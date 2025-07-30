"""
Source Code Fetcher Tool - Resolves proxy contracts and fetches verified source code
"""

import asyncio
import aiohttp
import time
import json
import re
from typing import Dict, Any, Optional, List
from .base import BaseTool, ToolResult


class SourceCodeFetcher(BaseTool):
    """
    Tool for fetching smart contract source code with proxy resolution
    
    Features:
    - Fetches verified source code from Etherscan/BSCScan
    - Resolves proxy contracts (EIP-1967, EIP-1822)
    - Maintains temporal consistency at specific blocks
    """
    
    def __init__(self, config):
        super().__init__(config)
        # Import here to avoid circular imports
        from ..web3_client import Web3Client
        self.web3_client = Web3Client(config)
    
    def get_name(self) -> str:
        return "source_code_fetcher"
    
    def get_description(self) -> str:
        return "Fetches verified smart contract source code with proxy resolution support"
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Fetch contract source code with proxy resolution
        
        Args:
            params: {
                "chain_id": int - Chain ID (1=Ethereum, 56=BSC)
                "contract_address": str - Contract address to fetch
                "block_number": int - Block number for historical consistency
                "resolve_proxies": bool - Whether to resolve proxy contracts (default: True)
            }
        
        Returns:
            ToolResult with source code and metadata
        """
        
        start_time = time.time()
        
        try:
            chain_id = params.get("chain_id")
            contract_address = params.get("contract_address", "").lower()
            block_number = params.get("block_number")
            resolve_proxies = params.get("resolve_proxies", True)
            
            self.logger.info(f"🔍 Source fetcher started for {contract_address} on chain {chain_id}")
            
            if not chain_id or not contract_address:
                return ToolResult(
                    success=False,
                    data={},
                    error_message="Missing chain_id or contract_address",
                    tool_name=self.get_name()
                )
            
            # Get chain configuration
            chain_config = self.config.get_chain_config(chain_id)
            if not chain_config:
                self.logger.error(f"❌ Unsupported chain ID: {chain_id}")
                return ToolResult(
                    success=False,
                    data={},
                    error_message=f"Unsupported chain ID: {chain_id}",
                    tool_name=self.get_name()
                )
            
            self.logger.info(f"✅ Chain config found: {chain_config.get('name', 'Unknown')}")
            
            # Clean address format
            if not contract_address.startswith("0x"):
                contract_address = "0x" + contract_address
            
            # Validate address format
            if not re.match(r"^0x[a-fA-F0-9]{40}$", contract_address):
                self.logger.error(f"❌ Invalid address format: {contract_address}")
                return ToolResult(
                    success=False,
                    data={},
                    error_message=f"Invalid contract address format: {contract_address}",
                    tool_name=self.get_name()
                )
            
            self.logger.info(f"📡 Fetching source code from {chain_config.get('scanner_url', 'Unknown API')}...")
            
            # Fetch source code
            source_data = await self._fetch_source_code(
                contract_address, 
                chain_config["scanner_url"], 
                chain_config["scanner_api_key"],
                chain_id
            )
            
            if not source_data["success"]:
                self.logger.error(f"❌ Source code fetch failed: {source_data['error']}")
                return ToolResult(
                    success=False,
                    data={},
                    error_message=source_data["error"],
                    tool_name=self.get_name()
                )
            
            self.logger.info(f"✅ Source code fetched successfully: {len(source_data['source_code'])} characters")
            
            # Check if this is a proxy contract and resolve if needed
            implementation_address = None
            if resolve_proxies:
                self.logger.info("🔍 Checking for proxy contract...")
                implementation_address = await self._resolve_proxy(
                    contract_address,
                    chain_id,
                    block_number
                )
                
                if implementation_address and implementation_address != contract_address:
                    self.logger.info(f"🎯 Proxy detected: {contract_address} -> {implementation_address}")
                    
                    # Fetch implementation source code
                    impl_source_data = await self._fetch_source_code(
                        implementation_address,
                        chain_config["scanner_url"],
                        chain_config["scanner_api_key"],
                        chain_id
                    )
                    
                    if impl_source_data["success"]:
                        self.logger.info(f"✅ Implementation source code fetched: {len(impl_source_data['source_code'])} characters")
                        # Use implementation source code but keep proxy metadata
                        source_data["source_code"] = impl_source_data["source_code"]
                        source_data["contract_name"] = impl_source_data["contract_name"]
                        source_data["compiler_version"] = impl_source_data["compiler_version"]
                        source_data["abi"] = impl_source_data["abi"]
                    else:
                        self.logger.warning(f"⚠️ Failed to fetch implementation source: {impl_source_data['error']}")
                else:
                    self.logger.info("ℹ️ Not a proxy contract or proxy resolution failed")
            
            execution_time = time.time() - start_time
            
            result_data = {
                "contract_address": contract_address,
                "implementation_address": implementation_address,
                "is_proxy": implementation_address is not None,
                "source_code": source_data["source_code"],
                "contract_name": source_data["contract_name"],
                "compiler_version": source_data["compiler_version"],
                "abi": source_data["abi"],
                "chain_id": chain_id,
                "block_number": block_number,
                "verification_status": "verified" if source_data["success"] else "unverified"
            }
            
            self.logger.info(f"🎉 Source fetch completed in {execution_time:.2f}s - contract: {source_data['contract_name']}")
            self.logger.debug(f"Source code preview:\n{source_data['source_code'][:500]}...")
            
            return ToolResult(
                success=True,
                data=result_data,
                tool_name=self.get_name(),
                execution_time=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Source fetcher error: {str(e)}"
            self.logger.error(f"❌ {error_msg}")
            return ToolResult(
                success=False,
                data={},
                error_message=error_msg,
                tool_name=self.get_name(),
                execution_time=execution_time
            )
    
    async def _fetch_source_code(self, contract_address: str, scanner_url: str, api_key: str, chain_id: int = 1) -> Dict[str, Any]:
        """
        Fetch source code from blockchain explorer API
        Supports both legacy API (Ethereum) and V2 unified API (BSC)
        """
        
        # Build API parameters based on API version
        if "v2/api" in scanner_url:
            # Etherscan V2 unified API (for BSC and other chains)
            params = {
                "chainid": chain_id,
                "module": "contract",
                "action": "getsourcecode",
                "address": contract_address,
                "apikey": api_key
            }
        else:
            # Legacy API (for Ethereum)
            params = {
                "module": "contract",
                "action": "getsourcecode",
                "address": contract_address,
                "apikey": api_key
            }
        
        self.logger.info(f"🌐 Making API request to scanner...")
        self.logger.debug(f"API URL: {scanner_url}")
        self.logger.debug(f"API params: {params}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(scanner_url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    
                    self.logger.info(f"📡 API response status: {response.status}")
                    
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"❌ API HTTP error {response.status}: {error_text[:500]}...")
                        return {
                            "success": False,
                            "error": f"API error {response.status}: {error_text}"
                        }
                    
                    data = await response.json()
                    self.logger.debug(f"API response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                    
                    if data.get("status") != "1":
                        error_msg = data.get('message', 'Unknown error')
                        self.logger.error(f"❌ API returned error status: {error_msg}")
                        return {
                            "success": False,
                            "error": f"API returned error: {error_msg}"
                        }
                    
                    result = data.get("result", [])
                    if not result or not isinstance(result, list):
                        self.logger.error("❌ No source code data returned from API")
                        return {
                            "success": False,
                            "error": "No source code data returned"
                        }
                    
                    contract_data = result[0]
                    self.logger.debug(f"Contract data keys: {list(contract_data.keys()) if isinstance(contract_data, dict) else 'Not a dict'}")
                    
                    source_code = contract_data.get("SourceCode", "")
                    contract_name = contract_data.get("ContractName", "Unknown")
                    
                    self.logger.info(f"📋 Raw source code length: {len(source_code)} characters")
                    self.logger.info(f"📋 Contract name: {contract_name}")
                    
                    if not source_code:
                        self.logger.error("❌ Contract source code not verified on explorer")
                        return {
                            "success": False,
                            "error": "Contract source code not verified"
                        }
                    
                    # Handle different source code formats
                    self.logger.info("🔄 Parsing source code format...")
                    parsed_source = self._parse_source_code(source_code)
                    self.logger.info(f"✅ Parsed source code length: {len(parsed_source)} characters")
                    
                    return {
                        "success": True,
                        "source_code": parsed_source,
                        "contract_name": contract_name,
                        "compiler_version": contract_data.get("CompilerVersion", "Unknown"),
                        "abi": contract_data.get("ABI", "[]")
                    }
                    
        except Exception as e:
            self.logger.error(f"❌ API request failed: {str(e)}")
            return {
                "success": False,
                "error": f"Request failed: {str(e)}"
            }
    
    def _parse_source_code(self, raw_source: str) -> str:
        """
        Parse different source code formats (single file, multi-file JSON, etc.)
        """
        
        if not raw_source:
            return ""
        
        # Check if it's JSON format (multi-file contract)
        if raw_source.startswith("{") and raw_source.endswith("}"):
            try:
                # Try to parse as JSON
                source_json = json.loads(raw_source)
                
                # Handle different JSON structures
                if "sources" in source_json:
                    # Standard JSON format
                    sources = []
                    for file_path, file_data in source_json["sources"].items():
                        content = file_data.get("content", "")
                        sources.append(f"// File: {file_path}\n{content}")
                    return "\n\n".join(sources)
                
                elif isinstance(source_json, dict):
                    # Direct file mapping
                    sources = []
                    for file_path, content in source_json.items():
                        if isinstance(content, str):
                            sources.append(f"// File: {file_path}\n{content}")
                        elif isinstance(content, dict) and "content" in content:
                            sources.append(f"// File: {file_path}\n{content['content']}")
                    return "\n\n".join(sources)
                
            except json.JSONDecodeError:
                # If JSON parsing fails, treat as raw source
                pass
        
        # Handle wrapped JSON (some explorers wrap JSON in extra braces)
        if raw_source.startswith("{{") and raw_source.endswith("}}"):
            try:
                # Remove outer braces and try parsing
                inner_json = raw_source[1:-1]
                return self._parse_source_code(inner_json)
            except:
                pass
        
        # Return as-is for single file contracts
        return raw_source
    
    async def _resolve_proxy(self, proxy_address: str, chain_id: int, block_number: Optional[int]) -> Optional[str]:
        """
        Resolve proxy contract to implementation address
        Supports EIP-1967 and EIP-1822 patterns
        """
        
        try:
            # Use Web3 client for proxy resolution
            implementation_address = await self.web3_client.resolve_proxy(
                chain_id, 
                proxy_address,
                block_number
            )
            
            return implementation_address
            
        except Exception as e:
            self.logger.error(f"Error resolving proxy {proxy_address}: {str(e)}")
            return None
    
    def is_contract_verified(self, contract_address: str, chain_id: int) -> bool:
        """
        Quick check if contract is verified without fetching full source
        """
        # This could be implemented as a lightweight API call
        # For now, assume we need to fetch to know
        return True
    
    async def get_contract_metadata(self, contract_address: str, chain_id: int) -> Dict[str, Any]:
        """
        Get basic contract metadata without full source code
        """
        
        chain_config = self.config.get_chain_config(chain_id)
        if not chain_config:
            return {"error": f"Unsupported chain: {chain_id}"}
        
        # Simplified metadata fetch
        # In a full implementation, this would be a separate API call
        result = await self.execute({
            "chain_id": chain_id,
            "contract_address": contract_address,
            "resolve_proxies": False
        })
        
        if result.success:
            return {
                "contract_name": result.data.get("contract_name"),
                "compiler_version": result.data.get("compiler_version"),
                "is_verified": True,
                "is_proxy": result.data.get("is_proxy", False)
            }
        else:
            return {"error": result.error_message} 