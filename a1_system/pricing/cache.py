"""
Price caching system to avoid redundant API calls
Provides efficient storage and retrieval of historical price data
"""

import time
import json
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import logging


@dataclass
class PriceCacheEntry:
    """Cached price entry with metadata"""
    price_usd: float
    timestamp: int
    block_number: Optional[int]
    chain_id: int
    token_symbol: str
    source: str  # "coingecko", "chainlink", "dex", "fallback"
    confidence: float  # 0.0 to 1.0
    cached_at: float  # Unix timestamp when cached


class PriceCache:
    """
    Efficient caching system for historical price data
    Reduces API calls during validation runs
    """
    
    def __init__(self, cache_dir: str = "price_cache", max_age_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.max_age_seconds = max_age_hours * 3600
        self.logger = logging.getLogger(__name__)
        
        # In-memory cache for recent lookups
        self.memory_cache: Dict[str, PriceCacheEntry] = {}
        
    def _get_cache_key(self, chain_id: int, token_symbol: str, block_number: Optional[int] = None) -> str:
        """Generate cache key for price lookup"""
        if block_number:
            return f"{chain_id}_{token_symbol}_{block_number}"
        else:
            return f"{chain_id}_{token_symbol}_latest"
    
    def _get_cache_file(self, chain_id: int) -> Path:
        """Get cache file path for chain"""
        return self.cache_dir / f"prices_chain_{chain_id}.json"
    
    def _load_disk_cache(self, chain_id: int) -> Dict[str, dict]:
        """Load cache from disk"""
        cache_file = self._get_cache_file(chain_id)
        if not cache_file.exists():
            return {}
        
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load price cache: {e}")
            return {}
    
    def _save_disk_cache(self, chain_id: int, cache_data: Dict[str, dict]):
        """Save cache to disk"""
        cache_file = self._get_cache_file(chain_id)
        try:
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save price cache: {e}")
    
    def get_price(self, chain_id: int, token_symbol: str, block_number: Optional[int] = None) -> Optional[PriceCacheEntry]:
        """
        Get cached price entry
        
        Args:
            chain_id: Blockchain ID
            token_symbol: Token symbol (e.g., "ETH", "USDC")
            block_number: Historical block number (None for latest)
            
        Returns:
            Cached price entry if found and valid, None otherwise
        """
        cache_key = self._get_cache_key(chain_id, token_symbol, block_number)
        
        # Check memory cache first
        if cache_key in self.memory_cache:
            entry = self.memory_cache[cache_key]
            if time.time() - entry.cached_at < self.max_age_seconds:
                return entry
            else:
                # Expired, remove from memory
                del self.memory_cache[cache_key]
        
        # Check disk cache
        disk_cache = self._load_disk_cache(chain_id)
        if cache_key in disk_cache:
            entry_data = disk_cache[cache_key]
            entry = PriceCacheEntry(**entry_data)
            
            # Check if entry is still valid
            if time.time() - entry.cached_at < self.max_age_seconds:
                # Add to memory cache for faster access
                self.memory_cache[cache_key] = entry
                return entry
            else:
                # Expired, remove from disk cache
                del disk_cache[cache_key]
                self._save_disk_cache(chain_id, disk_cache)
        
        return None
    
    def set_price(self, chain_id: int, token_symbol: str, price_usd: float, 
                  source: str, confidence: float = 1.0, block_number: Optional[int] = None,
                  timestamp: Optional[int] = None) -> PriceCacheEntry:
        """
        Cache a price entry
        
        Args:
            chain_id: Blockchain ID
            token_symbol: Token symbol
            price_usd: Price in USD
            source: Data source identifier
            confidence: Confidence level (0.0 to 1.0)
            block_number: Historical block number
            timestamp: Price timestamp (defaults to now)
            
        Returns:
            Created cache entry
        """
        cache_key = self._get_cache_key(chain_id, token_symbol, block_number)
        
        entry = PriceCacheEntry(
            price_usd=price_usd,
            timestamp=timestamp or int(time.time()),
            block_number=block_number,
            chain_id=chain_id,
            token_symbol=token_symbol,
            source=source,
            confidence=confidence,
            cached_at=time.time()
        )
        
        # Add to memory cache
        self.memory_cache[cache_key] = entry
        
        # Add to disk cache
        disk_cache = self._load_disk_cache(chain_id)
        disk_cache[cache_key] = asdict(entry)
        self._save_disk_cache(chain_id, disk_cache)
        
        return entry
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        stats = {
            "memory_entries": len(self.memory_cache),
            "disk_files": len(list(self.cache_dir.glob("*.json")))
        }
        
        # Count total disk entries
        total_disk_entries = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    total_disk_entries += len(data)
            except:
                continue
        
        stats["disk_entries"] = total_disk_entries
        return stats
    
    def clear_cache(self, chain_id: Optional[int] = None):
        """Clear cache entries"""
        if chain_id:
            # Clear specific chain
            cache_file = self._get_cache_file(chain_id)
            if cache_file.exists():
                cache_file.unlink()
            
            # Clear from memory cache
            keys_to_remove = [k for k in self.memory_cache.keys() if k.startswith(f"{chain_id}_")]
            for key in keys_to_remove:
                del self.memory_cache[key]
        else:
            # Clear all
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
            self.memory_cache.clear()
    
    def get_block_timestamp_estimate(self, chain_id: int, block_number: int) -> Optional[int]:
        """
        Get estimated timestamp for a block number
        This is a simplified implementation - in production, use actual block timestamp
        """
        # Approximate block times (seconds)
        BLOCK_TIMES = {
            1: 12,   # Ethereum ~12 seconds
            56: 3    # BSC ~3 seconds  
        }
        
        # Approximate current block numbers (as of implementation)
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
        
        return max(estimated_timestamp, 0)  # Don't return negative timestamps