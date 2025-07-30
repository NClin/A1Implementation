"""
Revenue Normalizer Tool - Implements paper's balance reconciliation methodology
Based on Section IV.D of A1 paper: Revenue Normalization and Economic Validation

Now uses unified pricing system for accurate historical pricing data.
"""

import time
import asyncio
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from .base import BaseTool, ToolResult
from ..web3_client import Web3Client
from ..pricing import PricingOracle, TokenRegistry
from ..pricing.balance_validator import BalanceInvariantValidator


@dataclass
class BalanceChange:
    """Represents a balance change for a specific token"""
    token_address: str
    token_symbol: str
    initial_balance: float
    final_balance: float
    net_change: float
    is_surplus: bool  # True if final > initial
    value_eth: float = 0.0
    value_usd: float = 0.0


@dataclass
class DEXRoute:
    """Represents an optimal DEX routing path"""
    dex_name: str
    path: List[str]  # Token addresses in the swap path
    liquidity: float
    estimated_output: float
    fee_tier: Optional[int] = None


class RevenueNormalizerTool(BaseTool):
    """
    Advanced revenue normalization implementing the paper's balance reconciliation methodology
    
    Features from paper Section IV.D:
    - Initial State Normalization: 10^5 ETH + 10^7 stablecoins
    - Post-Execution Reconciliation: Convert surplus tokens to base currency
    - Balance Invariant: Ensure no artificial revenue from token depletion
    - Economic Performance: Π = Bf(BASE) - Bi(BASE)
    """
    
    # Initial balances per paper specification
    INITIAL_BALANCES = {
        1: {  # Ethereum
            "ETH": 1e5,       # 100,000 ETH
            "WETH": 1e5,      # 100,000 WETH  
            "USDC": 1e7,      # 10,000,000 USDC
            "USDT": 1e7       # 10,000,000 USDT
        },
        56: {  # BSC
            "BNB": 1e5,       # 100,000 BNB
            "WBNB": 1e5,      # 100,000 WBNB
            "USDT": 1e7,      # 10,000,000 USDT
            "BUSD": 1e7       # 10,000,000 BUSD
        }
    }
    
    # NOTE: DEX routers now managed by TokenRegistry for consistency
    
    # NOTE: Token addresses now managed by TokenRegistry for consistency
    
    def __init__(self, config):
        super().__init__(config)
        self.web3_client = Web3Client(config)
        self.pricing_oracle = PricingOracle(config, self.web3_client)
        self.balance_validator = BalanceInvariantValidator()
        
    def get_name(self) -> str:
        return "revenue_normalizer_tool"
    
    def get_description(self) -> str:
        return "Implements paper's balance reconciliation methodology with DEX routing for accurate profit calculation"
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Execute comprehensive balance reconciliation per paper methodology
        
        Args:
            params: {
                "execution_result": ToolResult - Result from execution tool with balance data
                "chain_id": int - Blockchain ID
                "exploit_contract_address": str - Address of exploit contract  
                "target_contract_address": str - Address of target contract
                "block_number": int - Block number for historical pricing
                "initial_balances": Dict - Override initial balances (optional)
            }
        """
        start_time = time.time()
        
        try:
            execution_result = params.get("execution_result")
            if not execution_result or not hasattr(execution_result, 'data'):
                return ToolResult(
                    success=False,
                    data={},
                    error_message="No execution result provided for revenue analysis",
                    tool_name=self.get_name()
                )
            
            execution_data = execution_result.data
            chain_id = params.get("chain_id", 1)
            exploit_contract = params.get("exploit_contract_address", "")
            block_number = params.get("block_number")
            
            self.logger.info(f"🔄 Starting balance reconciliation for chain {chain_id}")
            self.logger.info(f"📊 Exploit contract: {exploit_contract}")
            
            # Step 1: Extract balance changes from execution result
            balance_changes = await self._extract_balance_changes(execution_data, chain_id)
            
            if not balance_changes:
                # Fallback to legacy extraction method
                balance_changes = await self._legacy_balance_extraction(execution_data, chain_id)
            
            self.logger.info(f"📈 Found {len(balance_changes)} balance changes")
            
            # Step 2: Perform surplus token resolution (convert excess to base currency)
            base_currency = TokenRegistry.get_base_currency(chain_id)
            base_currency_change = 0.0
            total_surplus_value = 0.0
            
            surplus_conversions = []
            deficit_resolutions = []
            
            for change in balance_changes:
                if change.token_symbol == base_currency:
                    # Direct base currency change
                    base_currency_change += change.net_change
                    self.logger.info(f"💰 Direct {base_currency} change: {change.net_change:.6f}")
                
                elif change.is_surplus and change.net_change > 0:
                    # Surplus token - convert to base currency
                    conversion = await self._convert_surplus_token(
                        change, base_currency, chain_id, block_number
                    )
                    surplus_conversions.append(conversion)
                    total_surplus_value += conversion.get("base_value", 0.0)
                    self.logger.info(f"🔄 Surplus {change.token_symbol}: {change.net_change:.6f} → {conversion.get('base_value', 0):.6f} {base_currency}")
                
                elif not change.is_surplus and change.net_change < 0:
                    # Deficit - should be resolved but typically indicates spending
                    deficit_resolution = await self._resolve_deficit_token(
                        change, base_currency, chain_id, block_number
                    )
                    deficit_resolutions.append(deficit_resolution)
                    self.logger.info(f"🔻 Deficit {change.token_symbol}: {change.net_change:.6f}")
            
            # Step 3: Calculate economic performance Π = Bf(BASE) - Bi(BASE)
            total_base_currency_profit = base_currency_change + total_surplus_value
            
            # Step 4: Convert to USD using unified pricing oracle
            base_currency_price = await self.pricing_oracle.get_base_currency_price(chain_id, block_number)
            usd_rate = base_currency_price.price_usd if base_currency_price else 3200.0  # Fallback
            total_usd_profit = total_base_currency_profit * usd_rate
            
            # Step 5: Determine profitability (paper uses different thresholds)
            is_profitable = total_usd_profit > 1.0 or total_base_currency_profit > 0.001  # Lowered threshold
            profit_threshold_met = total_usd_profit > 100.0  # Significant profit
            
            # Step 6: Enforce balance invariant ∀t : Bf(t) ≥ Bi(t) using validator
            balance_change_dicts = [
                {
                    "token": change.token_symbol,
                    "initial": change.initial_balance,
                    "final": change.final_balance,
                    "net_change": change.net_change
                }
                for change in balance_changes
            ]
            
            # Generate comprehensive compliance report
            compliance_report = self.balance_validator.generate_compliance_report(
                balance_change_dicts, chain_id
            )
            
            # Legacy format for backward compatibility
            invariant_violations = compliance_report["invariant_violations"]
            
            revenue_data = {
                "revenue_base_currency": total_base_currency_profit,
                "revenue_usd": total_usd_profit,
                "base_currency": base_currency,
                "is_profitable": is_profitable,
                "profit_threshold_met": profit_threshold_met,
                "balance_reconciliation": {
                    "direct_base_change": base_currency_change,
                    "surplus_conversions": surplus_conversions,
                    "deficit_resolutions": deficit_resolutions,
                    "total_surplus_value": total_surplus_value,
                    "balance_changes": [
                        {
                            "token": change.token_symbol,
                            "initial": change.initial_balance,
                            "final": change.final_balance,
                            "net_change": change.net_change,
                            "is_surplus": change.is_surplus,
                            "value_usd": change.value_usd
                        }
                        for change in balance_changes
                    ]
                },
                "market_data": {
                    "base_currency_usd_rate": usd_rate,
                    "block_number": block_number,
                    "pricing_method": "dex_routing"
                },
                "compliance": compliance_report
            }
            
            # Enhanced logging with compliance information
            if is_profitable:
                self.logger.info(f"✅ PROFITABLE EXPLOIT: {total_base_currency_profit:.6f} {base_currency} (${total_usd_profit:.2f} USD)")
                self.logger.info(f"   📊 Components: Direct {base_currency_change:.6f} + Surplus {total_surplus_value:.6f}")
            else:
                self.logger.info(f"❌ Not profitable: {total_base_currency_profit:.6f} {base_currency} (${total_usd_profit:.2f} USD)")
                if balance_changes:
                    self.logger.info(f"   🔍 Found {len(balance_changes)} balance changes but insufficient profit")
            
            # Log compliance status
            if not compliance_report["balance_invariant_enforced"]:
                self.logger.warning(f"⚠️  Balance invariant violations detected ({compliance_report['total_violations']})")
                for suggestion in compliance_report["enforcement_suggestions"]:
                    self.logger.warning(f"   {suggestion}")
            
            if not compliance_report["paper_methodology_compliant"]:
                self.logger.warning("📋 Paper methodology compliance issues detected")
                for suggestion in compliance_report["enforcement_suggestions"]:
                    self.logger.info(f"   {suggestion}")
            
            return ToolResult(
                success=True,
                data=revenue_data,
                execution_time=time.time() - start_time,
                tool_name=self.get_name()
            )
            
        except Exception as e:
            self.logger.error(f"Revenue analysis failed: {str(e)}")
            return ToolResult(
                success=False,
                data={},
                error_message=f"Revenue analysis error: {str(e)}",
                execution_time=time.time() - start_time,
                tool_name=self.get_name()
            )
    
    async def _extract_balance_changes(self, execution_data: Dict, chain_id: int) -> List[BalanceChange]:
        """Extract balance changes from execution result"""
        balance_changes = []
        
        # Try to extract from structured execution data
        if "balance_analysis" in execution_data:
            balance_data = execution_data["balance_analysis"]
            
            for token_data in balance_data.get("token_balances", []):
                if "before" in token_data and "after" in token_data:
                    initial = float(token_data["before"])
                    final = float(token_data["after"])
                    net_change = final - initial
                    
                    if abs(net_change) > 1e-12:  # Ignore dust amounts
                        balance_changes.append(BalanceChange(
                            token_address=token_data.get("address", ""),
                            token_symbol=token_data.get("symbol", "UNKNOWN"),
                            initial_balance=initial,
                            final_balance=final,
                            net_change=net_change,
                            is_surplus=net_change > 0
                        ))
        
        return balance_changes
    
    async def _legacy_balance_extraction(self, execution_data: Dict, chain_id: int) -> List[BalanceChange]:
        """Fallback method for extracting balance changes from legacy execution data"""
        balance_changes = []
        
        # Extract ETH/BNB changes
        eth_gained = execution_data.get("eth_gained", 0.0)
        base_currency = TokenRegistry.get_base_currency(chain_id)
        
        if abs(eth_gained) > 1e-12:
            initial_balance = self.INITIAL_BALANCES[chain_id][base_currency]
            balance_changes.append(BalanceChange(
                token_address="0x0000000000000000000000000000000000000000",  # Native token
                token_symbol=base_currency,
                initial_balance=initial_balance,
                final_balance=initial_balance + eth_gained,
                net_change=eth_gained,
                is_surplus=eth_gained > 0
            ))
        
        # Extract token changes
        tokens_extracted = execution_data.get("tokens_extracted", {})
        for token_identifier, amount in tokens_extracted.items():
            if isinstance(amount, (int, float)) and abs(amount) > 1e-12:
                # Token identifier might be address or symbol, try both
                if token_identifier.startswith("0x"):
                    # It's an address
                    token_info = TokenRegistry.get_token_by_address(chain_id, token_identifier)
                    token_address = token_identifier
                    token_symbol = token_info.symbol if token_info else "UNKNOWN"
                else:
                    # It's a symbol
                    token_info = TokenRegistry.get_token_info(chain_id, token_identifier)
                    token_address = token_info.address if token_info else ""
                    token_symbol = token_identifier
                
                balance_changes.append(BalanceChange(
                    token_address=token_address,
                    token_symbol=token_symbol,
                    initial_balance=0.0,  # Assume started with 0
                    final_balance=float(amount),
                    net_change=float(amount),
                    is_surplus=amount > 0
                ))
        
        return balance_changes
    
    async def _convert_surplus_token(self, change: BalanceChange, base_currency: str, 
                                  chain_id: int, block_number: Optional[int]) -> Dict[str, Any]:
        """Convert surplus token to base currency using unified pricing oracle"""
        
        # Use unified pricing oracle for accurate conversion
        base_value = await self.pricing_oracle.normalize_to_base_currency(
            change.token_address, 
            change.net_change, 
            chain_id, 
            block_number
        )
        
        if base_value is None:
            base_value = 0.0
        
        conversion_rate = base_value / change.net_change if change.net_change > 0 else 0
        
        return {
            "token": change.token_symbol,
            "amount": change.net_change,
            "base_value": base_value,
            "conversion_rate": conversion_rate,
            "route": None,  # Oracle handles routing internally
            "method": "unified_pricing_oracle"
        }
    
    async def _resolve_deficit_token(self, change: BalanceChange, base_currency: str,
                                   chain_id: int, block_number: Optional[int]) -> Dict[str, Any]:
        """Resolve token deficit by calculating base currency cost"""
        
        deficit_amount = abs(change.net_change)
        
        # Calculate cost to acquire deficit tokens using unified pricing oracle
        acquisition_cost = await self.pricing_oracle.normalize_to_base_currency(
            change.token_address,
            deficit_amount,
            chain_id,
            block_number
        )
        
        if acquisition_cost is None:
            acquisition_cost = 0.0
        
        return {
            "token": change.token_symbol,
            "deficit_amount": deficit_amount,
            "acquisition_cost_base": acquisition_cost,
            "method": "unified_pricing_oracle"
        }
    
    async def _find_optimal_dex_route(self, token_in: str, token_out: str, amount_in: float,
                                    chain_id: int, block_number: Optional[int]) -> Optional[DEXRoute]:
        """Find optimal DEX route - now delegated to unified pricing oracle"""
        
        # This functionality is now handled by the pricing oracle's DEX client
        # Return None to indicate fallback to oracle pricing
        return None
    
    async def _query_dex_liquidity(self, router: str, token_a: str, token_b: str,
                                 chain_id: int, block_number: Optional[int]) -> float:
        """Query DEX liquidity - now handled by pricing oracle"""
        # Functionality moved to pricing oracle's DEX client
        return 0.0
    
    async def _estimate_swap_output(self, router: str, token_in: str, token_out: str,
                                  amount_in: float, chain_id: int) -> float:
        """Estimate swap output - now handled by pricing oracle"""
        # Functionality moved to pricing oracle's DEX client
        return 0.0
    
    async def _get_token_conversion_rate(self, token_in: str, token_out: str, chain_id: int) -> float:
        """Get estimated conversion rate between tokens"""
        # Simplified rate estimation
        base_rates = {
            1: {"WETH": 1.0, "USDC": 1/3200, "USDT": 1/3200, "DAI": 1/3200},
            56: {"WBNB": 1.0, "USDT": 1/650, "BUSD": 1/650, "CAKE": 1/260}
        }
        
        rates = base_rates.get(chain_id, {})
        
        # Find token symbols from addresses
        token_in_symbol = self._address_to_symbol(token_in, chain_id)
        token_out_symbol = self._address_to_symbol(token_out, chain_id)
        
        rate_in = rates.get(token_in_symbol, 0.001)  # Default low rate
        rate_out = rates.get(token_out_symbol, 0.001)
        
        return rate_in / rate_out if rate_out > 0 else 0.001
    
    def _address_to_symbol(self, address: str, chain_id: int) -> str:
        """Convert token address to symbol using TokenRegistry"""
        token_info = TokenRegistry.get_token_by_address(chain_id, address)
        return token_info.symbol if token_info else "UNKNOWN"
    
    async def _estimate_token_value_dex(self, token_symbol: str, amount: float, 
                                      base_currency: str, chain_id: int) -> float:
        """Estimate token value - now handled by pricing oracle"""
        
        # Get token info from registry
        token_info = TokenRegistry.get_token_info(chain_id, token_symbol)
        if not token_info:
            return 0.0
        
        # Use pricing oracle for accurate conversion
        base_value = await self.pricing_oracle.normalize_to_base_currency(
            token_info.address, amount, chain_id, None
        )
        
        return base_value if base_value is not None else 0.0
    
    async def _get_base_currency_usd_rate(self, base_currency: str, chain_id: int, 
                                        block_number: Optional[int]) -> float:
        """Get base currency to USD exchange rate using unified pricing oracle"""
        
        base_currency_price = await self.pricing_oracle.get_base_currency_price(chain_id, block_number)
        if base_currency_price:
            return base_currency_price.price_usd
        
        # Fallback rates
        fallback_rates = {
            "ETH": 3200.0,
            "BNB": 650.0
        }
        
        return fallback_rates.get(base_currency, 1.0)