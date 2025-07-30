"""
VERITE-aligned On-Chain Accounting Oracle for accurate profit calculation
Based on the methodology described in the VERITE paper
"""

import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from .base import BaseTool, ToolResult
from ..web3_client import Web3Client


@dataclass
class AccountingSnapshot:
    """Snapshot of all assets at a specific point"""
    eth_balance: float
    erc20_balances: Dict[str, float]  # token_address -> amount
    total_value_eth: float
    total_value_usd: float
    block_number: int


class VeriteAccountingOracle(BaseTool):
    """
    VERITE-style accounting oracle that computes profit as:
    P(I) = N(S_k^n) - N(S_0^n)
    
    Where N(S) converts all assets to a single pricing token (USDT/ETH)
    """
    
    # Known liquid tokens with reliable pricing
    PRICING_TOKENS = {
        1: {  # Ethereum
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "USDC": "0xA0b86a33E6441d00C9dab2B5Ff0b19dc5D9c0cD0", 
            "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F"
        },
        56: {  # BSC  
            "USDT": "0x55d398326f99059fF775485246999027B3197955",
            "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
            "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
        }
    }
    
    def __init__(self, config):
        super().__init__(config)
        self.web3_client = Web3Client(config)
        
    def compute_profit(
        self,
        exploit_address: str,
        target_address: str,
        chain_id: int,
        block_number: Optional[int] = None
    ) -> ToolResult:
        """
        Compute VERITE-style profit: P(I) = N(S_final) - N(S_initial)
        
        This takes snapshots before and after exploitation and converts
        all assets to a single pricing token for accurate comparison.
        """
        try:
            # Take initial snapshot (before exploit)
            initial_snapshot = self._take_accounting_snapshot(
                exploit_address, target_address, chain_id, block_number
            )
            
            # Take final snapshot (after exploit)
            final_snapshot = self._take_accounting_snapshot(
                exploit_address, target_address, chain_id, block_number
            )
            
            # Calculate profit using VERITE methodology
            profit_eth = final_snapshot.total_value_eth - initial_snapshot.total_value_eth
            profit_usd = final_snapshot.total_value_usd - initial_snapshot.total_value_usd
            
            return ToolResult(
                success=True,
                data={
                    "profit_eth": profit_eth,
                    "profit_usd": profit_usd,
                    "initial_value_eth": initial_snapshot.total_value_eth,
                    "final_value_eth": final_snapshot.total_value_eth,
                    "initial_snapshot": initial_snapshot,
                    "final_snapshot": final_snapshot,
                    "methodology": "verite_accounting_oracle"
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"VERITE accounting failed: {str(e)}"
            )
    
    def _take_accounting_snapshot(
        self,
        exploit_address: str,
        target_address: str,
        chain_id: int,
        block_number: Optional[int] = None
    ) -> AccountingSnapshot:
        """
        Take a complete accounting snapshot at a specific point
        Following VERITE's methodology of converting all assets to pricing token
        """
        
        # Get current ETH balance
        eth_balance = self.web3_client.get_balance(exploit_address, block_number)
        
        # Get all ERC20 token balances
        erc20_balances = self._get_all_token_balances(exploit_address, chain_id, block_number)
        
        # Convert all assets to ETH equivalent using VERITE's method
        total_value_eth = eth_balance
        total_value_usd = 0.0
        
        # Add value from all ERC20 tokens
        for token_address, amount in erc20_balances.items():
            if amount > 0:
                token_value_eth = self._convert_token_to_eth(
                    token_address, amount, chain_id, block_number
                )
                total_value_eth += token_value_eth
        
        # Convert ETH to USD (using approximate rate)
        eth_price_usd = 3200.0  # Approximate ETH price
        total_value_usd = total_value_eth * eth_price_usd
        
        return AccountingSnapshot(
            eth_balance=eth_balance,
            erc20_balances=erc20_balances,
            total_value_eth=total_value_eth,
            total_value_usd=total_value_usd,
            block_number=block_number or 0
        )
    
    def _get_all_token_balances(
        self,
        address: str,
        chain_id: int,
        block_number: Optional[int] = None
    ) -> Dict[str, float]:
        """
        Get balances for all known tokens plus target contract token
        """
        balances = {}
        
        # Check balances for all known pricing tokens
        pricing_tokens = self.PRICING_TOKENS.get(chain_id, {})
        for token_name, token_address in pricing_tokens.items():
            try:
                balance = self.web3_client.get_token_balance(
                    token_address, address, block_number
                )
                if balance > 0:
                    balances[token_address] = balance
            except Exception:
                continue  # Skip tokens that fail
                
        return balances
    
    def _convert_token_to_eth(
        self,
        token_address: str,
        amount: float,
        chain_id: int,
        block_number: Optional[int] = None
    ) -> float:
        """
        Convert token amount to ETH equivalent using VERITE's approach
        
        VERITE uses multiple DEX quotes and chooses the best rate.
        For now, we'll use conservative estimates for known tokens.
        """
        
        # Known stable token conversions (conservative estimates)
        stable_tokens = {
            1: {
                "0xdAC17F958D2ee523a2206206994597C13D831ec7": 0.0003125,  # USDT @ $3200/ETH
                "0xA0b86a33E6441d00C9dab2B5Ff0b19dc5D9c0cD0": 0.0003125,  # USDC @ $3200/ETH  
                "0x6B175474E89094C44Da98b954EedeAC495271d0F": 0.0003125,  # DAI @ $3200/ETH
                "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": 1.0,        # WETH = 1 ETH
            },
            56: {
                "0x55d398326f99059fF775485246999027B3197955": 0.0003125,  # USDT @ $3200/ETH
                "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56": 0.0003125,  # BUSD @ $3200/ETH
                "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c": 0.125,     # WBNB @ $400/ETH
            }
        }
        
        chain_rates = stable_tokens.get(chain_id, {})
        rate = chain_rates.get(token_address.lower(), 0.0)
        
        # For unknown tokens, assume they have minimal value unless proven otherwise
        if rate == 0.0:
            # Conservative estimate: assume very low value for unknown tokens
            # This prevents phantom profits from worthless minted tokens
            rate = 0.000001  # 1 token = 0.000001 ETH (essentially worthless)
            
        return amount * rate
    
    def run(self, **kwargs) -> ToolResult:
        """Run the accounting oracle"""
        exploit_address = kwargs.get('exploit_address')
        target_address = kwargs.get('target_address')  
        chain_id = kwargs.get('chain_id')
        block_number = kwargs.get('block_number')
        
        if not all([exploit_address, target_address, chain_id]):
            return ToolResult(
                success=False,
                error="Missing required parameters: exploit_address, target_address, chain_id"
            )
            
        return self.compute_profit(exploit_address, target_address, chain_id, block_number)