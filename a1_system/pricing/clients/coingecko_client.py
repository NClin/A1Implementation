"""
CoinGecko API client for historical pricing data
Provides comprehensive historical price data aligned with block timestamps
"""

import aiohttp
import asyncio
import time
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timezone
import logging
from ..cache import PriceCache


class CoinGeckoClient:
    """
    CoinGecko API client for historical cryptocurrency pricing
    
    Features:
    - Historical prices by timestamp
    - Block-aligned pricing using timestamp estimation
    - Rate limiting and error handling
    - Comprehensive token coverage
    """
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self, api_key: Optional[str] = None, cache: Optional[PriceCache] = None):
        self.api_key = api_key
        self.cache = cache
        self.logger = logging.getLogger(__name__)
        
        # Rate limiting (free tier: 10-50 calls/minute)
        self.rate_limit_delay = 1.2 if api_key else 6.0  # Seconds between requests
        self.last_request_time = 0.0
        
        # Session for connection pooling
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            headers = {}
            if self.api_key:
                headers["x-cg-pro-api-key"] = self.api_key
            
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers=headers
            )
        return self.session
    
    async def close(self):
        """Close the HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _rate_limit(self):
        """Apply rate limiting"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()
    
    async def _make_request(self, endpoint: str, params: Dict) -> Optional[Dict]:
        """Make rate-limited API request"""
        await self._rate_limit()
        
        session = await self._get_session()
        url = f"{self.BASE_URL}/{endpoint}"
        
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    # Rate limited, wait longer
                    self.logger.warning("CoinGecko rate limit hit, waiting...")
                    await asyncio.sleep(60)
                    return await self._make_request(endpoint, params)
                else:
                    self.logger.error(f"CoinGecko API error {response.status}: {await response.text()}")
                    return None
        except Exception as e:
            self.logger.error(f"CoinGecko request failed: {e}")
            return None
    
    async def get_historical_price(self, coingecko_id: str, timestamp: int, 
                                  chain_id: int, token_symbol: str) -> Optional[Tuple[float, float]]:
        """
        Get historical price by timestamp
        
        Args:
            coingecko_id: CoinGecko token ID
            timestamp: Unix timestamp
            chain_id: Blockchain ID (for caching)
            token_symbol: Token symbol (for caching)
            
        Returns:
            Tuple of (price_usd, confidence) or None if failed
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_price(chain_id, token_symbol, None)  # Use None for timestamp-based
            if cached and abs(cached.timestamp - timestamp) < 3600:  # Within 1 hour
                return cached.price_usd, cached.confidence
        
        # Format date for CoinGecko API (DD-MM-YYYY format)
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
        date_str = dt.strftime("%d-%m-%Y")
        
        params = {
            "date": date_str,
            "localization": "false"
        }
        
        data = await self._make_request(f"coins/{coingecko_id}/history", params)
        
        if data and "market_data" in data and "current_price" in data["market_data"]:
            price_usd = data["market_data"]["current_price"].get("usd", 0.0)
            
            if price_usd > 0:
                # Cache the result
                if self.cache:
                    self.cache.set_price(
                        chain_id=chain_id,
                        token_symbol=token_symbol,
                        price_usd=price_usd,
                        source="coingecko",
                        confidence=0.9,  # High confidence for CoinGecko
                        timestamp=timestamp
                    )
                
                return price_usd, 0.9
        
        return None
    
    async def get_historical_price_range(self, coingecko_id: str, from_timestamp: int, 
                                        to_timestamp: int) -> List[Tuple[int, float]]:
        """
        Get price data over a time range
        
        Args:
            coingecko_id: CoinGecko token ID  
            from_timestamp: Start timestamp
            to_timestamp: End timestamp
            
        Returns:
            List of (timestamp, price_usd) tuples
        """
        params = {
            "vs_currency": "usd",
            "from": from_timestamp,
            "to": to_timestamp,
            "interval": "daily"
        }
        
        data = await self._make_request(f"coins/{coingecko_id}/market_chart/range", params)
        
        if data and "prices" in data:
            # CoinGecko returns [[timestamp_ms, price], ...]
            return [(int(ts / 1000), price) for ts, price in data["prices"]]
        
        return []
    
    async def get_current_price(self, coingecko_id: str, chain_id: int, 
                               token_symbol: str) -> Optional[Tuple[float, float]]:
        """
        Get current price for a token
        
        Args:
            coingecko_id: CoinGecko token ID
            chain_id: Blockchain ID
            token_symbol: Token symbol
            
        Returns:
            Tuple of (price_usd, confidence) or None if failed
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_price(chain_id, token_symbol, None)
            if cached and time.time() - cached.cached_at < 300:  # 5 minutes
                return cached.price_usd, cached.confidence
        
        params = {
            "ids": coingecko_id,
            "vs_currencies": "usd",
            "include_24hr_change": "false",
            "precision": "full"
        }
        
        data = await self._make_request("simple/price", params)
        
        if data and coingecko_id in data and "usd" in data[coingecko_id]:
            price_usd = data[coingecko_id]["usd"]
            
            # Cache the result
            if self.cache:
                self.cache.set_price(
                    chain_id=chain_id,
                    token_symbol=token_symbol,
                    price_usd=price_usd,
                    source="coingecko",
                    confidence=0.95,  # Very high confidence for current price
                    timestamp=int(time.time())
                )
            
            return price_usd, 0.95
        
        return None
    
    async def get_supported_tokens(self) -> List[Dict]:
        """Get list of all supported tokens"""
        data = await self._make_request("coins/list", {})
        return data if data else []
    
    def get_block_timestamp_estimate(self, chain_id: int, block_number: int) -> int:
        """
        Estimate timestamp for a block number
        This is a simplified implementation - in production, use actual block data
        """
        # Approximate block times (seconds)
        BLOCK_TIMES = {
            1: 12,   # Ethereum ~12 seconds
            56: 3    # BSC ~3 seconds
        }
        
        # Approximate current block numbers (update these periodically)
        CURRENT_BLOCKS = {
            1: 21000000,   # Ethereum mainnet
            56: 45000000   # BSC mainnet
        }
        
        block_time = BLOCK_TIMES.get(chain_id, 12)
        current_block = CURRENT_BLOCKS.get(chain_id, 21000000)
        current_time = int(time.time())
        
        # Estimate timestamp
        blocks_ago = current_block - block_number
        estimated_timestamp = current_time - (blocks_ago * block_time)
        
        return max(estimated_timestamp, 1500000000)  # Don't return timestamps before 2017
    
    async def get_price_at_block(self, coingecko_id: str, chain_id: int, 
                                block_number: int, token_symbol: str) -> Optional[Tuple[float, float]]:
        """
        Get price at a specific block number
        
        Args:
            coingecko_id: CoinGecko token ID
            chain_id: Blockchain ID
            block_number: Block number
            token_symbol: Token symbol
            
        Returns:
            Tuple of (price_usd, confidence) or None if failed
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_price(chain_id, token_symbol, block_number)
            if cached:
                return cached.price_usd, cached.confidence
        
        # Estimate timestamp for the block
        estimated_timestamp = self.get_block_timestamp_estimate(chain_id, block_number)
        
        result = await self.get_historical_price(coingecko_id, estimated_timestamp, chain_id, token_symbol)
        
        if result and self.cache:
            # Cache with block number
            price_usd, confidence = result
            self.cache.set_price(
                chain_id=chain_id,
                token_symbol=token_symbol,
                price_usd=price_usd,
                source="coingecko",
                confidence=confidence * 0.8,  # Reduce confidence for block estimation
                block_number=block_number,
                timestamp=estimated_timestamp
            )
        
        return result