"""
Comprehensive Value Detector Tool - Identifies all types of extractable value
Now uses unified pricing system for accurate historical pricing data.
"""

import time
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from .base import BaseTool, ToolResult
from ..web3_client import Web3Client
from ..pricing import PricingOracle, TokenRegistry


@dataclass
class ValueItem:
    """Represents a detected value item"""
    asset_type: str  # "erc20", "lp_token", "vault_share", "governance", "nft", etc.
    token_address: str
    amount: float
    estimated_value_eth: float
    estimated_value_usd: float
    confidence: float  # 0.0 to 1.0
    detection_method: str
    metadata: Dict[str, Any]


class ComprehensiveValueDetector(BaseTool):
    """
    Advanced value detection that identifies multiple asset types and their values
    """
    
    # NOTE: Token addresses and DEX routers now managed by TokenRegistry and PricingOracle
    
    def __init__(self, config):
        super().__init__(config)
        self.web3_client = Web3Client(config)
        self.pricing_oracle = PricingOracle(config, self.web3_client)
        
    def get_name(self) -> str:
        return "comprehensive_value_detector"
        
    def get_description(self) -> str:
        return "Detects and values all types of extractable assets including tokens, LP shares, NFTs, and governance rights"
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Comprehensive value detection and measurement
        
        Args:
            params: {
                "contract_address": str - Contract to analyze
                "chain_id": int - Blockchain to analyze on
                "block_number": int - Historical block (optional)
                "detection_scope": str - "basic", "comprehensive", "deep" (optional)
                "exploit_contract": str - Address of exploit contract to check balances (optional)
                "execution_result": ToolResult - Result from execution tool (optional)
            }
        """
        start_time = time.time()
        
        try:
            contract_address = params.get("contract_address", "")
            exploit_contract = params.get("exploit_contract", contract_address)
            chain_id = params.get("chain_id", 1)
            block_number = params.get("block_number")
            scope = params.get("detection_scope", "comprehensive")
            execution_result = params.get("execution_result")
            
            if not contract_address:
                return ToolResult(
                    success=False,
                    data={},
                    error_message="Contract address required",
                    tool_name=self.get_name()
                )
            
            self.logger.info(f"🔍 Starting comprehensive value detection for {contract_address}")
            self.logger.info(f"🎯 Exploit contract: {exploit_contract}")
            self.logger.info(f"📊 Detection scope: {scope}")
            self.logger.info(f"🔍 Execution result data keys: {list(execution_result.data.keys()) if execution_result and execution_result.data else 'No execution data'}")
            
            detected_values = []
            
            # First, check if we have execution results to use as baseline
            if execution_result and execution_result.data:
                exec_data = execution_result.data
                eth_gained = exec_data.get("eth_gained", 0.0)
                tokens_extracted = exec_data.get("tokens_extracted", {})
                
                self.logger.info(f"🔍 Found execution results: {eth_gained:.6f} ETH, {len(tokens_extracted)} token types")
                self.logger.info(f"🔍 Tokens extracted details: {tokens_extracted}")
                
                # Add ETH gained from execution
                if eth_gained > 0:
                    detected_values.append(ValueItem(
                        asset_type="native_currency_gained",
                        token_address="ETH" if chain_id == 1 else "BNB",
                        amount=eth_gained,
                        estimated_value_eth=eth_gained,
                        estimated_value_usd=eth_gained * await self._get_eth_price_usd(chain_id, block_number),
                        confidence=1.0,
                        detection_method="foundry_execution",
                        metadata={"source": "concrete_execution_tool"}
                    ))
                
                # Add tokens extracted from execution - FIX: Handle different formats
                for token_addr, amount in tokens_extracted.items():
                    if amount > 0:
                        # FIXED: tokens_extracted from execution tool contains raw wei amounts
                        # For the uerii contract, we see 300000000000000000 which is 0.3 tokens (18 decimals)
                        try:
                            # Try to get token decimals from contract
                            decimals = await self._get_token_decimals(token_addr, chain_id, block_number)
                            if decimals is None:
                                # Default to 18 decimals for unknown tokens (standard ERC20)
                                decimals = 18
                                self.logger.info(f"🔢 Using default 18 decimals for unknown token {token_addr}")
                            else:
                                self.logger.info(f"🔢 Retrieved {decimals} decimals from contract for {token_addr}")
                        except Exception as e:
                            self.logger.warning(f"Failed to get token decimals: {e}, assuming 18")
                            decimals = 18
                        
                        # Convert from raw amount to token units
                        token_amount = amount / (10**decimals)
                        
                        # Use unified pricing oracle for accurate valuation
                        usd_value = await self.pricing_oracle.convert_token_to_usd(
                            token_addr, token_amount, chain_id, block_number
                        )
                        eth_value = await self.pricing_oracle.normalize_to_base_currency(
                            token_addr, token_amount, chain_id, block_number
                        )
                        
                        if usd_value is None:
                            usd_value = 0.0
                        if eth_value is None:
                            eth_value = 0.0
                        
                        detected_values.append(ValueItem(
                            asset_type="erc20_token_extracted",
                            token_address=token_addr,
                            amount=token_amount,
                            estimated_value_eth=eth_value,
                            estimated_value_usd=usd_value,
                            confidence=0.9,
                            detection_method="foundry_execution",
                            metadata={
                                "source": "concrete_execution_tool", 
                                "raw_amount": amount,
                                "decimals": decimals
                            }
                        ))
                
                # FIXED: Use ETH_EQUIVALENT as the authoritative total value from execution
                foundry_output = exec_data.get("foundry_output", "")
                if foundry_output:
                    # Look for ETH_EQUIVALENT which represents total value in wei
                    import re
                    eth_equiv_match = re.search(r'ETH_EQUIVALENT:\s*(\d+)', foundry_output)
                    if eth_equiv_match:
                        total_eth_equivalent_wei = int(eth_equiv_match.group(1))
                        total_eth_equivalent = total_eth_equivalent_wei / 10**18
                        self.logger.info(f"🎯 Found ETH_EQUIVALENT from execution: {total_eth_equivalent:.6f} ETH (from {total_eth_equivalent_wei} wei)")
                        
                        # FIXED: Don't add to existing values, replace them with authoritative execution result
                        # The ETH_EQUIVALENT already includes both ETH and token values converted to ETH
                        detected_values = []  # Clear any estimates
                        detected_values.append(ValueItem(
                            asset_type="total_execution_value",
                            token_address="ETH_EQUIVALENT_TOTAL",
                            amount=total_eth_equivalent,
                            estimated_value_eth=total_eth_equivalent,
                            estimated_value_usd=total_eth_equivalent * await self._get_eth_price_usd(chain_id),
                            confidence=1.0,
                            detection_method="foundry_execution_total",
                            metadata={
                                "source": "ETH_EQUIVALENT_authoritative", 
                                "total_eth_equivalent_wei": total_eth_equivalent_wei,
                                "replaces_individual_estimates": True
                            }
                        ))
            
            # If we already have good results from execution, we can skip the complex Web3 calls
            # that were failing due to contract function call issues
            if detected_values and scope != "deep":
                self.logger.info("✅ Using execution results directly - skipping Web3 queries that were failing")
            else:
                # Only run Web3-based detection if we need more detail or have no execution results
                self.logger.info("🌐 Running additional Web3-based value detection...")
                
                try:
                    # Phase 1: Direct token detection (with error handling)
                    erc20_values = await self._detect_erc20_tokens(
                        chain_id, contract_address, exploit_contract, block_number
                    )
                    detected_values.extend(erc20_values)
                except Exception as e:
                    self.logger.warning(f"ERC20 detection failed: {e}")
                
                try:
                    # Phase 2: LP token detection
                    if scope in ["comprehensive", "deep"]:
                        lp_values = await self._detect_lp_tokens(
                            chain_id, contract_address, exploit_contract, block_number
                        )
                        detected_values.extend(lp_values)
                except Exception as e:
                    self.logger.warning(f"LP token detection failed: {e}")
                
                try:
                    # Phase 3: Vault shares and synthetic assets
                    if scope in ["comprehensive", "deep"]:
                        vault_values = await self._detect_vault_shares(
                            chain_id, contract_address, exploit_contract, block_number
                        )
                        detected_values.extend(vault_values)
                except Exception as e:
                    self.logger.warning(f"Vault detection failed: {e}")
                
                try:
                    # Phase 4: Governance and reward tokens
                    if scope == "deep":
                        gov_values = await self._detect_governance_value(
                            chain_id, contract_address, exploit_contract, block_number
                        )
                        detected_values.extend(gov_values)
                except Exception as e:
                    self.logger.warning(f"Governance detection failed: {e}")
                
                try:
                    # Phase 5: NFTs and unique assets
                    if scope == "deep":
                        nft_values = await self._detect_nfts(
                            chain_id, contract_address, exploit_contract, block_number
                        )
                        detected_values.extend(nft_values)
                except Exception as e:
                    self.logger.warning(f"NFT detection failed: {e}")
            
            # Calculate total values
            total_eth = sum(item.estimated_value_eth for item in detected_values)
            total_usd = sum(item.estimated_value_usd for item in detected_values)
            
            # Determine overall profitability
            is_profitable = total_usd > 10.0 or total_eth > 0.01
            
            execution_time = time.time() - start_time
            
            result_data = {
                "total_value_eth": total_eth,
                "total_value_usd": total_usd,
                "is_profitable": is_profitable,
                "items_detected": len(detected_values),
                "detection_scope": scope,
                "value_items": [self._value_item_to_dict(item) for item in detected_values],
                "value_by_type": self._group_values_by_type(detected_values),
                "contract_address": contract_address,
                "exploit_contract": exploit_contract,
                "chain_id": chain_id,
                "block_number": block_number
            }
            
            self.logger.info(
                f"💰 Value detection complete: {len(detected_values)} items, "
                f"{total_eth:.6f} ETH (${total_usd:.2f}) - Profitable: {is_profitable}"
            )
            
            return ToolResult(
                success=True,
                data=result_data,
                execution_time=execution_time,
                tool_name=self.get_name()
            )
            
        except Exception as e:
            self.logger.error(f"Value detection failed: {str(e)}")
            return ToolResult(
                success=False,
                data={},
                error_message=f"Value detection error: {str(e)}",
                execution_time=time.time() - start_time,
                tool_name=self.get_name()
            )
    
    async def _detect_erc20_tokens(
        self, 
        chain_id: int, 
        contract_address: str,
        exploit_contract: str,
        block_number: Optional[int]
    ) -> List[ValueItem]:
        """Detect standard ERC20 tokens and stablecoins"""
        
        values = []
        known_tokens = TokenRegistry.get_all_tokens(chain_id)
        
        # Check ETH balance first
        eth_balance = await self._get_eth_balance(exploit_contract, chain_id, block_number)
        if eth_balance > 0:
            eth_usd = eth_balance * await self._get_eth_price_usd(chain_id, block_number)
            base_currency = TokenRegistry.get_base_currency(chain_id)
            values.append(ValueItem(
                asset_type="native_currency",
                token_address=base_currency,
                amount=eth_balance,
                estimated_value_eth=eth_balance,
                estimated_value_usd=eth_usd,
                confidence=1.0,
                detection_method="web3_balance",
                metadata={"is_native": True}
            ))
        
        # Check known ERC20 tokens
        for symbol, token_info in known_tokens.items():
            try:
                balance = await self._get_token_balance(
                    token_info.address, exploit_contract, chain_id, block_number
                )
                
                if balance > 0:
                    eth_value, usd_value = await self._get_token_value(
                        token_info.address, balance, chain_id, block_number
                    )
                    
                    values.append(ValueItem(
                        asset_type="erc20_token",
                        token_address=token_info.address,
                        amount=balance,
                        estimated_value_eth=eth_value,
                        estimated_value_usd=usd_value,
                        confidence=0.9,
                        detection_method="known_token_list",
                        metadata={"symbol": symbol, "is_stablecoin": token_info.is_stablecoin}
                    ))
                    
            except Exception as e:
                self.logger.debug(f"Failed to check token {symbol}: {e}")
                continue
        
        return values
    
    async def _detect_lp_tokens(
        self,
        chain_id: int,
        contract_address: str, 
        exploit_contract: str,
        block_number: Optional[int]
    ) -> List[ValueItem]:
        """Detect Uniswap V2/V3 style LP tokens"""
        
        values = []
        
        # Check if the contract itself is an LP token
        try:
            # Uniswap V2 pattern
            reserves_call = await self.web3_client.call_contract_function(
                chain_id,
                contract_address,
                {"name": "getReserves", "type": "function", "stateMutability": "view", 
                 "inputs": [], "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}]},
                [],
                block_number
            )
            
            if reserves_call:
                # This is an LP token, check exploit contract's balance
                lp_balance = await self._get_token_balance(
                    contract_address, exploit_contract, chain_id, block_number
                )
                
                if lp_balance > 0:
                    # Calculate underlying value
                    token0 = await self.web3_client.call_contract_function(
                        chain_id, contract_address,
                        {"name": "token0", "type": "function", "stateMutability": "view",
                         "inputs": [], "outputs": [{"type": "address"}]},
                        [], block_number
                    )
                    
                    token1 = await self.web3_client.call_contract_function(
                        chain_id, contract_address,
                        {"name": "token1", "type": "function", "stateMutability": "view", 
                         "inputs": [], "outputs": [{"type": "address"}]},
                        [], block_number
                    )
                    
                    total_supply = await self.web3_client.call_contract_function(
                        chain_id, contract_address,
                        {"name": "totalSupply", "type": "function", "stateMutability": "view",
                         "inputs": [], "outputs": [{"type": "uint256"}]},
                        [], block_number
                    )
                    
                    if token0 and token1 and total_supply and total_supply > 0:
                        # Calculate share of pool
                        pool_share = lp_balance / total_supply
                        reserve0, reserve1 = reserves_call[0], reserves_call[1]
                        
                        # Estimate value (simplified)
                        underlying0 = reserve0 * pool_share
                        underlying1 = reserve1 * pool_share
                        
                        # Get token values
                        eth_value0, usd_value0 = await self._get_token_value(
                            token0, underlying0, chain_id, block_number
                        )
                        eth_value1, usd_value1 = await self._get_token_value(
                            token1, underlying1, chain_id, block_number
                        )
                        
                        total_eth_value = eth_value0 + eth_value1
                        total_usd_value = usd_value0 + usd_value1
                        
                        values.append(ValueItem(
                            asset_type="lp_token", 
                            token_address=contract_address,
                            amount=lp_balance,
                            estimated_value_eth=total_eth_value,
                            estimated_value_usd=total_usd_value,
                            confidence=0.8,
                            detection_method="uniswap_v2_pattern",
                            metadata={
                                "token0": token0,
                                "token1": token1,
                                "pool_share": pool_share,
                                "underlying0": underlying0,
                                "underlying1": underlying1
                            }
                        ))
                        
        except Exception as e:
            self.logger.debug(f"LP token detection failed: {e}")
        
        return values
    
    async def _detect_vault_shares(
        self,
        chain_id: int,
        contract_address: str,
        exploit_contract: str, 
        block_number: Optional[int]
    ) -> List[ValueItem]:
        """Detect Yearn vaults, Compound cTokens, Aave aTokens"""
        
        values = []
        
        # Check for Compound cToken pattern
        try:
            exchange_rate = await self.web3_client.call_contract_function(
                chain_id, contract_address,
                {"name": "exchangeRateStored", "type": "function", "stateMutability": "view",
                 "inputs": [], "outputs": [{"type": "uint256"}]},
                [], block_number
            )
            
            if exchange_rate:
                ctoken_balance = await self._get_token_balance(
                    contract_address, exploit_contract, chain_id, block_number
                )
                
                if ctoken_balance > 0:
                    # Get underlying token
                    underlying = await self.web3_client.call_contract_function(
                        chain_id, contract_address,
                        {"name": "underlying", "type": "function", "stateMutability": "view",
                         "inputs": [], "outputs": [{"type": "address"}]},
                        [], block_number
                    )
                    
                    if underlying:
                        underlying_amount = (ctoken_balance * exchange_rate) // (10**18)
                        eth_value, usd_value = await self._get_token_value(
                            underlying, underlying_amount, chain_id, block_number
                        )
                        
                        values.append(ValueItem(
                            asset_type="compound_ctoken",
                            token_address=contract_address,
                            amount=ctoken_balance,
                            estimated_value_eth=eth_value,
                            estimated_value_usd=usd_value,
                            confidence=0.9,
                            detection_method="compound_pattern",
                            metadata={
                                "underlying_token": underlying,
                                "underlying_amount": underlying_amount,
                                "exchange_rate": exchange_rate
                            }
                        ))
                        
        except Exception as e:
            self.logger.debug(f"Compound cToken detection failed: {e}")
        
        # Check for Yearn vault pattern
        try:
            price_per_share = await self.web3_client.call_contract_function(
                chain_id, contract_address,
                {"name": "pricePerShare", "type": "function", "stateMutability": "view",
                 "inputs": [], "outputs": [{"type": "uint256"}]},
                [], block_number
            )
            
            if price_per_share:
                vault_balance = await self._get_token_balance(
                    contract_address, exploit_contract, chain_id, block_number
                )
                
                if vault_balance > 0:
                    underlying_token = await self.web3_client.call_contract_function(
                        chain_id, contract_address,
                        {"name": "token", "type": "function", "stateMutability": "view",
                         "inputs": [], "outputs": [{"type": "address"}]},
                        [], block_number
                    )
                    
                    if underlying_token:
                        underlying_amount = (vault_balance * price_per_share) // (10**18)
                        eth_value, usd_value = await self._get_token_value(
                            underlying_token, underlying_amount, chain_id, block_number
                        )
                        
                        values.append(ValueItem(
                            asset_type="yearn_vault",
                            token_address=contract_address,
                            amount=vault_balance,
                            estimated_value_eth=eth_value,
                            estimated_value_usd=usd_value,
                            confidence=0.9,
                            detection_method="yearn_pattern",
                            metadata={
                                "underlying_token": underlying_token,
                                "underlying_amount": underlying_amount,
                                "price_per_share": price_per_share
                            }
                        ))
                        
        except Exception as e:
            self.logger.debug(f"Yearn vault detection failed: {e}")
        
        return values
    
    async def _detect_governance_value(
        self,
        chain_id: int,
        contract_address: str,
        exploit_contract: str,
        block_number: Optional[int]
    ) -> List[ValueItem]:
        """Detect governance tokens and voting power"""
        
        values = []
        
        # Check for standard governance patterns
        governance_functions = [
            "getVotes",
            "votingPower", 
            "earned",
            "pendingReward",
            "claimableReward"
        ]
        
        for func_name in governance_functions:
            try:
                result = await self.web3_client.call_contract_function(
                    chain_id, contract_address,
                    {"name": func_name, "type": "function", "stateMutability": "view",
                     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
                    [exploit_contract], block_number
                )
                
                if result and result > 0:
                    # Estimate governance value (this is complex - simplified here)
                    estimated_eth = result * 0.001  # Rough estimate: 0.1% of face value
                    estimated_usd = estimated_eth * await self._get_eth_price_usd(chain_id)
                    
                    values.append(ValueItem(
                        asset_type="governance_rights",
                        token_address=contract_address,
                        amount=result,
                        estimated_value_eth=estimated_eth,
                        estimated_value_usd=estimated_usd,
                        confidence=0.3,  # Low confidence due to estimation
                        detection_method=f"governance_{func_name}",
                        metadata={"function": func_name, "raw_amount": result}
                    ))
                    
            except Exception as e:
                self.logger.debug(f"Governance detection for {func_name} failed: {e}")
                continue
        
        return values
    
    async def _detect_nfts(
        self,
        chain_id: int,
        contract_address: str,
        exploit_contract: str,
        block_number: Optional[int]
    ) -> List[ValueItem]:
        """Detect NFTs and estimate floor prices"""
        
        values = []
        
        # Check ERC721 interface
        try:
            # Check if contract supports ERC721
            supports_721 = await self.web3_client.call_contract_function(
                chain_id, contract_address,
                {"name": "supportsInterface", "type": "function", "stateMutability": "view",
                 "inputs": [{"type": "bytes4"}], "outputs": [{"type": "bool"}]},
                ["0x80ac58cd"], block_number  # ERC721 interface ID
            )
            
            if supports_721:
                nft_balance = await self.web3_client.call_contract_function(
                    chain_id, contract_address,
                    {"name": "balanceOf", "type": "function", "stateMutability": "view",
                     "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
                    [exploit_contract], block_number
                )
                
                if nft_balance and nft_balance > 0:
                    # Rough NFT valuation (would need external price APIs)
                    estimated_floor_price_eth = 0.01  # Conservative 0.01 ETH per NFT
                    total_eth_value = nft_balance * estimated_floor_price_eth
                    total_usd_value = total_eth_value * await self._get_eth_price_usd(chain_id)
                    
                    values.append(ValueItem(
                        asset_type="erc721_nft",
                        token_address=contract_address,
                        amount=nft_balance,
                        estimated_value_eth=total_eth_value,
                        estimated_value_usd=total_usd_value,
                        confidence=0.2,  # Very low confidence without real pricing
                        detection_method="erc721_balance",
                        metadata={
                            "estimated_floor_price_eth": estimated_floor_price_eth,
                            "nft_count": nft_balance
                        }
                    ))
                    
        except Exception as e:
            self.logger.debug(f"NFT detection failed: {e}")
        
        return values
    
    # Helper methods
    async def _get_eth_balance(self, address: str, chain_id: int, block_number: Optional[int]) -> float:
        """Get ETH balance in ETH units"""
        try:
            balance_wei = await self.web3_client.get_balance(chain_id, address, block_number)
            return balance_wei / 10**18
        except:
            return 0.0
    
    async def _get_token_balance(
        self, token_address: str, holder_address: str, chain_id: int, block_number: Optional[int]
    ) -> float:
        """Get ERC20 token balance for an address"""
        
        try:
            # ERC20 balanceOf function ABI
            balance_abi = {
                "name": "balanceOf",
                "type": "function", 
                "stateMutability": "view",
                "inputs": [{"name": "account", "type": "address"}],
                "outputs": [{"type": "uint256"}]
            }
            
            balance_wei = await self.web3_client.call_contract_function(
                chain_id,
                token_address,
                balance_abi,
                [holder_address],
                block_number
            )
            
            if balance_wei is not None:
                # Get token decimals for proper conversion
                decimals = await self._get_token_decimals(token_address, chain_id, block_number)
                if decimals is not None:
                    return balance_wei / (10**decimals)
                else:
                    # Fallback to 18 decimals
                    return balance_wei / 10**18
            
            return 0.0
            
        except Exception as e:
            self.logger.debug(f"Failed to get token balance: {e}")
            return 0.0
    
    async def _get_token_decimals(
        self, token_address: str, chain_id: int, block_number: Optional[int]
    ) -> Optional[int]:
        """Get ERC20 token decimals"""
        
        try:
            # ERC20 decimals function ABI
            decimals_abi = {
                "name": "decimals",
                "type": "function",
                "stateMutability": "view", 
                "inputs": [],
                "outputs": [{"type": "uint8"}]
            }
            
            decimals = await self.web3_client.call_contract_function(
                chain_id,
                token_address,
                decimals_abi,
                [],
                block_number
            )
            
            return decimals if decimals is not None else None
            
        except Exception as e:
            self.logger.debug(f"Failed to get token decimals for {token_address}: {e}")
            return None
    
    async def _get_token_value(
        self, token_address: str, amount: float, chain_id: int, block_number: Optional[int]
    ) -> Tuple[float, float]:
        """Get token value in ETH and USD using unified pricing oracle"""
        try:
            # Use unified pricing oracle for accurate valuation
            usd_value = await self.pricing_oracle.convert_token_to_usd(
                token_address, amount, chain_id, block_number
            )
            eth_value = await self.pricing_oracle.normalize_to_base_currency(
                token_address, amount, chain_id, block_number
            )
            
            if usd_value is None:
                usd_value = 0.0
            if eth_value is None:
                eth_value = 0.0
            
            return eth_value, usd_value
                
        except Exception as e:
            self.logger.debug(f"Token valuation failed for {token_address}: {e}")
            return 0.0, 0.0
    
    async def _get_eth_price_usd(self, chain_id: int, block_number: Optional[int] = None) -> float:
        """Get ETH/BNB price in USD using unified pricing oracle"""
        base_currency_price = await self.pricing_oracle.get_base_currency_price(chain_id, block_number)
        if base_currency_price:
            return base_currency_price.price_usd
        
        # Fallback rates
        return 3200.0 if chain_id == 1 else 650.0
    
    def _value_item_to_dict(self, item: ValueItem) -> Dict[str, Any]:
        """Convert ValueItem to dictionary"""
        return {
            "asset_type": item.asset_type,
            "token_address": item.token_address,
            "amount": item.amount,
            "estimated_value_eth": item.estimated_value_eth,
            "estimated_value_usd": item.estimated_value_usd,
            "confidence": item.confidence,
            "detection_method": item.detection_method,
            "metadata": item.metadata
        }
    
    def _group_values_by_type(self, values: List[ValueItem]) -> Dict[str, Dict[str, float]]:
        """Group detected values by asset type"""
        grouped = {}
        for item in values:
            if item.asset_type not in grouped:
                grouped[item.asset_type] = {"count": 0, "total_eth": 0.0, "total_usd": 0.0}
            
            grouped[item.asset_type]["count"] += 1
            grouped[item.asset_type]["total_eth"] += item.estimated_value_eth
            grouped[item.asset_type]["total_usd"] += item.estimated_value_usd
        
        return grouped 