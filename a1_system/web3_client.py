"""
Web3 Client for A1 System - Blockchain interaction wrapper
"""

import asyncio
import logging
import json
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from web3 import Web3

# Handle different web3.py versions for middleware import
try:
    from web3.middleware import geth_poa_middleware
except ImportError:
    try:
        from web3.middleware.geth_poa import geth_poa_middleware
    except ImportError:
        # For very old versions or if completely removed
        geth_poa_middleware = None

from eth_utils import to_checksum_address, is_address
from .config import Config


@dataclass
class ContractCall:
    """Represents a contract function call"""
    address: str
    function_name: str
    inputs: List[Any]
    outputs: List[str]  # ABI output types
    

class Web3Client:
    """
    Web3 wrapper for blockchain interactions
    
    Features:
    - Multi-chain support (Ethereum, BSC)
    - State reading and storage queries
    - Proxy resolution (EIP-1967, EIP-1822)
    - Batch calls for efficiency
    - Archive node support for historical queries
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Web3 connections for different chains
        self.connections: Dict[int, Web3] = {}
        
        # EIP-1967 and EIP-1822 storage slots
        self.proxy_slots = {
            # EIP-1967 Implementation slot: keccak256("eip1967.proxy.implementation") - 1
            "eip1967_impl": "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
            # EIP-1967 Admin slot: keccak256("eip1967.proxy.admin") - 1  
            "eip1967_admin": "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103",
            # EIP-1822 Implementation slot: keccak256("PROXIABLE")
            "eip1822_impl": "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"
        }
    
    def get_web3(self, chain_id: int) -> Optional[Web3]:
        """Get Web3 connection for chain"""
        
        if chain_id in self.connections:
            return self.connections[chain_id]
        
        # Get chain config
        chain_config = self.config.get_chain_config(chain_id)
        if not chain_config or not chain_config.get("rpc_url"):
            self.logger.error(f"No RPC URL configured for chain {chain_id}")
            return None
        
        try:
            # Create Web3 connection
            rpc_url = chain_config["rpc_url"]
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            
            # Add PoA middleware for BSC and other PoA chains
            if chain_id == 56 and geth_poa_middleware:  # BSC
                w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            
            # Test connection
            if not w3.is_connected():
                self.logger.error(f"Failed to connect to chain {chain_id} RPC: {rpc_url}")
                return None
            
            # Cache connection
            self.connections[chain_id] = w3
            
            self.logger.info(f"Connected to chain {chain_id}: block {w3.eth.block_number}")
            return w3
            
        except Exception as e:
            self.logger.error(f"Error connecting to chain {chain_id}: {str(e)}")
            return None
    
    async def get_latest_block(self, chain_id: int) -> Optional[int]:
        """Get latest block number for chain"""
        
        w3 = self.get_web3(chain_id)
        if not w3:
            return None
        
        try:
            return w3.eth.block_number
        except Exception as e:
            self.logger.error(f"Error getting latest block for chain {chain_id}: {str(e)}")
            return None
    
    async def get_storage_at(
        self, 
        chain_id: int, 
        address: str, 
        slot: Union[str, int], 
        block_number: Optional[int] = None
    ) -> Optional[str]:
        """Read storage slot at address"""
        
        w3 = self.get_web3(chain_id)
        if not w3:
            return None
        
        try:
            address = to_checksum_address(address)
            block_id = block_number if block_number else "latest"
            
            storage_value = w3.eth.get_storage_at(address, slot, block_id)
            return storage_value.hex()
            
        except Exception as e:
            self.logger.error(f"Error reading storage {slot} at {address}: {str(e)}")
            return None
    
    async def resolve_proxy(
        self, 
        chain_id: int, 
        proxy_address: str, 
        block_number: Optional[int] = None
    ) -> Optional[str]:
        """
        Resolve proxy contract to implementation address
        Supports EIP-1967 and EIP-1822 standards
        """
        
        if not is_address(proxy_address):
            return None
        
        proxy_address = to_checksum_address(proxy_address)
        
        # Try EIP-1967 implementation slot first
        impl_storage = await self.get_storage_at(
            chain_id, 
            proxy_address, 
            self.proxy_slots["eip1967_impl"], 
            block_number
        )
        
        if impl_storage and impl_storage != "0x" + "0" * 64:
            # Extract address from storage (last 20 bytes)
            impl_address = "0x" + impl_storage[-40:]
            if is_address(impl_address) and impl_address != "0x" + "0" * 40:
                self.logger.info(f"EIP-1967 proxy detected: {proxy_address} -> {impl_address}")
                return to_checksum_address(impl_address)
        
        # Try EIP-1822 implementation slot
        impl_storage = await self.get_storage_at(
            chain_id,
            proxy_address,
            self.proxy_slots["eip1822_impl"],
            block_number
        )
        
        if impl_storage and impl_storage != "0x" + "0" * 64:
            # Extract address from storage (last 20 bytes)
            impl_address = "0x" + impl_storage[-40:]
            if is_address(impl_address) and impl_address != "0x" + "0" * 40:
                self.logger.info(f"EIP-1822 proxy detected: {proxy_address} -> {impl_address}")
                return to_checksum_address(impl_address)
        
        # No proxy pattern detected
        return None
    
    async def call_contract_function(
        self,
        chain_id: int,
        contract_address: str,
        function_abi: Dict[str, Any],
        inputs: List[Any] = None,
        block_number: Optional[int] = None
    ) -> Optional[Any]:
        """Call a contract view function"""
        
        w3 = self.get_web3(chain_id)
        if not w3:
            return None
        
        try:
            contract_address = to_checksum_address(contract_address)
            inputs = inputs or []
            block_id = block_number if block_number else "latest"
            
            # Create contract instance with minimal ABI
            contract = w3.eth.contract(
                address=contract_address,
                abi=[function_abi]
            )
            
            # Get function
            function = contract.get_function_by_name(function_abi["name"])
            
            # Call function
            result = function(*inputs).call(block_identifier=block_id)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error calling function {function_abi.get('name', 'unknown')}: {str(e)}")
            return None
    
    async def get_basic_contract_info(
        self,
        chain_id: int,
        contract_address: str,
        block_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get basic information about a contract"""
        
        w3 = self.get_web3(chain_id)
        if not w3:
            return {"error": "No Web3 connection"}
        
        try:
            contract_address = to_checksum_address(contract_address)
            block_id = block_number if block_number else "latest"
            
            # Get contract code
            code = w3.eth.get_code(contract_address, block_id)
            
            info = {
                "address": contract_address,
                "has_code": len(code) > 0,
                "code_size": len(code),
                "block_number": block_id
            }
            
            # Check if it's a proxy
            impl_address = await self.resolve_proxy(chain_id, contract_address, block_number)
            if impl_address:
                info["is_proxy"] = True
                info["implementation"] = impl_address
            else:
                info["is_proxy"] = False
            
            return info
            
        except Exception as e:
            return {"error": str(e)}
    
    async def read_contract_state(
        self,
        chain_id: int,
        contract_address: str,
        abi: List[Dict[str, Any]],
        block_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Read contract state by calling all view functions
        """
        
        state = {}
        
        # Filter for view/pure functions with no inputs
        view_functions = [
            func for func in abi 
            if func.get("type") == "function" 
            and func.get("stateMutability") in ["view", "pure"]
            and len(func.get("inputs", [])) == 0
        ]
        
        for func_abi in view_functions:
            func_name = func_abi["name"]
            
            try:
                result = await self.call_contract_function(
                    chain_id,
                    contract_address,
                    func_abi,
                    [],
                    block_number
                )
                
                if result is not None:
                    state[func_name] = result
                    
            except Exception as e:
                self.logger.debug(f"Failed to call {func_name}: {str(e)}")
                state[func_name] = {"error": str(e)}
        
        return state
    
    def parse_abi_string(self, abi_string: str) -> List[Dict[str, Any]]:
        """Parse ABI string to list of function definitions"""
        
        try:
            if isinstance(abi_string, str):
                return json.loads(abi_string)
            return abi_string
        except json.JSONDecodeError:
            self.logger.error("Invalid ABI format")
            return []
    
    async def batch_call_view_functions(
        self,
        chain_id: int,
        calls: List[ContractCall],
        block_number: Optional[int] = None
    ) -> List[Any]:
        """
        Batch multiple contract calls for efficiency
        TODO: Implement actual multicall contract usage
        """
        
        results = []
        
        # For now, make sequential calls
        # In production, would use Multicall contract for batch efficiency
        for call in calls:
            try:
                # Create minimal function ABI
                func_abi = {
                    "name": call.function_name,
                    "type": "function",
                    "stateMutability": "view",
                    "inputs": [],  # Simplified for now
                    "outputs": [{"type": output_type} for output_type in call.outputs]
                }
                
                result = await self.call_contract_function(
                    chain_id,
                    call.address,
                    func_abi,
                    call.inputs,
                    block_number
                )
                
                results.append(result)
                
            except Exception as e:
                self.logger.error(f"Batch call failed for {call.function_name}: {str(e)}")
                results.append(None)
        
        return results
    
    def close_connections(self):
        """Close all Web3 connections"""
        self.connections.clear()
        self.logger.info("Closed all Web3 connections") 