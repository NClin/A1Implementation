"""
DEX client for on-chain historical pricing
Provides real DEX quotes and routing for token pricing
"""

import asyncio
from typing import Dict, Optional, Tuple, List
import logging
from ..cache import PriceCache


class DEXClient:
    """
    DEX client for on-chain token pricing
    
    Features:
    - Historical DEX quotes at specific blocks
    - Multi-DEX routing for best prices
    - Uniswap V2/V3 and PancakeSwap support
    """
    
    # Uniswap V2 Router ABI
    UNISWAP_V2_ROUTER_ABI = [
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"}
            ],
            "name": "getAmountsOut",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    
    # Uniswap V2 Pair ABI
    UNISWAP_V2_PAIR_ABI = [
        {
            "inputs": [],
            "name": "getReserves",
            "outputs": [
                {"internalType": "uint112", "name": "_reserve0", "type": "uint112"},
                {"internalType": "uint112", "name": "_reserve1", "type": "uint112"},
                {"internalType": "uint32", "name": "_blockTimestampLast", "type": "uint32"}
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "token0",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "token1",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    
    def __init__(self, web3_client, cache: Optional[PriceCache] = None):
        self.web3_client = web3_client
        self.cache = cache
        self.logger = logging.getLogger(__name__)
        
        # DEX router addresses
        self.routers = {
            1: {  # Ethereum
                "uniswap_v2": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
                "sushiswap": "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F"
            },
            56: {  # BSC
                "pancakeswap_v2": "0x10ED43C718714eb63d5aA57B78B54704E256024E"
            }
        }
    
    async def get_dex_quote(self, router_address: str, chain_id: int, 
                           token_in: str, token_out: str, amount_in: int,
                           block_number: Optional[int] = None) -> Optional[int]:
        """
        Get quote from DEX router
        
        Args:
            router_address: DEX router contract address
            chain_id: Blockchain ID
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount (in token units)
            block_number: Historical block number
            
        Returns:
            Output amount or None if failed
        """
        try:
            get_amounts_out_fn = {
                "name": "getAmountsOut",
                "type": "function",
                "stateMutability": "view",
                "inputs": [
                    {"type": "uint256"},
                    {"type": "address[]"}
                ],
                "outputs": [{"type": "uint256[]"}]
            }
            
            path = [token_in, token_out]
            
            result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=router_address,
                function_abi=get_amounts_out_fn,
                args=[amount_in, path],
                block_number=block_number
            )
            
            if result and len(result) >= 2:
                return result[-1]  # Last element is the output amount
            
        except Exception as e:
            self.logger.debug(f"DEX quote failed for {router_address}: {e}")
        
        return None
    
    async def get_token_price_via_dex(self, token_address: str, chain_id: int, 
                                     token_symbol: str, block_number: Optional[int] = None) -> Optional[Tuple[float, float]]:
        """
        Get token price using DEX routing
        
        Args:
            token_address: Token to price
            chain_id: Blockchain ID
            token_symbol: Token symbol (for caching)
            block_number: Historical block number
            
        Returns:
            Tuple of (price_usd, confidence) or None if failed
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_price(chain_id, token_symbol, block_number)
            if cached and cached.source == "dex":
                return cached.price_usd, cached.confidence
        
        # Get base currency and stablecoin addresses
        base_currency = self._get_base_currency(chain_id)
        stablecoin_address = self._get_stablecoin_address(chain_id)
        
        if not base_currency or not stablecoin_address:
            return None
        
        # Try to get price via base currency (ETH/BNB)
        price_in_base = await self._get_price_in_base_currency(
            token_address, base_currency, chain_id, block_number
        )
        
        if price_in_base:
            # Convert base currency to USD
            base_usd_price = await self._get_base_currency_usd_price(
                chain_id, block_number
            )
            
            if base_usd_price:
                price_usd = price_in_base * base_usd_price
                
                # Cache the result
                if self.cache:
                    self.cache.set_price(
                        chain_id=chain_id,
                        token_symbol=token_symbol,
                        price_usd=price_usd,
                        source="dex",
                        confidence=0.8,  # Medium confidence for DEX pricing
                        block_number=block_number
                    )
                
                return price_usd, 0.8
        
        return None
    
    async def _get_price_in_base_currency(self, token_address: str, base_currency: str, 
                                         chain_id: int, block_number: Optional[int] = None) -> Optional[float]:
        """Get token price in base currency (ETH/BNB)"""
        base_currency_address = self._get_base_currency_address(chain_id)
        if not base_currency_address:
            return None
        
        # Try each DEX router
        routers = self.routers.get(chain_id, {})
        
        for router_name, router_address in routers.items():
            try:
                # Use 1 token as input (scaled by decimals)
                input_amount = 10**18  # Assume 18 decimals
                
                output_amount = await self.get_dex_quote(
                    router_address=router_address,
                    chain_id=chain_id,
                    token_in=token_address,
                    token_out=base_currency_address,
                    amount_in=input_amount,
                    block_number=block_number
                )
                
                if output_amount and output_amount > 0:
                    # Calculate price (how much base currency for 1 token)
                    price_in_base = output_amount / input_amount
                    self.logger.debug(f"Got {token_address} price via {router_name}: {price_in_base} {base_currency}")
                    return price_in_base
                    
            except Exception as e:
                self.logger.debug(f"Failed to get price via {router_name}: {e}")
                continue
        
        return None
    
    async def _get_base_currency_usd_price(self, chain_id: int, block_number: Optional[int] = None) -> Optional[float]:
        """Get base currency (ETH/BNB) price in USD"""
        base_currency = self._get_base_currency(chain_id)
        stablecoin_address = self._get_stablecoin_address(chain_id)
        base_currency_address = self._get_base_currency_address(chain_id)
        
        if not all([base_currency, stablecoin_address, base_currency_address]):
            return None
        
        # Try each DEX router
        routers = self.routers.get(chain_id, {})
        
        for router_name, router_address in routers.items():
            try:
                # Use 1 base currency as input
                input_amount = 10**18  # 1 ETH/BNB
                
                output_amount = await self.get_dex_quote(
                    router_address=router_address,
                    chain_id=chain_id,
                    token_in=base_currency_address,
                    token_out=stablecoin_address,
                    amount_in=input_amount,
                    block_number=block_number
                )
                
                if output_amount and output_amount > 0:
                    # Adjust for stablecoin decimals
                    stablecoin_decimals = 6 if chain_id == 1 else 18  # USDC vs USDT
                    usd_price = output_amount / (10**stablecoin_decimals)
                    self.logger.debug(f"Got {base_currency} USD price via {router_name}: ${usd_price}")
                    return usd_price
                    
            except Exception as e:
                self.logger.debug(f"Failed to get {base_currency} USD price via {router_name}: {e}")
                continue
        
        return None
    
    def _get_base_currency(self, chain_id: int) -> Optional[str]:
        """Get base currency symbol for chain"""
        if chain_id == 1:
            return "ETH"
        elif chain_id == 56:
            return "BNB"
        return None
    
    def _get_base_currency_address(self, chain_id: int) -> Optional[str]:
        """Get wrapped base currency address"""
        if chain_id == 1:
            return "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"  # WETH
        elif chain_id == 56:
            return "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"  # WBNB
        return None
    
    def _get_stablecoin_address(self, chain_id: int) -> Optional[str]:
        """Get stablecoin address for USD pricing"""
        if chain_id == 1:
            return "0xA0b86a33E6441d00C9dab2B1DC7Be85c39Ad"  # USDC
        elif chain_id == 56:
            return "0x55d398326f99059fF775485246999027B3197955"  # USDT
        return None
    
    async def get_pair_reserves(self, pair_address: str, chain_id: int, 
                               block_number: Optional[int] = None) -> Optional[Tuple[int, int, str, str]]:
        """
        Get reserves for a Uniswap V2 style pair
        
        Args:
            pair_address: Pair contract address
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            Tuple of (reserve0, reserve1, token0, token1) or None if failed
        """
        try:
            # Get reserves
            reserves_fn = {
                "name": "getReserves",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {"type": "uint112"},  # reserve0
                    {"type": "uint112"},  # reserve1
                    {"type": "uint32"}    # blockTimestampLast
                ]
            }
            
            reserves_result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=pair_address,
                function_abi=reserves_fn,
                args=[],
                block_number=block_number
            )
            
            if not reserves_result or len(reserves_result) < 2:
                return None
            
            reserve0, reserve1 = reserves_result[0], reserves_result[1]
            
            # Get token addresses
            token0_fn = {
                "name": "token0",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "address"}]
            }
            
            token1_fn = {
                "name": "token1",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "address"}]
            }
            
            token0_result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=pair_address,
                function_abi=token0_fn,
                args=[],
                block_number=block_number
            )
            
            token1_result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=pair_address,
                function_abi=token1_fn,
                args=[],
                block_number=block_number
            )
            
            if token0_result and token1_result:
                return reserve0, reserve1, token0_result, token1_result
            
        except Exception as e:
            self.logger.debug(f"Failed to get pair reserves for {pair_address}: {e}")
        
        return None
    
    async def calculate_pair_price(self, pair_address: str, chain_id: int, 
                                  target_token: str, block_number: Optional[int] = None) -> Optional[float]:
        """
        Calculate token price from pair reserves
        
        Args:
            pair_address: Pair contract address
            chain_id: Blockchain ID
            target_token: Token to price
            block_number: Historical block number
            
        Returns:
            Price in terms of the other token, or None if failed
        """
        reserves_data = await self.get_pair_reserves(pair_address, chain_id, block_number)
        
        if not reserves_data:
            return None
        
        reserve0, reserve1, token0, token1 = reserves_data
        
        if reserve0 == 0 or reserve1 == 0:
            return None
        
        # Determine which token is the target
        if target_token.lower() == token0.lower():
            # Target is token0, price in terms of token1
            price = reserve1 / reserve0
        elif target_token.lower() == token1.lower():
            # Target is token1, price in terms of token0
            price = reserve0 / reserve1
        else:
            # Target token not in this pair
            return None
        
        return price