"""
Enhanced LLM Client with Tool Calling Support
Extends the base LLM client to support tool calling functionality
"""

import json
import time
import logging
from typing import Dict, Any, List, Optional, Union
import httpx

from .llm_client import LLMClient
from .tool_calling import ToolCallManager, ToolCall, ToolCallStatus


class ToolCallingLLMClient(LLMClient):
    """Enhanced LLM client with tool calling capabilities"""
    
    def __init__(self, config, tool_manager: Optional[ToolCallManager] = None):
        super().__init__(config)
        self.tool_manager = tool_manager
        self.logger = logging.getLogger(f"{__name__}.ToolCallingLLMClient")
        
        # Tool calling specific settings
        self.max_tool_iterations = 3  # Maximum back-and-forth with tools
        self.enable_parallel_tools = True
    
    async def generate_with_tools(self, system_prompt: str, user_prompt: str,
                                 model: Optional[str] = None,
                                 enable_tools: bool = True) -> Dict[str, Any]:
        """
        Generate response with tool calling support
        
        Args:
            system_prompt: System prompt for the LLM
            user_prompt: User prompt
            model: Model to use (defaults to config default)
            enable_tools: Whether to enable tool calling
            
        Returns:
            Dict containing response, tool calls, and metadata
        """
        if not enable_tools or not self.tool_manager:
            # Fall back to standard generation
            response = await self.generate(system_prompt, user_prompt, model)
            return {
                "response": response,
                "tool_calls": [],
                "iterations": 1,
                "total_cost": self.total_cost
            }
        
        model = model or self.config.default_model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        all_tool_calls = []
        iteration = 0
        total_cost = 0.0
        
        self.logger.info(f"🚀 Starting tool-calling generation (max iterations: {self.max_tool_iterations})")
        
        for iteration in range(self.max_tool_iterations):
            self.logger.info(f"🔄 Tool calling iteration {iteration + 1}/{self.max_tool_iterations}")
            
            # Prepare tools for this iteration
            tools = self.tool_manager.get_tools_for_llm() if iteration == 0 else None
            
            # Make LLM request
            start_time = time.time()
            llm_response = await self._make_tool_calling_request(messages, model, tools)
            request_time = time.time() - start_time
            
            # Track cost
            iteration_cost = self._calculate_cost(llm_response, model)
            total_cost += iteration_cost
            self.total_cost += iteration_cost
            
            self.logger.info(f"💰 LLM request cost: ${iteration_cost:.4f}, time: {request_time:.1f}s")
            
            # Log raw response structure for debugging
            self.logger.info(f"🔍 Raw LLM response keys: {list(llm_response.keys())}")
            if "choices" in llm_response and len(llm_response["choices"]) > 0:
                message = llm_response["choices"][0].get("message", {})
                self.logger.info(f"🔍 Message keys: {list(message.keys())}")
                if "tool_calls" in message:
                    self.logger.info(f"🎯 LLM made {len(message['tool_calls'])} tool calls!")
                else:
                    self.logger.info("🤔 LLM response contains no tool calls")
            
            # Parse response
            response_content = self._extract_content(llm_response)
            tool_calls = self.tool_manager.parse_tool_calls_from_llm(llm_response)
            
            if not tool_calls:
                # No more tool calls - we're done
                self.logger.info("✅ No tool calls requested - generation complete")
                return {
                    "response": response_content,
                    "tool_calls": all_tool_calls,
                    "iterations": iteration + 1,
                    "total_cost": total_cost
                }
            
            self.logger.info(f"🔧 Executing {len(tool_calls)} tool calls")
            
            # Execute tool calls
            executed_calls = await self.tool_manager.execute_tool_calls(
                tool_calls, parallel=self.enable_parallel_tools
            )
            all_tool_calls.extend(executed_calls)
            
            # Add assistant message with tool calls
            messages.append({
                "role": "assistant", 
                "content": response_content,
                "tool_calls": [self._format_tool_call_for_message(tc) for tc in tool_calls]
            })
            
            # Add tool results as messages
            for tc in executed_calls:
                tool_result = self._format_tool_result_for_message(tc)
                messages.append(tool_result)
            
            # Log tool call results
            successful_calls = [tc for tc in executed_calls if tc.status == ToolCallStatus.COMPLETED]
            failed_calls = [tc for tc in executed_calls if tc.status != ToolCallStatus.COMPLETED]
            
            self.logger.info(f"📊 Tool calls: {len(successful_calls)} successful, {len(failed_calls)} failed")
            
            # If all tools failed, break the loop
            if len(failed_calls) == len(executed_calls):
                self.logger.warning("❌ All tool calls failed - stopping iterations")
                break
        
        # Final LLM call to generate response based on tool results
        # Add explicit instruction to generate complete exploit contract
        messages.append({
            "role": "user",
            "content": """Based on the tool results above, please provide a COMPLETE exploit contract that implements the vulnerability discovered. Your response must include:

1. Complete Solidity contract code with all necessary imports
2. The contract must contain a function named 'exploit()' or 'exploit() external'
3. The exploit should be ready to compile and execute

Format your response with the complete contract in a ```solidity code block.

IMPORTANT: Do not just provide analysis - provide the actual complete working exploit contract code."""
        })
        
        self.logger.info("🎯 Making final LLM call with tool results and explicit exploit generation request")
        final_response = await self._make_tool_calling_request(messages, model, tools=None)
        final_cost = self._calculate_cost(final_response, model)
        total_cost += final_cost
        self.total_cost += final_cost
        
        final_content = self._extract_content(final_response)
        
        return {
            "response": final_content,
            "tool_calls": all_tool_calls,
            "iterations": iteration + 1,
            "total_cost": total_cost
        }
    
    async def _make_tool_calling_request(self, messages: List[Dict[str, Any]], 
                                       model: str, tools: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Make HTTP request to LLM with tool calling support"""
        
        # Prepare request payload
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        
        # Add tools if provided
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"  # Let LLM decide when to use tools
        
        headers = {
            "Authorization": f"Bearer {self.config.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/anthropics/a1-system",
            "X-Title": "A1 Security Analysis System"
        }
        
        self.logger.info(f"🌐 Making tool-calling request to {model}")
        self.logger.info(f"Tools enabled: {tools is not None}")
        if tools:
            self.logger.info(f"🔧 Available tools: {[t['function']['name'] for t in tools]}")
            for tool in tools:
                func = tool['function']
                params = list(func['parameters']['properties'].keys())
                self.logger.info(f"   📋 {func['name']}: {params}")
        else:
            self.logger.info("🚫 No tools provided to LLM")
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            return response.json()
    
    def _extract_content(self, llm_response: Dict[str, Any]) -> str:
        """Extract text content from LLM response"""
        if "choices" in llm_response and len(llm_response["choices"]) > 0:
            message = llm_response["choices"][0].get("message", {})
            return message.get("content", "")
        return ""
    
    def _format_tool_call_for_message(self, tool_call: ToolCall) -> Dict[str, Any]:
        """Format tool call for message history"""
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": json.dumps(tool_call.parameters)
            }
        }
    
    def _format_tool_result_for_message(self, tool_call: ToolCall) -> Dict[str, Any]:
        """Format tool result for message history"""
        if tool_call.status == ToolCallStatus.COMPLETED and tool_call.result:
            content = json.dumps({
                "success": tool_call.result.success,
                "data": tool_call.result.data,
                "execution_time": tool_call.execution_time
            })
            
            if not tool_call.result.success:
                content = json.dumps({
                    "success": False,
                    "error": tool_call.result.error_message,
                    "execution_time": tool_call.execution_time
                })
        else:
            content = json.dumps({
                "success": False,
                "error": tool_call.error or f"Tool call failed: {tool_call.status.value}",
                "execution_time": tool_call.execution_time
            })
        
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": content
        }
    
    def _calculate_cost(self, response: Dict[str, Any], model: str) -> float:
        """Calculate cost for this request (reuse parent implementation)"""
        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        # Use parent class pricing logic
        if model in self.model_pricing:
            pricing = self.model_pricing[model]
            cost = (prompt_tokens * pricing["input"]) + (completion_tokens * pricing["output"])
            return cost / 1000000  # Convert from per-million to per-token
        else:
            # Use default pricing
            return (prompt_tokens * 0.000015) + (completion_tokens * 0.000015)
    
    def set_tool_calling_config(self, max_iterations: int = 3, 
                               parallel_tools: bool = True) -> None:
        """Configure tool calling behavior"""
        self.max_tool_iterations = max_iterations
        self.enable_parallel_tools = parallel_tools
        self.logger.info(f"🔧 Tool calling config: max_iterations={max_iterations}, parallel={parallel_tools}")
    
    def get_tool_calling_stats(self) -> Dict[str, Any]:
        """Get tool calling statistics"""
        stats = {
            "max_iterations": self.max_tool_iterations,
            "parallel_enabled": self.enable_parallel_tools,
            "total_cost": self.total_cost
        }
        
        if self.tool_manager:
            stats.update(self.tool_manager.get_tool_usage_stats())
        
        return stats