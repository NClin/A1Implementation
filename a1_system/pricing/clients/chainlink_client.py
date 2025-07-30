"""
Chainlink price feed client for on-chain historical pricing
Provides authoritative price data from Chainlink oracles
"""

import asyncio
from typing import Dict, Optional, Tuple
import logging
from ..cache import PriceCache


class ChainlinkClient:
    """
    Chainlink price feed client for on-chain pricing data
    
    Features:
    - Historical price data from Chainlink aggregators
    - High confidence authoritative pricing
    - On-chain verification of price feeds
    """
    
    # Chainlink aggregator ABI for price feeds
    AGGREGATOR_ABI = [
        {
            "inputs": [{"internalType": "uint80", "name": "_roundId", "type": "uint80"}],
            "name": "getRoundData",
            "outputs": [
                {"internalType": "uint80", "name": "roundId", "type": "uint80"},
                {"internalType": "int256", "name": "answer", "type": "int256"},
                {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
                {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
                {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"}
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "latestRoundData",
            "outputs": [
                {"internalType": "uint80", "name": "roundId", "type": "uint80"},
                {"internalType": "int256", "name": "answer", "type": "int256"},
                {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
                {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
                {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"}
            ],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "decimals",
            "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    
    def __init__(self, web3_client, cache: Optional[PriceCache] = None):
        self.web3_client = web3_client
        self.cache = cache
        self.logger = logging.getLogger(__name__)
        
        # Cache for feed decimals to avoid repeated calls
        self.feed_decimals: Dict[str, int] = {}
    
    async def _get_feed_decimals(self, feed_address: str, chain_id: int) -> int:
        """Get decimals for a Chainlink price feed"""
        if feed_address in self.feed_decimals:
            return self.feed_decimals[feed_address]
        
        try:
            decimals_fn = {
                "name": "decimals",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [{"type": "uint8"}]
            }
            
            decimals = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=feed_address,
                function_abi=decimals_fn,
                args=[],
                block_number=None
            )
            
            if decimals is not None:
                self.feed_decimals[feed_address] = decimals
                return decimals
            
        except Exception as e:
            self.logger.debug(f"Failed to get feed decimals for {feed_address}: {e}")
        
        return 8  # Default to 8 decimals (most common)
    
    async def get_latest_price(self, feed_address: str, chain_id: int, 
                              token_symbol: str) -> Optional[Tuple[float, float]]:
        """
        Get latest price from Chainlink feed
        
        Args:
            feed_address: Chainlink aggregator address
            chain_id: Blockchain ID
            token_symbol: Token symbol (for caching)
            
        Returns:
            Tuple of (price_usd, confidence) or None if failed
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_price(chain_id, token_symbol, None)
            if cached and cached.source == "chainlink":
                return cached.price_usd, cached.confidence
        
        try:
            latest_round_fn = {
                "name": "latestRoundData",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {"type": "uint80"},  # roundId
                    {"type": "int256"},  # answer
                    {"type": "uint256"}, # startedAt
                    {"type": "uint256"}, # updatedAt
                    {"type": "uint80"}   # answeredInRound
                ]
            }
            
            result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=feed_address,
                function_abi=latest_round_fn,
                args=[],
                block_number=None
            )
            
            if result and len(result) >= 5:
                round_id, answer, started_at, updated_at, answered_in_round = result
                
                if answer > 0:
                    # Get feed decimals
                    decimals = await self._get_feed_decimals(feed_address, chain_id)
                    price_usd = answer / (10 ** decimals)
                    
                    # Cache the result
                    if self.cache:
                        self.cache.set_price(
                            chain_id=chain_id,
                            token_symbol=token_symbol,
                            price_usd=price_usd,
                            source="chainlink",
                            confidence=0.98,  # Very high confidence for Chainlink
                            timestamp=updated_at
                        )
                    
                    return price_usd, 0.98
            
        except Exception as e:
            self.logger.debug(f"Failed to get Chainlink price for {feed_address}: {e}")
        
        return None
    
    async def get_historical_price(self, feed_address: str, chain_id: int, 
                                  block_number: int, token_symbol: str) -> Optional[Tuple[float, float]]:
        """
        Get historical price from Chainlink feed at specific block
        
        Args:
            feed_address: Chainlink aggregator address
            chain_id: Blockchain ID
            block_number: Historical block number
            token_symbol: Token symbol (for caching)
            
        Returns:
            Tuple of (price_usd, confidence) or None if failed
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_price(chain_id, token_symbol, block_number)
            if cached and cached.source == "chainlink":
                return cached.price_usd, cached.confidence
        
        try:
            # Get latest round data at the specific block
            latest_round_fn = {
                "name": "latestRoundData",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {"type": "uint80"},  # roundId
                    {"type": "int256"},  # answer
                    {"type": "uint256"}, # startedAt
                    {"type": "uint256"}, # updatedAt
                    {"type": "uint80"}   # answeredInRound
                ]
            }
            
            result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=feed_address,
                function_abi=latest_round_fn,
                args=[],
                block_number=block_number
            )
            
            if result and len(result) >= 5:
                round_id, answer, started_at, updated_at, answered_in_round = result
                
                if answer > 0:
                    # Get feed decimals
                    decimals = await self._get_feed_decimals(feed_address, chain_id)
                    price_usd = answer / (10 ** decimals)
                    
                    # Cache the result
                    if self.cache:
                        self.cache.set_price(
                            chain_id=chain_id,
                            token_symbol=token_symbol,
                            price_usd=price_usd,
                            source="chainlink",
                            confidence=0.95,  # High confidence for historical Chainlink
                            block_number=block_number,
                            timestamp=updated_at
                        )
                    
                    return price_usd, 0.95
            
        except Exception as e:
            self.logger.debug(f"Failed to get historical Chainlink price for {feed_address}: {e}")
        
        return None
    
    async def get_round_data(self, feed_address: str, chain_id: int, 
                            round_id: int) -> Optional[Dict]:
        """
        Get specific round data from Chainlink feed
        
        Args:
            feed_address: Chainlink aggregator address
            chain_id: Blockchain ID
            round_id: Round ID to query
            
        Returns:
            Round data dictionary or None if failed
        """
        try:
            round_data_fn = {
                "name": "getRoundData",
                "type": "function",
                "stateMutability": "view",
                "inputs": [{"type": "uint80"}],
                "outputs": [
                    {"type": "uint80"},  # roundId
                    {"type": "int256"},  # answer
                    {"type": "uint256"}, # startedAt
                    {"type": "uint256"}, # updatedAt
                    {"type": "uint80"}   # answeredInRound
                ]
            }
            
            result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=feed_address,
                function_abi=round_data_fn,
                args=[round_id],
                block_number=None
            )
            
            if result and len(result) >= 5:
                round_id, answer, started_at, updated_at, answered_in_round = result
                
                # Get feed decimals
                decimals = await self._get_feed_decimals(feed_address, chain_id)
                price_usd = answer / (10 ** decimals) if answer > 0 else 0
                
                return {
                    "round_id": round_id,
                    "price_usd": price_usd,
                    "started_at": started_at,
                    "updated_at": updated_at,
                    "answered_in_round": answered_in_round,
                    "decimals": decimals
                }
            
        except Exception as e:
            self.logger.debug(f"Failed to get round data for {feed_address}: {e}")
        
        return None
    
    async def find_round_by_timestamp(self, feed_address: str, chain_id: int, 
                                     target_timestamp: int, token_symbol: str) -> Optional[Tuple[float, float]]:
        """
        Find the round closest to a target timestamp
        This is a simplified implementation - production would use binary search
        
        Args:
            feed_address: Chainlink aggregator address
            chain_id: Blockchain ID
            target_timestamp: Target timestamp
            token_symbol: Token symbol
            
        Returns:
            Tuple of (price_usd, confidence) or None if failed
        """
        try:
            # Get latest round to start searching backwards
            latest_round_fn = {
                "name": "latestRoundData",
                "type": "function",
                "stateMutability": "view",
                "inputs": [],
                "outputs": [
                    {"type": "uint80"},  # roundId
                    {"type": "int256"},  # answer
                    {"type": "uint256"}, # startedAt
                    {"type": "uint256"}, # updatedAt
                    {"type": "uint80"}   # answeredInRound
                ]
            }
            
            latest_result = await self.web3_client.call_contract_function(
                chain_id=chain_id,
                contract_address=feed_address,
                function_abi=latest_round_fn,
                args=[],
                block_number=None
            )
            
            if not latest_result or len(latest_result) < 5:
                return None
            
            latest_round_id, latest_answer, latest_started_at, latest_updated_at, _ = latest_result
            
            # If target is after latest update, return latest price
            if target_timestamp >= latest_updated_at:
                decimals = await self._get_feed_decimals(feed_address, chain_id)
                price_usd = latest_answer / (10 ** decimals)
                return price_usd, 0.9
            
            # Simple approach: search backwards from latest round
            # In production, use binary search for efficiency
            current_round_id = latest_round_id
            search_limit = 100  # Limit search to avoid infinite loops
            
            for _ in range(search_limit):
                round_data = await self.get_round_data(feed_address, chain_id, current_round_id)
                
                if round_data and round_data["updated_at"] <= target_timestamp:
                    # Found round at or before target timestamp
                    return round_data["price_usd"], 0.9
                
                current_round_id -= 1
                if current_round_id <= 0:
                    break
            
            # If we couldn't find a suitable round, return None
            return None
            
        except Exception as e:
            self.logger.debug(f"Failed to find round by timestamp for {feed_address}: {e}")
            return None