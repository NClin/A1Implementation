"""
Base classes for A1 tools with tool calling support
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
import logging
import inspect
import json


@dataclass
class ToolParameter:
    """Tool parameter definition for schema generation"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None


@dataclass
class ToolResult:
    """Standard result format for all tools"""
    success: bool
    data: Dict[str, Any]
    error_message: Optional[str] = None
    execution_time: float = 0.0
    tool_name: str = ""


@dataclass
class ToolSchema:
    """Tool schema for LLM tool calling"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema format


class BaseTool(ABC):
    """Base class for all A1 tools with tool calling support"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Execute the tool with given parameters
        
        Args:
            params: Tool-specific parameters
            
        Returns:
            ToolResult with success status and data
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get tool name"""
        pass
    
    @abstractmethod
    def get_description(self) -> str:
        """Get tool description"""
        pass
    
    def get_parameters(self) -> List[ToolParameter]:
        """
        Get tool parameters for schema generation
        Override this method to define tool-specific parameters
        
        Returns:
            List of ToolParameter definitions
        """
        return []
    
    def get_schema(self) -> ToolSchema:
        """
        Generate JSON schema for this tool for LLM tool calling
        
        Returns:
            ToolSchema compatible with OpenAI/Anthropic tool calling
        """
        parameters = self.get_parameters()
        
        # Build JSON Schema
        properties = {}
        required = []
        
        for param in parameters:
            prop_schema = {
                "type": param.type,
                "description": param.description
            }
            
            if param.enum:
                prop_schema["enum"] = param.enum
            
            if param.default is not None:
                prop_schema["default"] = param.default
            
            properties[param.name] = prop_schema
            
            if param.required:
                required.append(param.name)
        
        schema_params = {
            "type": "object",
            "properties": properties
        }
        
        if required:
            schema_params["required"] = required
        
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=schema_params
        )
    
    def get_usage_examples(self) -> List[Dict[str, Any]]:
        """
        Get usage examples for this tool
        Override this method to provide examples for the LLM
        
        Returns:
            List of example parameter dictionaries
        """
        return []
    
    def _create_result(
        self,
        success: bool,
        data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        execution_time: float = 0.0
    ) -> ToolResult:
        """Helper to create standardized ToolResult"""
        return ToolResult(
            success=success,
            data=data or {},
            error_message=error_message,
            execution_time=execution_time,
            tool_name=self.get_name()
        ) 