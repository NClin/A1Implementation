"""
Tool Calling Framework for A1 System
Provides generalizable and extensible tool calling functionality
"""

from typing import Dict, Any, List, Optional, Callable, Union
import json
import logging
import asyncio
from dataclasses import dataclass, asdict
from enum import Enum

from .tools.base import BaseTool, ToolResult, ToolSchema


class ToolCallStatus(Enum):
    """Status of tool call execution"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ToolCall:
    """Represents a tool call request from LLM"""
    id: str
    name: str
    parameters: Dict[str, Any]
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Optional[ToolResult] = None
    error: Optional[str] = None
    execution_time: float = 0.0


@dataclass
class ToolCallMessage:
    """Message containing tool calls from LLM"""
    content: str
    tool_calls: List[ToolCall]


class ToolRegistry:
    """Registry for managing available tools"""
    
    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self.logger = logging.getLogger(f"{__name__}.ToolRegistry")
    
    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool in the registry"""
        name = tool.get_name()
        self.tools[name] = tool
        self.logger.info(f"🔧 Registered tool: {name}")
    
    def unregister_tool(self, name: str) -> None:
        """Unregister a tool from the registry"""
        if name in self.tools:
            del self.tools[name]
            self.logger.info(f"🗑️ Unregistered tool: {name}")
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name"""
        return self.tools.get(name)
    
    def list_tools(self) -> List[str]:
        """List all registered tool names"""
        return list(self.tools.keys())
    
    def get_schemas(self) -> List[ToolSchema]:
        """Get schemas for all registered tools"""
        schemas = []
        for tool in self.tools.values():
            try:
                schema = tool.get_schema()
                schemas.append(schema)
            except Exception as e:
                self.logger.error(f"Failed to get schema for tool {tool.get_name()}: {e}")
        return schemas
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """Get tool definitions in LLM-compatible format"""
        tools = []
        for schema in self.get_schemas():
            # OpenAI/Anthropic compatible format
            tool_def = {
                "type": "function",
                "function": {
                    "name": schema.name,
                    "description": schema.description,
                    "parameters": schema.parameters
                }
            }
            tools.append(tool_def)
        return tools


class ToolCallExecutor:
    """Executes tool calls with proper error handling and logging"""
    
    def __init__(self, registry: ToolRegistry, timeout: float = 30.0):
        self.registry = registry
        self.timeout = timeout
        self.logger = logging.getLogger(f"{__name__}.ToolCallExecutor")
    
    async def execute_tool_call(self, tool_call: ToolCall) -> ToolCall:
        """Execute a single tool call"""
        start_time = asyncio.get_event_loop().time()
        tool_call.status = ToolCallStatus.RUNNING
        
        self.logger.info(f"🔧 Executing tool call: {tool_call.name} (ID: {tool_call.id})")
        self.logger.debug(f"Parameters: {tool_call.parameters}")
        
        try:
            # Get the tool
            tool = self.registry.get_tool(tool_call.name)
            if not tool:
                raise ValueError(f"Tool '{tool_call.name}' not found in registry")
            
            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(tool_call.parameters),
                timeout=self.timeout
            )
            
            tool_call.result = result
            tool_call.status = ToolCallStatus.COMPLETED
            tool_call.execution_time = asyncio.get_event_loop().time() - start_time
            
            self.logger.info(f"✅ Tool call completed: {tool_call.name} (success: {result.success})")
            if not result.success:
                self.logger.warning(f"Tool call failed: {result.error_message}")
            
        except asyncio.TimeoutError:
            tool_call.status = ToolCallStatus.TIMEOUT
            tool_call.error = f"Tool call timed out after {self.timeout}s"
            tool_call.execution_time = self.timeout
            self.logger.error(f"⏰ Tool call timeout: {tool_call.name}")
            
        except Exception as e:
            tool_call.status = ToolCallStatus.FAILED
            tool_call.error = str(e)
            tool_call.execution_time = asyncio.get_event_loop().time() - start_time
            self.logger.error(f"❌ Tool call failed: {tool_call.name}, error: {e}")
        
        return tool_call
    
    async def execute_tool_calls(self, tool_calls: List[ToolCall], 
                                parallel: bool = True) -> List[ToolCall]:
        """Execute multiple tool calls"""
        if not tool_calls:
            return []
        
        self.logger.info(f"🚀 Executing {len(tool_calls)} tool calls (parallel: {parallel})")
        
        if parallel:
            # Execute all tool calls in parallel
            tasks = [self.execute_tool_call(tc) for tc in tool_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle any exceptions that occurred
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    tool_calls[i].status = ToolCallStatus.FAILED
                    tool_calls[i].error = str(result)
                    self.logger.error(f"Tool call {tool_calls[i].name} failed with exception: {result}")
        else:
            # Execute tool calls sequentially
            for tool_call in tool_calls:
                await self.execute_tool_call(tool_call)
        
        return tool_calls


class ToolCallManager:
    """High-level manager for tool calling functionality"""
    
    def __init__(self, tools: Optional[List[BaseTool]] = None, 
                 executor_timeout: float = 30.0):
        self.registry = ToolRegistry()
        self.executor = ToolCallExecutor(self.registry, executor_timeout)
        self.logger = logging.getLogger(f"{__name__}.ToolCallManager")
        
        # Register provided tools
        if tools:
            for tool in tools:
                self.register_tool(tool)
    
    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool"""
        self.registry.register_tool(tool)
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """Get tool definitions for LLM"""
        return self.registry.get_tools_for_llm()
    
    def parse_tool_calls_from_llm(self, llm_response: Dict[str, Any]) -> List[ToolCall]:
        """
        Parse tool calls from LLM response
        Supports multiple LLM providers (OpenAI, Anthropic, etc.)
        """
        tool_calls = []
        
        self.logger.info(f"🔍 Parsing tool calls from response structure: {list(llm_response.keys())}")
        
        # Handle OpenRouter/OpenAI API response format
        if "choices" in llm_response:
            if len(llm_response["choices"]) > 0:
                message = llm_response["choices"][0].get("message", {})
                self.logger.info(f"🔍 Found message with keys: {list(message.keys())}")
                
                # Check for tool_calls in the message
                if "tool_calls" in message and message["tool_calls"]:
                    self.logger.info(f"🔧 Found {len(message['tool_calls'])} tool calls in message")
                    for tc in message["tool_calls"]:
                        if tc.get("type") == "function":
                            func = tc.get("function", {})
                            try:
                                parameters = json.loads(func.get("arguments", "{}"))
                                
                                tool_call = ToolCall(
                                    id=tc.get("id", f"call_{len(tool_calls)}"),
                                    name=func["name"],
                                    parameters=parameters
                                )
                                tool_calls.append(tool_call)
                                self.logger.info(f"✅ Parsed tool call: {func['name']} with {len(parameters)} parameters")
                            except json.JSONDecodeError as e:
                                self.logger.error(f"❌ Failed to parse tool call arguments: {e}")
                        else:
                            self.logger.debug(f"⚠️ Skipping non-function tool call: {tc.get('type')}")
                else:
                    self.logger.info("📝 No tool_calls found in message")
                    
                # Log the content for debugging
                content = message.get("content", "")
                if content:
                    self.logger.info(f"📄 Message content preview: {content[:200]}...")
            else:
                self.logger.warning("⚠️ Empty choices array in LLM response")
        
        # Direct OpenAI format (for compatibility)
        elif "tool_calls" in llm_response:
            self.logger.info(f"🔧 Found {len(llm_response['tool_calls'])} tool calls in direct format")
            for tc in llm_response["tool_calls"]:
                if tc["type"] == "function":
                    func = tc["function"]
                    parameters = json.loads(func.get("arguments", "{}"))
                    
                    tool_call = ToolCall(
                        id=tc.get("id", f"call_{len(tool_calls)}"),
                        name=func["name"],
                        parameters=parameters
                    )
                    tool_calls.append(tool_call)
        
        # Anthropic format (tool_use)
        elif "content" in llm_response:
            content = llm_response["content"]
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "tool_use":
                        tool_call = ToolCall(
                            id=item.get("id", f"call_{len(tool_calls)}"),
                            name=item["name"],
                            parameters=item.get("input", {})
                        )
                        tool_calls.append(tool_call)
        
        if len(tool_calls) == 0:
            self.logger.info("📭 No tool calls found in LLM response - LLM chose not to use tools")
        else:
            self.logger.info(f"📥 Successfully parsed {len(tool_calls)} tool calls from LLM response")
            for tc in tool_calls:
                self.logger.info(f"🔧 Tool call: {tc.name} (ID: {tc.id}) with parameters: {list(tc.parameters.keys())}")
        
        return tool_calls
    
    async def execute_tool_calls(self, tool_calls: List[ToolCall], 
                                parallel: bool = True) -> List[ToolCall]:
        """Execute tool calls and return results"""
        return await self.executor.execute_tool_calls(tool_calls, parallel)
    
    def format_tool_results_for_llm(self, tool_calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """Format tool call results for LLM consumption"""
        messages = []
        
        for tc in tool_calls:
            if tc.status == ToolCallStatus.COMPLETED and tc.result:
                # Success case
                result_data = {
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "success": tc.result.success,
                        "data": tc.result.data,
                        "execution_time": tc.execution_time
                    })
                }
                
                if not tc.result.success:
                    result_data["content"] = json.dumps({
                        "success": False,
                        "error": tc.result.error_message,
                        "execution_time": tc.execution_time
                    })
            else:
                # Error case
                result_data = {
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "success": False,
                        "error": tc.error or f"Tool call failed with status: {tc.status.value}",
                        "execution_time": tc.execution_time
                    })
                }
            
            messages.append(result_data)
        
        return messages
    
    def get_tool_usage_stats(self) -> Dict[str, Any]:
        """Get statistics about tool usage"""
        return {
            "registered_tools": len(self.registry.tools),
            "tool_names": self.registry.list_tools(),
            "executor_timeout": self.executor.timeout
        }
    
    def create_tool_calling_prompt(self, base_prompt: str, 
                                  include_examples: bool = True) -> str:
        """Create enhanced prompt that explains available tools"""
        tools_info = []
        
        for tool_name in self.registry.list_tools():
            tool = self.registry.get_tool(tool_name)
            if tool:
                tool_info = f"- **{tool_name}**: {tool.get_description()}"
                
                if include_examples:
                    examples = tool.get_usage_examples()
                    if examples:
                        tool_info += f"\n  Example: {examples[0]}"
                
                tools_info.append(tool_info)
        
        if tools_info:
            tools_section = f"""

AVAILABLE TOOLS:
You have access to the following tools for analysis and exploit generation:

{chr(10).join(tools_info)}

When you need to analyze contracts, check liquidity, or plan sophisticated attacks, 
use these tools to gather real-time information before generating exploit code.
"""
            return base_prompt + tools_section
        
        return base_prompt