"""
State Reader Tool - Queries contract state at specific blocks
"""

import time
import json
from typing import Dict, Any, List, Optional
from .base import BaseTool, ToolResult
from ..web3_client import Web3Client


class StateReaderTool(BaseTool):
    """
    Tool for reading smart contract state using Web3
    
    Features:
    - Read contract state variables via view functions
    - Support for historical state queries at specific blocks
    - Automatic ABI parsing and function discovery
    - Batch calls for efficiency
    """
    
    def __init__(self, config):
        super().__init__(config)
        self.web3_client = Web3Client(config)
    
    def get_name(self) -> str:
        return "state_reader_tool"
    
    def get_description(self) -> str:
        return "Queries contract state variables and function results using Web3"
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Read contract state at specific block
        
        Args:
            params: {
                "chain_id": int - Chain ID (1=Ethereum, 56=BSC)
                "contract_address": str - Contract address to query
                "block_number": int - Block number for historical consistency (optional)
                "abi": str|List - Contract ABI (JSON string or parsed)
                "specific_functions": List[str] - Specific functions to call (optional)
                "include_balances": bool - Whether to read common balance functions (default: True)
            }
        
        Returns:
            ToolResult with contract state data
        """
        
        start_time = time.time()
        
        try:
            chain_id = params.get("chain_id")
            contract_address = params.get("contract_address", "").lower()
            block_number = params.get("block_number")
            abi_data = params.get("abi")
            specific_functions = params.get("specific_functions", [])
            include_balances = params.get("include_balances", True)
            
            if not chain_id or not contract_address:
                return ToolResult(
                    success=False,
                    data={},
                    error_message="Missing chain_id or contract_address",
                    tool_name=self.get_name()
                )
            
            self.logger.info(f"Reading state for {contract_address} on chain {chain_id}")
            
            # Parse ABI if provided
            abi = []
            if abi_data:
                if isinstance(abi_data, str):
                    try:
                        abi = json.loads(abi_data)
                    except json.JSONDecodeError:
                        self.logger.warning("Invalid ABI format, using standard functions")
                        abi = []
                elif isinstance(abi_data, list):
                    abi = abi_data
            
            # Get basic contract info
            contract_info = await self.web3_client.get_basic_contract_info(
                chain_id, contract_address, block_number
            )
            
            if "error" in contract_info:
                return ToolResult(
                    success=False,
                    data={},
                    error_message=f"Contract info error: {contract_info['error']}",
                    tool_name=self.get_name()
                )
            
            if not contract_info.get("has_code", False):
                return ToolResult(
                    success=False,
                    data={},
                    error_message="Address has no contract code",
                    tool_name=self.get_name()
                )
            
            # Read contract state
            state_data = {}
            
            if abi:
                # Use provided ABI to read state
                contract_state = await self.web3_client.read_contract_state(
                    chain_id, contract_address, abi, block_number
                )
                state_data.update(contract_state)
            
            # Try common functions if no ABI or if specified
            if not abi or include_balances:
                common_state = await self._read_common_functions(
                    chain_id, contract_address, block_number
                )
                state_data.update(common_state)
            
            # Try specific functions if requested
            if specific_functions:
                for func_name in specific_functions:
                    if func_name not in state_data:  # Don't override existing
                        result = await self._try_function_call(
                            chain_id, contract_address, func_name, block_number
                        )
                        if result is not None:
                            state_data[func_name] = result
            
            execution_time = time.time() - start_time
            
            result_data = {
                "contract_address": contract_address,
                "chain_id": chain_id,
                "block_number": block_number,
                "contract_info": contract_info,
                "state": state_data,
                "functions_called": len(state_data),
                "successful_calls": len(state_data)
            }
            
            successful_functions = list(state_data.keys()) if state_data else []
            self.logger.info(
                f"State reading completed: {len(state_data)} successful function calls"
                + (f" ({', '.join(successful_functions)})" if successful_functions else " (no functions available)")
            )
            
            return ToolResult(
                success=True,
                data=result_data,
                execution_time=execution_time,
                tool_name=self.get_name()
            )
            
        except Exception as e:
            self.logger.error(f"State reading failed: {str(e)}")
            return ToolResult(
                success=False,
                data={},
                error_message=f"State reading error: {str(e)}",
                execution_time=time.time() - start_time,
                tool_name=self.get_name()
            )
    
    async def _read_common_functions(
        self, 
        chain_id: int, 
        contract_address: str, 
        block_number: Optional[int]
    ) -> Dict[str, Any]:
        """
        Try common ERC20/ERC721 functions
        """
        
        common_functions = [
            # ERC20 functions
            {"name": "name", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
            {"name": "symbol", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
            {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
            {"name": "totalSupply", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint256"}]},
            
            # Common access control
            {"name": "owner", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
            {"name": "admin", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
            
            # Common state variables
            {"name": "paused", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "bool"}]},
            {"name": "version", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
        ]
        
        state = {}
        
        for func_abi in common_functions:
            func_name = func_abi["name"]
            
            try:
                result = await self.web3_client.call_contract_function(
                    chain_id,
                    contract_address,
                    func_abi,
                    [],
                    block_number
                )
                
                if result is not None:
                    state[func_name] = result
                    
            except Exception as e:
                # Don't log errors for common functions (many won't exist)
                continue
        
        return state
    
    async def _try_function_call(
        self,
        chain_id: int,
        contract_address: str,
        function_name: str,
        block_number: Optional[int],
        inputs: List[Any] = None
    ) -> Any:
        """
        Try to call a function by name with minimal ABI
        """
        
        inputs = inputs or []
        
        # Create a generic function ABI
        func_abi = {
            "name": function_name,
            "type": "function",
            "stateMutability": "view",
            "inputs": [],  # Assume no inputs for now
            "outputs": [{"type": "bytes"}]  # Generic output
        }
        
        try:
            return await self.web3_client.call_contract_function(
                chain_id,
                contract_address,
                func_abi,
                inputs,
                block_number
            )
        except Exception:
            return None
    
    async def read_storage_slots(
        self,
        chain_id: int,
        contract_address: str,
        slots: List[str],
        block_number: Optional[int] = None
    ) -> Dict[str, str]:
        """
        Read raw storage slots
        """
        
        storage = {}
        
        for slot in slots:
            try:
                value = await self.web3_client.get_storage_at(
                    chain_id, contract_address, slot, block_number
                )
                if value:
                    storage[slot] = value
            except Exception as e:
                storage[slot] = f"error: {str(e)}"
        
        return storage
    
    async def get_token_balances(
        self,
        chain_id: int,
        token_address: str,
        holder_addresses: List[str],
        block_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get token balances for multiple addresses
        """
        
        balances = {}
        
        # ERC20 balanceOf function ABI
        balance_abi = {
            "name": "balanceOf",
            "type": "function",
            "stateMutability": "view",
            "inputs": [{"name": "account", "type": "address"}],
            "outputs": [{"type": "uint256"}]
        }
        
        for address in holder_addresses:
            try:
                balance = await self.web3_client.call_contract_function(
                    chain_id,
                    token_address,
                    balance_abi,
                    [address],
                    block_number
                )
                
                if balance is not None:
                    balances[address] = balance
                    
            except Exception as e:
                balances[address] = f"error: {str(e)}"
        
        return balances 