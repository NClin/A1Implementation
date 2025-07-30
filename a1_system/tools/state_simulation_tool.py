"""
State Simulation Tool for testing contract behavior
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .base import BaseTool, ToolResult, ToolParameter


class StateSimulationTool(BaseTool):
    """
    Tool for simulating contract state changes and testing function behavior
    """
    
    def get_name(self) -> str:
        return "state_simulation_tool"
    
    def get_description(self) -> str:
        return "Simulate contract function calls and analyze state changes, return values, and potential failure scenarios"
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="contract_address", 
                type="string", 
                description="Contract address to simulate"
            ),
            ToolParameter(
                name="chain_id",
                type="integer", 
                description="Blockchain chain ID"
            ),
            ToolParameter(
                name="function_name",
                type="string",
                description="Function to simulate calling"
            ),
            ToolParameter(
                name="function_args",
                type="string",
                description="JSON array of function arguments",
                required=False,
                default="[]"
            ),
            ToolParameter(
                name="caller_address",
                type="string",
                description="Address that would call the function",
                required=False,
                default="0x0000000000000000000000000000000000000001"
            ),
            ToolParameter(
                name="simulation_type",
                type="string",
                description="Type of simulation: 'call' (read-only), 'transaction' (state-changing), 'edge_cases' (test edge cases)",
                enum=["call", "transaction", "edge_cases"],
                default="call"
            ),
            ToolParameter(
                name="block_number",
                type="integer",
                description="Block number to simulate at",
                required=False
            )
        ]
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """Simulate contract function calls"""
        
        try:
            contract_address = params["contract_address"]
            chain_id = params["chain_id"]
            function_name = params["function_name"]
            function_args = json.loads(params.get("function_args", "[]"))
            caller_address = params.get("caller_address", "0x0000000000000000000000000000000000000001")
            simulation_type = params.get("simulation_type", "call")
            block_number = params.get("block_number")
            
            # Get Web3 client
            web3_client = self.config.get_web3_client()
            
            if simulation_type == "call":
                return await self._simulate_call(
                    web3_client, contract_address, chain_id, function_name, 
                    function_args, caller_address, block_number
                )
            elif simulation_type == "transaction":
                return await self._simulate_transaction(
                    web3_client, contract_address, chain_id, function_name,
                    function_args, caller_address, block_number
                )
            elif simulation_type == "edge_cases":
                return await self._test_edge_cases(
                    web3_client, contract_address, chain_id, function_name,
                    function_args, caller_address, block_number
                )
            else:
                return ToolResult(
                    success=False,
                    error_message=f"Unknown simulation type: {simulation_type}"
                )
                
        except Exception as e:
            return ToolResult(
                success=False,
                error_message=f"State simulation failed: {str(e)}"
            )
    
    async def _simulate_call(self, web3_client, contract_address: str, chain_id: int, 
                           function_name: str, function_args: List, caller_address: str,
                           block_number: Optional[int]) -> ToolResult:
        """Simulate a read-only call"""
        
        try:
            # Connect to appropriate chain
            w3 = await web3_client.get_web3_instance(chain_id)
            if not w3:
                return ToolResult(
                    success=False,
                    error_message=f"Could not connect to chain {chain_id}"
                )
            
            # Create contract instance (we'll need ABI - simplified approach)
            # For now, use low-level call simulation
            from web3 import Web3
            
            # Encode function call
            function_signature = f"{function_name}({','.join(['uint256'] * len(function_args))})"
            function_selector = Web3.keccak(text=function_signature)[:4]
            
            # Encode arguments (simplified - assumes all uint256)
            encoded_args = b""
            for arg in function_args:
                if isinstance(arg, int):
                    encoded_args += arg.to_bytes(32, 'big')
                elif isinstance(arg, str) and arg.startswith('0x'):
                    # Address or bytes
                    encoded_args += bytes.fromhex(arg[2:].zfill(64))
            
            call_data = function_selector + encoded_args
            
            # Simulate the call
            call_result = w3.eth.call({
                'to': contract_address,
                'data': call_data.hex(),
                'from': caller_address
            }, block_identifier=block_number or 'latest')
            
            return ToolResult(
                success=True,
                data={
                    "function_name": function_name,
                    "function_args": function_args,
                    "caller": caller_address,
                    "result": call_result.hex(),
                    "result_length": len(call_result),
                    "reverted": False,
                    "block_number": block_number or await web3_client.get_latest_block(chain_id)
                }
            )
            
        except Exception as e:
            # Check if it's a revert
            if "execution reverted" in str(e):
                return ToolResult(
                    success=True,
                    data={
                        "function_name": function_name,
                        "function_args": function_args,
                        "caller": caller_address,
                        "result": None,
                        "reverted": True,
                        "revert_reason": str(e),
                        "block_number": block_number
                    }
                )
            else:
                return ToolResult(
                    success=False,
                    error_message=f"Call simulation failed: {str(e)}"
                )
    
    async def _simulate_transaction(self, web3_client, contract_address: str, chain_id: int,
                                  function_name: str, function_args: List, caller_address: str,
                                  block_number: Optional[int]) -> ToolResult:
        """Simulate a state-changing transaction"""
        
        # For now, similar to call but we can extend this to simulate gas usage,
        # state changes, etc.
        call_result = await self._simulate_call(
            web3_client, contract_address, chain_id, function_name,
            function_args, caller_address, block_number
        )
        
        if call_result.success:
            # Add transaction-specific information
            call_result.data.update({
                "simulation_type": "transaction",
                "estimated_gas": 21000,  # Placeholder
                "state_changing": True
            })
        
        return call_result
    
    async def _test_edge_cases(self, web3_client, contract_address: str, chain_id: int,
                             function_name: str, function_args: List, caller_address: str,
                             block_number: Optional[int]) -> ToolResult:
        """Test edge cases for the function"""
        
        edge_cases = []
        
        # Test with zero values
        if function_args:
            zero_args = [0] * len(function_args)
            zero_result = await self._simulate_call(
                web3_client, contract_address, chain_id, function_name,
                zero_args, caller_address, block_number
            )
            edge_cases.append({
                "case": "zero_values",
                "args": zero_args,
                "result": zero_result.data if zero_result.success else {"error": zero_result.error_message}
            })
        
        # Test with max values
        if function_args:
            max_args = [2**256 - 1] * len(function_args)
            max_result = await self._simulate_call(
                web3_client, contract_address, chain_id, function_name,
                max_args, caller_address, block_number
            )
            edge_cases.append({
                "case": "max_values",
                "args": max_args,
                "result": max_result.data if max_result.success else {"error": max_result.error_message}
            })
        
        # Test with different callers
        special_callers = [
            "0x0000000000000000000000000000000000000000",  # Zero address
            contract_address,  # Self
            "0x000000000000000000000000000000000000dEaD"   # Burn address
        ]
        
        for special_caller in special_callers:
            caller_result = await self._simulate_call(
                web3_client, contract_address, chain_id, function_name,
                function_args, special_caller, block_number
            )
            edge_cases.append({
                "case": f"caller_{special_caller}",
                "args": function_args,
                "caller": special_caller,
                "result": caller_result.data if caller_result.success else {"error": caller_result.error_message}
            })
        
        return ToolResult(
            success=True,
            data={
                "function_name": function_name,
                "edge_cases": edge_cases,
                "total_cases_tested": len(edge_cases)
            }
        )