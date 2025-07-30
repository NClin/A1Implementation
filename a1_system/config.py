"""
Configuration management for A1 system
"""

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class Config:
    """Configuration for A1 system"""
    
    # LLM Configuration
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    default_model: str = "anthropic/claude-sonnet-4"  # Free model for testing
    max_iterations: int = 3  # Paper shows diminishing returns: +9.7%, +3.7%, +5.1%, +2.8% for iterations 2-5
    temperature: float = 0.1
    max_tokens: int = 120000  # Increased for o3-pro reasoning + output
    
    # Blockchain Configuration - Archive node support for historical blocks  
    ethereum_rpc_url: str = os.getenv("ETHEREUM_RPC_URL", 
                                      os.getenv("ALCHEMY_API_KEY", 
                                                "https://ethereum-rpc.publicnode.com"))
    ethereum_archive_url: str = os.getenv("ETHEREUM_ARCHIVE_URL",
                                          os.getenv("ALCHEMY_API_KEY", 
                                                    "https://ethereum-rpc.publicnode.com"))
    avalanche_rpc_url: str = os.getenv("AVALANCHE_RPC_URL", "https://api.avax.network/ext/bc/C/rpc")
    bsc_rpc_url: str = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
    bsc_archive_url: str = os.getenv("BSC_ARCHIVE_URL", "https://bsc-dataseed.binance.org")
    etherscan_api_key: str = os.getenv("ETHERSCAN_API_KEY", "YourApiKeyToken")
    
    # Foundry Configuration
    foundry_path: str = os.getenv("FOUNDRY_PATH", "/usr/local/bin/forge")
    test_timeout: int = 300  # 5 minutes
    
    # Economic Validation - Per paper Section IV.D Initial State Normalization
    initial_eth_balance: int = 100000  # 10^5 ETH (paper specification)
    initial_erc20_balance: int = 10000000  # 10^7 tokens (USDC/USDT per paper)
    revenue_cap_usd: int = 20000  # $20k cap per paper
    
    # Multi-asset initialization per paper
    initial_balances_eth: Optional[Dict[str, int]] = None  # Set in __post_init__
    initial_balances_bsc: Optional[Dict[str, int]] = None  # Set in __post_init__
    
    # Security Settings
    sandbox_mode: bool = True
    max_gas_limit: int = 30000000
    analysis_timeout: int = 1800  # 30 minutes
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "a1_system.log"
    
    # Cost Management
    max_cost_per_analysis: float = 5.0  # USD
    cost_tracking: bool = True
    
    def __post_init__(self):
        """Post-initialization processing"""
        # Initialize multi-asset balances per paper Section IV.D
        if self.initial_balances_eth is None:
            self.initial_balances_eth = {
                "ETH": self.initial_eth_balance,      # 10^5 ETH
                "WETH": self.initial_eth_balance,     # 10^5 WETH  
                "USDC": self.initial_erc20_balance,   # 10^7 USDC
                "USDT": self.initial_erc20_balance    # 10^7 USDT
            }
        
        if self.initial_balances_bsc is None:
            self.initial_balances_bsc = {
                "BNB": self.initial_eth_balance,      # 10^5 BNB
                "WBNB": self.initial_eth_balance,     # 10^5 WBNB
                "USDT": self.initial_erc20_balance,   # 10^7 USDT
                "BUSD": self.initial_erc20_balance    # 10^7 BUSD
            }
        
        # If ALCHEMY_API_KEY is set, use it (supports both key and full URL formats)
        if "ALCHEMY_API_KEY" in os.environ:
            alchemy_value = os.environ["ALCHEMY_API_KEY"]
            if alchemy_value.startswith("https://"):
                # Full URL provided, extract key for BSC
                if "eth-mainnet.g.alchemy.com/v2/" in alchemy_value:
                    self.ethereum_rpc_url = alchemy_value
                    self.ethereum_archive_url = alchemy_value
            else:
                # Just key provided, construct URLs
                alchemy_key = alchemy_value
                if not self.ethereum_rpc_url.startswith("http"):
                    self.ethereum_rpc_url = f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_key}"
                if not self.ethereum_archive_url.startswith("http"):
                    self.ethereum_archive_url = f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_key}"
    
    def validate(self) -> bool:
        """Validate configuration"""
        required_fields = [
            self.openrouter_api_key,
            self.ethereum_rpc_url,
            self.etherscan_api_key
        ]
        
        if not all(required_fields):
            raise ValueError("Missing required configuration fields")
            
        return True
    
    def get_chain_config(self, chain_id: int) -> Dict[str, Any]:
        """Get chain-specific configuration"""
        chain_configs = {
            1: {  # Ethereum
                "name": "Ethereum",
                "rpc_url": self.ethereum_archive_url,  # Use archive URL for historical blocks
                "scanner_api_key": self.etherscan_api_key,
                "scanner_url": "https://api.etherscan.io/api",
                "base_currency": "ETH",
                "wrapped_token": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
                "stable_tokens": [
                    "0xA0b86a33E6441d00C9Dab2B5Ff0b19dc5D9c0cd0", # USDC
                    "0xdac17f958d2ee523a2206206994597c13d831ec7"  # USDT
                ]
            },
            43114: {  # Avalanche
                "name": "Avalanche",
                "rpc_url": self.avalanche_rpc_url,
                "scanner_api_key": self.etherscan_api_key,
                "scanner_url": "https://api.routescan.io/v2/network/mainnet/evm/43114/etherscan/api",
                "base_currency": "AVAX",
                "wrapped_token": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",  # WAVAX
                "stable_tokens": [
                    "0xc7198437980c041c805A1EDcbA50c1Ce5db95118",  # USDT.e
                    "0xA7D7079b0FEaD91F3e65f86E8915Cb59c1a4C664"   # USDC.e
                ]
            },
            56: {  # BSC
                "name": "Binance Smart Chain",
                "rpc_url": self.bsc_archive_url,  # Use archive URL for historical blocks
                "scanner_api_key": self.etherscan_api_key,
                "scanner_url": "https://api.etherscan.io/v2/api",
                "chain_id": 56,
                "base_currency": "BNB",
                "wrapped_token": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
                "stable_tokens": [
                    "0x55d398326f99059ff775485246999027b3197955",  # USDT
                    "0xe9e7cea3dedca5984780bafc599bd69add087d56"   # BUSD
                ]
            }
        }
        
        return chain_configs.get(chain_id, {})
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Create config from environment variables"""
        return cls()

# Default configuration instance
config = Config.from_env() 