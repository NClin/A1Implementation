"""
Centralized token registry with consistent addresses and metadata
Eliminates hardcoded token addresses scattered across tools
"""

from typing import Dict, Optional, List
from dataclasses import dataclass


@dataclass
class TokenInfo:
    """Token metadata and configuration"""
    address: str
    symbol: str
    decimals: int
    name: str
    is_stablecoin: bool = False
    is_wrapped_native: bool = False
    coingecko_id: Optional[str] = None
    chainlink_feed: Optional[str] = None


class TokenRegistry:
    """
    Centralized registry for all token addresses and metadata
    Provides consistent token information across all pricing tools
    """
    
    # Token definitions by chain ID
    TOKENS = {
        1: {  # Ethereum Mainnet
            "ETH": TokenInfo(
                address="0x0000000000000000000000000000000000000000",
                symbol="ETH",
                decimals=18,
                name="Ethereum",
                is_wrapped_native=False,
                coingecko_id="ethereum",
                chainlink_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"  # ETH/USD
            ),
            "WETH": TokenInfo(
                address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                symbol="WETH",
                decimals=18,
                name="Wrapped Ethereum",
                is_wrapped_native=True,
                coingecko_id="ethereum",
                chainlink_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"  # ETH/USD
            ),
            "USDC": TokenInfo(
                address="0xA0b86a33E6441d00C9dab2B1DC7Be85c39Ad",
                symbol="USDC", 
                decimals=6,
                name="USD Coin",
                is_stablecoin=True,
                coingecko_id="usd-coin",
                chainlink_feed="0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6"  # USDC/USD
            ),
            "USDT": TokenInfo(
                address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
                symbol="USDT",
                decimals=6,
                name="Tether USD",
                is_stablecoin=True,
                coingecko_id="tether",
                chainlink_feed="0x3E7d1eAB13ad0104d2750B8863b489D65364e32D"  # USDT/USD
            ),
            "DAI": TokenInfo(
                address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
                symbol="DAI",
                decimals=18,
                name="Dai Stablecoin",
                is_stablecoin=True,
                coingecko_id="dai",
                chainlink_feed="0xAed0c38402d20D9df45C7C74C061f3f8a1e9e8D1"  # DAI/USD
            ),
            "WBTC": TokenInfo(
                address="0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
                symbol="WBTC",
                decimals=8,
                name="Wrapped Bitcoin",
                coingecko_id="wrapped-bitcoin",
                chainlink_feed="0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"  # BTC/USD
            ),
            "UNI": TokenInfo(
                address="0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
                symbol="UNI",
                decimals=18,
                name="Uniswap",
                coingecko_id="uniswap",
                chainlink_feed="0x553303d460EE0afB37EdFf9bE42922D8FF63220e"  # UNI/USD
            ),
            "COMP": TokenInfo(
                address="0xc00e94Cb662C3520282E6f5717214004A7f26888",
                symbol="COMP",
                decimals=18,
                name="Compound",
                coingecko_id="compound-governance-token",
                chainlink_feed="0xdbd020CAeF83eFd542f4De03e3cF0C28A4428bd5"  # COMP/USD
            ),
            "stETH": TokenInfo(
                address="0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
                symbol="stETH",
                decimals=18,
                name="Lido Staked ETH",
                coingecko_id="staked-ether",
                chainlink_feed="0xCfE54B5cD566aB89272946F602D76Ea879CAb4a8"  # stETH/USD
            ),
            # VERITE dataset tokens
            "UERII": TokenInfo(
                address="0x418C24191aE947A78C99fDc0e45a1f96Afb254BE",
                symbol="UERII",
                decimals=6,
                name="UERII Token",
                coingecko_id="uerii"  # May not exist, will fallback
            )
        },
        56: {  # BSC Mainnet
            "BNB": TokenInfo(
                address="0x0000000000000000000000000000000000000000",
                symbol="BNB",
                decimals=18,
                name="Binance Coin",
                is_wrapped_native=False,
                coingecko_id="binancecoin",
                chainlink_feed="0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE"  # BNB/USD
            ),
            "WBNB": TokenInfo(
                address="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
                symbol="WBNB",
                decimals=18,
                name="Wrapped BNB",
                is_wrapped_native=True,
                coingecko_id="binancecoin",
                chainlink_feed="0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE"  # BNB/USD
            ),
            "USDT": TokenInfo(
                address="0x55d398326f99059fF775485246999027B3197955",
                symbol="USDT",
                decimals=18,
                name="Tether USD",
                is_stablecoin=True,
                coingecko_id="tether",
                chainlink_feed="0xB97Ad0E74fa7d920791E90258A6E2085088b4320"  # USDT/USD
            ),
            "BUSD": TokenInfo(
                address="0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
                symbol="BUSD",
                decimals=18,
                name="Binance USD",
                is_stablecoin=True,
                coingecko_id="binance-usd",
                chainlink_feed="0xcBb98864Ef56E9042e7d2efef76141f15731B82f"  # BUSD/USD
            ),
            "CAKE": TokenInfo(
                address="0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
                symbol="CAKE",
                decimals=18,
                name="PancakeSwap Token",
                coingecko_id="pancakeswap-token",
                chainlink_feed="0xB6064eD41d4f67e353768aA239cA86f4F73665a1"  # CAKE/USD
            )
        }
    }
    
    # DEX router addresses for pricing
    DEX_ROUTERS = {
        1: {  # Ethereum
            "uniswap_v2": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
            "uniswap_v3": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
            "sushiswap": "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F"
        },
        56: {  # BSC
            "pancakeswap_v2": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
            "pancakeswap_v3": "0x1b81D678ffb9C0263b24A97847620C99d213eB14"
        }
    }
    
    @classmethod
    def get_token_info(cls, chain_id: int, symbol: str) -> Optional[TokenInfo]:
        """Get token info by symbol"""
        chain_tokens = cls.TOKENS.get(chain_id, {})
        return chain_tokens.get(symbol.upper())
    
    @classmethod
    def get_token_by_address(cls, chain_id: int, address: str) -> Optional[TokenInfo]:
        """Get token info by address"""
        chain_tokens = cls.TOKENS.get(chain_id, {})
        address_lower = address.lower()
        
        for token_info in chain_tokens.values():
            if token_info.address.lower() == address_lower:
                return token_info
        return None
    
    @classmethod
    def get_all_tokens(cls, chain_id: int) -> Dict[str, TokenInfo]:
        """Get all tokens for a chain"""
        return cls.TOKENS.get(chain_id, {})
    
    @classmethod
    def get_base_currency(cls, chain_id: int) -> str:
        """Get base currency symbol for chain"""
        if chain_id == 1:
            return "ETH"
        elif chain_id == 56:
            return "BNB"
        else:
            return "ETH"  # Default fallback
    
    @classmethod
    def get_stablecoins(cls, chain_id: int) -> List[TokenInfo]:
        """Get all stablecoins for a chain"""
        chain_tokens = cls.TOKENS.get(chain_id, {})
        return [token for token in chain_tokens.values() if token.is_stablecoin]
    
    @classmethod
    def get_dex_routers(cls, chain_id: int) -> Dict[str, str]:
        """Get DEX router addresses for chain"""
        return cls.DEX_ROUTERS.get(chain_id, {})
    
    @classmethod
    def is_native_token(cls, chain_id: int, address: str) -> bool:
        """Check if address represents native token"""
        return address.lower() in [
            "0x0000000000000000000000000000000000000000",
            "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        ]
    
    @classmethod
    def get_native_token_info(cls, chain_id: int) -> Optional[TokenInfo]:
        """Get native token info"""
        base_currency = cls.get_base_currency(chain_id)
        return cls.get_token_info(chain_id, base_currency)