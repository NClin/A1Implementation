"""
Unified pricing oracle with multiple data sources and historical support
Provides accurate, consistent pricing across all A1 tools
"""

import asyncio
import time
from typing import Dict, Optional, Tuple, List, Any
from dataclasses import dataclass
import logging

from .tokens import TokenRegistry, TokenInfo
from .cache import PriceCache, PriceCacheEntry
from .clients.coingecko_client import CoinGeckoClient
from .clients.chainlink_client import ChainlinkClient
from .clients.dex_client import DEXClient


@dataclass
class PriceResult:
    """Result of price lookup with metadata"""
    price_usd: float
    confidence: float
    source: str
    timestamp: int
    block_number: Optional[int] = None
    token_symbol: str = ""
    chain_id: int = 1


class PricingOracle:
    """
    Unified pricing oracle that coordinates multiple data sources
    
    Data Source Priority:
    1. Chainlink feeds (highest confidence, limited coverage)
    2. DEX quotes (accurate for specific blocks, good coverage)
    3. CoinGecko API (broad coverage, block-aligned)
    4. Fallback rates (last resort)
    
    Features:
    - Historical pricing at specific block numbers
    - Intelligent fallback between sources
    - Comprehensive caching to reduce API calls
    - Consistent pricing across all tools
    """
    
    def __init__(self, config, web3_client):
        self.config = config
        self.web3_client = web3_client
        self.logger = logging.getLogger(__name__)
        
        # Initialize cache
        self.cache = PriceCache()
        
        # Initialize API clients
        self.coingecko_client = CoinGeckoClient(
            api_key=getattr(config, 'coingecko_api_key', None),
            cache=self.cache
        )
        
        self.chainlink_client = ChainlinkClient(
            web3_client=web3_client,
            cache=self.cache
        )
        
        self.dex_client = DEXClient(
            web3_client=web3_client,
            cache=self.cache
        )
        
        # Fallback rates (last resort)
        self.fallback_rates = {
            1: {  # Ethereum
                "ETH": 3200.0,
                "WETH": 3200.0,
                "USDC": 1.0,
                "USDT": 1.0,
                "DAI": 1.0,
                "WBTC": 65000.0,
                "UNI": 10.0,
                "COMP": 50.0,
                "stETH": 3200.0,
                # VERITE dataset tokens
                "UERII": 0.001  # Small value for testing token
            },
            56: {  # BSC
                "BNB": 650.0,
                "WBNB": 650.0,
                "USDT": 1.0,
                "BUSD": 1.0,
                "CAKE": 2.5
            }
        }
    
    async def get_token_price(self, token_address: str, chain_id: int, 
                             block_number: Optional[int] = None) -> Optional[PriceResult]:
        """
        Get token price with fallback sources
        
        Args:
            token_address: Token contract address
            chain_id: Blockchain ID
            block_number: Historical block number (None for latest)
            
        Returns:
            PriceResult with price and metadata, or None if all sources fail
        """
        # Get token info
        token_info = TokenRegistry.get_token_by_address(chain_id, token_address)
        if not token_info:
            # Try to handle native tokens
            if TokenRegistry.is_native_token(chain_id, token_address):
                token_info = TokenRegistry.get_native_token_info(chain_id)
            else:
                self.logger.warning(f"Unknown token {token_address} on chain {chain_id}")
                return None
        
        # Check cache first
        cached_price = self.cache.get_price(chain_id, token_info.symbol, block_number)
        if cached_price:
            return PriceResult(
                price_usd=cached_price.price_usd,
                confidence=cached_price.confidence,
                source=cached_price.source,
                timestamp=cached_price.timestamp,
                block_number=cached_price.block_number,
                token_symbol=token_info.symbol,
                chain_id=chain_id
            )
        
        # Try data sources in priority order
        price_result = None
        
        # 1. Try Chainlink (highest confidence)
        if token_info.chainlink_feed:
            price_result = await self._get_chainlink_price(
                token_info, chain_id, block_number
            )
            if price_result:
                self.logger.debug(f"Got {token_info.symbol} price from Chainlink: ${price_result.price_usd}")
                return price_result
        
        # 2. Try DEX quotes (accurate for specific blocks)
        if block_number:
            price_result = await self._get_dex_price(
                token_info, chain_id, block_number
            )
            if price_result:
                self.logger.debug(f"Got {token_info.symbol} price from DEX: ${price_result.price_usd}")
                return price_result
        
        # 3. Try CoinGecko (broad coverage)
        if token_info.coingecko_id:
            price_result = await self._get_coingecko_price(
                token_info, chain_id, block_number
            )
            if price_result:
                self.logger.debug(f"Got {token_info.symbol} price from CoinGecko: ${price_result.price_usd}")
                return price_result
        
        # 4. Fallback to hardcoded rates
        price_result = self._get_fallback_price(token_info, chain_id, block_number)
        if price_result:
            self.logger.debug(f"Got {token_info.symbol} price from fallback: ${price_result.price_usd}")
            return price_result
        
        self.logger.warning(f"Failed to get price for {token_info.symbol} on chain {chain_id}")
        return None
    
    async def _get_chainlink_price(self, token_info: TokenInfo, chain_id: int, 
                                  block_number: Optional[int]) -> Optional[PriceResult]:
        """Get price from Chainlink feed"""
        if not token_info.chainlink_feed:
            return None
        
        try:
            if block_number:
                result = await self.chainlink_client.get_historical_price(
                    token_info.chainlink_feed, chain_id, block_number, token_info.symbol
                )
            else:
                result = await self.chainlink_client.get_latest_price(
                    token_info.chainlink_feed, chain_id, token_info.symbol
                )
            
            if result:
                price_usd, confidence = result
                return PriceResult(
                    price_usd=price_usd,
                    confidence=confidence,
                    source="chainlink",
                    timestamp=int(time.time()),
                    block_number=block_number,
                    token_symbol=token_info.symbol,
                    chain_id=chain_id
                )
        except Exception as e:
            self.logger.debug(f"Chainlink price failed for {token_info.symbol}: {e}")
        
        return None
    
    async def _get_dex_price(self, token_info: TokenInfo, chain_id: int, 
                            block_number: int) -> Optional[PriceResult]:
        """Get price from DEX"""
        try:
            result = await self.dex_client.get_token_price_via_dex(
                token_info.address, chain_id, token_info.symbol, block_number
            )
            
            if result:
                price_usd, confidence = result
                return PriceResult(
                    price_usd=price_usd,
                    confidence=confidence,
                    source="dex",
                    timestamp=int(time.time()),
                    block_number=block_number,
                    token_symbol=token_info.symbol,
                    chain_id=chain_id
                )
        except Exception as e:
            self.logger.debug(f"DEX price failed for {token_info.symbol}: {e}")
        
        return None
    
    async def _get_coingecko_price(self, token_info: TokenInfo, chain_id: int, 
                                  block_number: Optional[int]) -> Optional[PriceResult]:
        """Get price from CoinGecko"""
        if not token_info.coingecko_id:
            return None
        
        try:
            if block_number:
                result = await self.coingecko_client.get_price_at_block(
                    token_info.coingecko_id, chain_id, block_number, token_info.symbol
                )
            else:
                result = await self.coingecko_client.get_current_price(
                    token_info.coingecko_id, chain_id, token_info.symbol
                )
            
            if result:
                price_usd, confidence = result
                return PriceResult(
                    price_usd=price_usd,
                    confidence=confidence,
                    source="coingecko",
                    timestamp=int(time.time()),
                    block_number=block_number,
                    token_symbol=token_info.symbol,
                    chain_id=chain_id
                )
        except Exception as e:
            self.logger.debug(f"CoinGecko price failed for {token_info.symbol}: {e}")
        
        return None
    
    def _get_fallback_price(self, token_info: TokenInfo, chain_id: int, 
                           block_number: Optional[int]) -> Optional[PriceResult]:
        """Get fallback price from hardcoded rates"""
        chain_rates = self.fallback_rates.get(chain_id, {})
        price_usd = chain_rates.get(token_info.symbol)
        
        if price_usd:
            # Cache the fallback price
            self.cache.set_price(
                chain_id=chain_id,
                token_symbol=token_info.symbol,
                price_usd=price_usd,
                source="fallback",
                confidence=0.3,  # Low confidence for fallback
                block_number=block_number
            )
            
            return PriceResult(
                price_usd=price_usd,
                confidence=0.3,
                source="fallback",
                timestamp=int(time.time()),
                block_number=block_number,
                token_symbol=token_info.symbol,
                chain_id=chain_id
            )
        
        return None
    
    async def get_token_price_by_symbol(self, token_symbol: str, chain_id: int, 
                                       block_number: Optional[int] = None) -> Optional[PriceResult]:
        """
        Get token price by symbol (convenience method)
        
        Args:
            token_symbol: Token symbol (e.g., "ETH", "USDC")
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            PriceResult or None if failed
        """
        token_info = TokenRegistry.get_token_info(chain_id, token_symbol)
        if not token_info:
            return None
        
        return await self.get_token_price(token_info.address, chain_id, block_number)
    
    async def convert_token_to_usd(self, token_address: str, amount: float, 
                                  chain_id: int, block_number: Optional[int] = None) -> Optional[float]:
        """
        Convert token amount to USD value
        
        Args:
            token_address: Token contract address
            amount: Token amount (in token units, not wei)
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            USD value or None if price unavailable
        """
        price_result = await self.get_token_price(token_address, chain_id, block_number)
        if price_result:
            return amount * price_result.price_usd
        return None
    
    async def convert_tokens_to_usd(self, token_amounts: Dict[str, float], 
                                   chain_id: int, block_number: Optional[int] = None) -> Dict[str, float]:
        """
        Convert multiple token amounts to USD
        
        Args:
            token_amounts: Dict of token_address -> amount
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            Dict of token_address -> usd_value
        """
        results = {}
        
        # Use asyncio.gather for concurrent price fetching
        tasks = []
        addresses = []
        
        for token_address, amount in token_amounts.items():
            tasks.append(self.convert_token_to_usd(token_address, amount, chain_id, block_number))
            addresses.append(token_address)
        
        usd_values = await asyncio.gather(*tasks, return_exceptions=True)
        
        for address, usd_value in zip(addresses, usd_values):
            if isinstance(usd_value, Exception):
                self.logger.warning(f"Failed to convert {address} to USD: {usd_value}")
                results[address] = 0.0
            else:
                results[address] = usd_value or 0.0
        
        return results
    
    async def get_base_currency_price(self, chain_id: int, 
                                     block_number: Optional[int] = None) -> Optional[PriceResult]:
        """
        Get base currency (ETH/BNB) price
        
        Args:
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            PriceResult for base currency
        """
        base_currency = TokenRegistry.get_base_currency(chain_id)
        return await self.get_token_price_by_symbol(base_currency, chain_id, block_number)
    
    async def normalize_to_base_currency(self, token_address: str, amount: float, 
                                        chain_id: int, block_number: Optional[int] = None) -> Optional[float]:
        """
        Convert token amount to base currency (ETH/BNB)
        
        Args:
            token_address: Token contract address
            amount: Token amount
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            Amount in base currency or None if failed
        """
        # Get token USD price
        token_usd_value = await self.convert_token_to_usd(token_address, amount, chain_id, block_number)
        if not token_usd_value:
            return None
        
        # Get base currency USD price
        base_currency_price = await self.get_base_currency_price(chain_id, block_number)
        if not base_currency_price:
            return None
        
        # Convert USD to base currency
        return token_usd_value / base_currency_price.price_usd
    
    async def get_multiple_token_prices(self, token_addresses: List[str], 
                                       chain_id: int, block_number: Optional[int] = None) -> Dict[str, PriceResult]:
        """
        Get prices for multiple tokens concurrently
        
        Args:
            token_addresses: List of token addresses
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            Dict of token_address -> PriceResult
        """
        tasks = []
        for address in token_addresses:
            tasks.append(self.get_token_price(address, chain_id, block_number))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        price_results = {}
        for address, result in zip(token_addresses, results):
            if isinstance(result, Exception):
                self.logger.warning(f"Failed to get price for {address}: {result}")
            elif result:
                price_results[address] = result
        
        return price_results
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get pricing cache statistics"""
        return {
            "cache_stats": self.cache.get_cache_stats(),
            "fallback_rates": self.fallback_rates,
            "supported_chains": list(self.fallback_rates.keys())
        }
    
    async def close(self):
        """Close all API clients"""
        await self.coingecko_client.close()
        # Note: Other clients don't need explicit closing
    
    def clear_cache(self, chain_id: Optional[int] = None):
        """Clear pricing cache"""
        self.cache.clear_cache(chain_id)
    
    async def warmup_cache(self, chain_id: int, block_number: Optional[int] = None):
        """
        Warm up cache with common token prices
        
        Args:
            chain_id: Blockchain ID
            block_number: Historical block number
        """
        # Get all tokens for the chain
        all_tokens = TokenRegistry.get_all_tokens(chain_id)
        
        self.logger.info(f"Warming up price cache for {len(all_tokens)} tokens on chain {chain_id}")
        
        # Batch fetch prices
        token_addresses = [token.address for token in all_tokens.values()]
        await self.get_multiple_token_prices(token_addresses, chain_id, block_number)
        
        self.logger.info(f"Price cache warmed up for chain {chain_id}")
    
    async def validate_pricing_accuracy(self, chain_id: int, 
                                       block_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Validate pricing accuracy by comparing sources
        
        Args:
            chain_id: Blockchain ID
            block_number: Historical block number
            
        Returns:
            Validation report
        """
        report = {
            "chain_id": chain_id,
            "block_number": block_number,
            "timestamp": int(time.time()),
            "source_comparison": {},
            "accuracy_metrics": {}
        }
        
        # Test common tokens
        test_tokens = ["ETH", "USDC", "USDT"] if chain_id == 1 else ["BNB", "USDT", "BUSD"]
        
        for token_symbol in test_tokens:
            token_info = TokenRegistry.get_token_info(chain_id, token_symbol)
            if not token_info:
                continue
            
            # Get prices from different sources
            prices = {}
            
            # Chainlink
            if token_info.chainlink_feed:
                chainlink_result = await self._get_chainlink_price(token_info, chain_id, block_number)
                if chainlink_result:
                    prices["chainlink"] = chainlink_result.price_usd
            
            # CoinGecko
            if token_info.coingecko_id:
                coingecko_result = await self._get_coingecko_price(token_info, chain_id, block_number)
                if coingecko_result:
                    prices["coingecko"] = coingecko_result.price_usd
            
            # DEX
            if block_number:
                dex_result = await self._get_dex_price(token_info, chain_id, block_number)
                if dex_result:
                    prices["dex"] = dex_result.price_usd
            
            # Fallback
            fallback_result = self._get_fallback_price(token_info, chain_id, block_number)
            if fallback_result:
                prices["fallback"] = fallback_result.price_usd
            
            if len(prices) > 1:
                # Calculate variance
                price_values = list(prices.values())
                avg_price = sum(price_values) / len(price_values)
                variance = sum((p - avg_price) ** 2 for p in price_values) / len(price_values)
                
                report["source_comparison"][token_symbol] = {
                    "prices": prices,
                    "average": avg_price,
                    "variance": variance,
                    "max_deviation": max(abs(p - avg_price) / avg_price for p in price_values) * 100
                }
        
        return report