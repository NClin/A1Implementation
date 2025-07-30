"""
Code Analysis Tool for LLM reasoning
"""

import re
import ast
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .base import BaseTool, ToolResult, ToolParameter


@dataclass
class FunctionInfo:
    name: str
    modifiers: List[str]
    parameters: List[str]
    visibility: str
    state_mutability: str
    body: str


@dataclass 
class StateVariableInfo:
    name: str
    type: str
    visibility: str
    initial_value: Optional[str]


class CodeAnalysisTool(BaseTool):
    """
    Tool for analyzing Solidity code patterns, function interactions, 
    and potential vulnerability surfaces
    """
    
    def get_name(self) -> str:
        return "code_analysis_tool"
    
    def get_description(self) -> str:
        return "Analyze Solidity contract code for functions, state variables, modifiers, and interaction patterns"
    
    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="source_code", 
                type="string", 
                description="Solidity source code to analyze"
            ),
            ToolParameter(
                name="analysis_type",
                type="string", 
                description="Type of analysis: 'functions', 'state_vars', 'modifiers', 'interactions', 'math_ops', 'access_control'",
                enum=["functions", "state_vars", "modifiers", "interactions", "math_ops", "access_control"]
            ),
            ToolParameter(
                name="focus_function",
                type="string",
                description="Specific function name to analyze in detail (optional)",
                required=False
            )
        ]
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """Analyze Solidity code based on requested analysis type"""
        
        try:
            source_code = params["source_code"]
            analysis_type = params["analysis_type"]
            focus_function = params.get("focus_function")
            
            if analysis_type == "functions":
                return await self._analyze_functions(source_code, focus_function)
            elif analysis_type == "state_vars":
                return await self._analyze_state_variables(source_code)
            elif analysis_type == "modifiers":
                return await self._analyze_modifiers(source_code)
            elif analysis_type == "interactions":
                return await self._analyze_interactions(source_code)
            elif analysis_type == "math_ops":
                return await self._analyze_math_operations(source_code)
            elif analysis_type == "access_control":
                return await self._analyze_access_control(source_code)
            else:
                return ToolResult(
                    success=False,
                    error_message=f"Unknown analysis type: {analysis_type}"
                )
                
        except Exception as e:
            return ToolResult(
                success=False,
                error_message=f"Code analysis failed: {str(e)}"
            )
    
    async def _analyze_functions(self, source_code: str, focus_function: Optional[str] = None) -> ToolResult:
        """Extract and analyze function definitions"""
        
        # Pattern to match function definitions
        function_pattern = r'function\s+(\w+)\s*\([^)]*\)\s*((?:public|private|internal|external)?\s*(?:pure|view|payable)?\s*(?:override)?\s*(?:returns\s*\([^)]*\))?\s*)(?:(\w+(?:\([^)]*\))?)\s*)*\s*\{'
        
        functions = []
        
        # Find all function matches
        for match in re.finditer(function_pattern, source_code, re.MULTILINE | re.DOTALL):
            func_name = match.group(1)
            
            # Skip if we're focusing on a specific function and this isn't it
            if focus_function and func_name != focus_function:
                continue
                
            # Extract function body (basic approach)
            start_pos = match.end()
            brace_count = 1
            end_pos = start_pos
            
            for i, char in enumerate(source_code[start_pos:], start_pos):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i
                        break
            
            func_body = source_code[start_pos:end_pos] if end_pos > start_pos else ""
            
            # Extract modifiers
            modifiers = self._extract_modifiers(match.group(0))
            
            # Determine visibility and state mutability
            visibility = self._extract_visibility(match.group(2))
            state_mutability = self._extract_state_mutability(match.group(2))
            
            # Extract parameters
            param_match = re.search(r'function\s+\w+\s*\(([^)]*)\)', match.group(0))
            parameters = param_match.group(1).strip() if param_match else ""
            
            functions.append({
                "name": func_name,
                "visibility": visibility,
                "state_mutability": state_mutability,
                "modifiers": modifiers,
                "parameters": parameters,
                "body_preview": func_body[:200] + "..." if len(func_body) > 200 else func_body,
                "body_length": len(func_body),
                "calls_external": bool(re.search(r'\.call\(|\.delegatecall\(|\.staticcall\(', func_body)),
                "has_loops": bool(re.search(r'\bfor\s*\(|\bwhile\s*\(', func_body)),
                "has_math": bool(re.search(r'[\+\-\*\/]|\b(?:add|sub|mul|div)\b', func_body)),
                "modifies_state": bool(re.search(r'=(?!=)', func_body)) and state_mutability not in ["pure", "view"],
                "has_transfers": bool(re.search(r'\.transfer\(|\.send\(|transferFrom|safeTransfer', func_body))
            })
        
        return ToolResult(
            success=True,
            data={
                "functions": functions,
                "total_functions": len(functions),
                "focus_function": focus_function
            }
        )
    
    async def _analyze_state_variables(self, source_code: str) -> ToolResult:
        """Analyze state variable declarations"""
        
        # Pattern for state variables (simplified)
        state_var_pattern = r'^\s*((?:public|private|internal)?\s*)(?:constant\s+)?(\w+)(?:\[\w*\])*\s+(public|private|internal)?\s*(\w+)(?:\s*=\s*([^;]+))?;'
        
        variables = []
        
        for match in re.finditer(state_var_pattern, source_code, re.MULTILINE):
            visibility = match.group(1).strip() or match.group(3) or "internal"
            var_type = match.group(2)
            var_name = match.group(4)
            initial_value = match.group(5)
            
            variables.append({
                "name": var_name,
                "type": var_type,
                "visibility": visibility,
                "initial_value": initial_value.strip() if initial_value else None,
                "is_mapping": "mapping" in var_type,
                "is_array": "[" in var_type,
                "is_constant": "constant" in match.group(0)
            })
        
        return ToolResult(
            success=True,
            data={
                "state_variables": variables,
                "total_variables": len(variables)
            }
        )
    
    async def _analyze_modifiers(self, source_code: str) -> ToolResult:
        """Analyze modifier definitions and usage"""
        
        # Pattern for modifier definitions
        modifier_pattern = r'modifier\s+(\w+)(?:\([^)]*\))?\s*\{([^}]*)\}'
        
        modifiers = []
        
        for match in re.finditer(modifier_pattern, source_code, re.DOTALL):
            modifier_name = match.group(1)
            modifier_body = match.group(2)
            
            modifiers.append({
                "name": modifier_name,
                "body": modifier_body.strip(),
                "has_require": "require(" in modifier_body,
                "has_revert": "revert(" in modifier_body,
                "has_underscore": "_;" in modifier_body,
                "checks_msg_sender": "msg.sender" in modifier_body,
                "checks_balance": "balance" in modifier_body.lower()
            })
        
        # Find modifier usage in functions
        modifier_usage = {}
        for modifier in modifiers:
            usage_pattern = f'\\b{modifier["name"]}\\b'
            usage_count = len(re.findall(usage_pattern, source_code))
            modifier_usage[modifier["name"]] = usage_count - 1  # Subtract definition
        
        return ToolResult(
            success=True,
            data={
                "modifiers": modifiers,
                "modifier_usage": modifier_usage,
                "total_modifiers": len(modifiers)
            }
        )
    
    async def _analyze_interactions(self, source_code: str) -> ToolResult:
        """Analyze external calls and contract interactions"""
        
        external_calls = []
        
        # Patterns for different types of external calls
        patterns = {
            "low_level_call": r'\.call\s*\(',
            "delegate_call": r'\.delegatecall\s*\(',
            "static_call": r'\.staticcall\s*\(',
            "transfer": r'\.transfer\s*\(',
            "send": r'\.send\s*\(',
            "interface_call": r'I\w+\([^)]+\)\.\w+\(',
            "contract_creation": r'new\s+\w+\s*\('
        }
        
        for call_type, pattern in patterns.items():
            matches = re.finditer(pattern, source_code)
            for match in matches:
                # Get context around the call
                start = max(0, match.start() - 50)
                end = min(len(source_code), match.end() + 50)
                context = source_code[start:end]
                
                external_calls.append({
                    "type": call_type,
                    "position": match.start(),
                    "context": context.strip(),
                    "has_return_check": bool(re.search(r'\(bool\s+\w+,|\(bool\s+success', context))
                })
        
        return ToolResult(
            success=True,
            data={
                "external_calls": external_calls,
                "total_external_calls": len(external_calls),
                "call_types": list(set(call["type"] for call in external_calls))
            }
        )
    
    async def _analyze_math_operations(self, source_code: str) -> ToolResult:
        """Analyze mathematical operations and potential overflow/underflow"""
        
        math_operations = []
        
        # Patterns for math operations
        patterns = {
            "addition": r'(\w+)\s*\+\s*(\w+)',
            "subtraction": r'(\w+)\s*\-\s*(\w+)',
            "multiplication": r'(\w+)\s*\*\s*(\w+)',
            "division": r'(\w+)\s*\/\s*(\w+)',
            "safe_math_add": r'\.add\s*\(',
            "safe_math_sub": r'\.sub\s*\(',
            "safe_math_mul": r'\.mul\s*\(',
            "safe_math_div": r'\.div\s*\('
        }
        
        for op_type, pattern in patterns.items():
            matches = re.finditer(pattern, source_code)
            for match in matches:
                context_start = max(0, match.start() - 30)
                context_end = min(len(source_code), match.end() + 30)
                context = source_code[context_start:context_end]
                
                math_operations.append({
                    "type": op_type,
                    "position": match.start(),
                    "context": context.strip(),
                    "is_safe_math": "safe_math" in op_type,
                    "in_loop": self._is_in_loop(source_code, match.start()),
                    "in_condition": self._is_in_condition(source_code, match.start())
                })
        
        return ToolResult(
            success=True,
            data={
                "math_operations": math_operations,
                "total_operations": len(math_operations),
                "safe_math_usage": len([op for op in math_operations if op["is_safe_math"]]),
                "unsafe_operations": len([op for op in math_operations if not op["is_safe_math"]])
            }
        )
    
    async def _analyze_access_control(self, source_code: str) -> ToolResult:
        """Analyze access control patterns"""
        
        access_controls = []
        
        # Look for access control patterns
        patterns = {
            "only_owner": r'onlyOwner',
            "require_owner": r'require\s*\([^)]*owner[^)]*\)',
            "msg_sender_check": r'require\s*\([^)]*msg\.sender[^)]*\)',
            "role_check": r'require\s*\([^)]*hasRole[^)]*\)',
            "modifier_usage": r'\b\w+\s*(?:\([^)]*\))?\s*(?:public|external|internal|private)'
        }
        
        for control_type, pattern in patterns.items():
            matches = re.finditer(pattern, source_code)
            for match in matches:
                context_start = max(0, match.start() - 40)
                context_end = min(len(source_code), match.end() + 40)
                context = source_code[context_start:context_end]
                
                access_controls.append({
                    "type": control_type,
                    "position": match.start(),
                    "context": context.strip()
                })
        
        return ToolResult(
            success=True,
            data={
                "access_controls": access_controls,
                "total_controls": len(access_controls),
                "control_types": list(set(ac["type"] for ac in access_controls))
            }
        )
    
    def _extract_modifiers(self, function_def: str) -> List[str]:
        """Extract modifiers from function definition"""
        # Look for modifier names (simplified)
        modifier_matches = re.findall(r'\b([a-zA-Z_]\w*)\s*(?:\([^)]*\))?\s*(?=\{)', function_def)
        # Filter out keywords
        keywords = {'public', 'private', 'internal', 'external', 'pure', 'view', 'payable', 'override', 'returns'}
        return [m for m in modifier_matches if m not in keywords]
    
    def _extract_visibility(self, modifiers_str: str) -> str:
        """Extract visibility from modifiers string"""
        for visibility in ['public', 'private', 'internal', 'external']:
            if visibility in modifiers_str:
                return visibility
        return 'internal'  # default
    
    def _extract_state_mutability(self, modifiers_str: str) -> str:
        """Extract state mutability from modifiers string"""
        for mutability in ['pure', 'view', 'payable']:
            if mutability in modifiers_str:
                return mutability
        return 'nonpayable'  # default
    
    def _is_in_loop(self, source_code: str, position: int) -> bool:
        """Check if position is inside a loop"""
        # Simplified check - look backwards for loop keywords
        preceding_code = source_code[max(0, position-500):position]
        return bool(re.search(r'\b(?:for|while)\s*\([^{]*$', preceding_code))
    
    def _is_in_condition(self, source_code: str, position: int) -> bool:
        """Check if position is inside a condition"""
        # Simplified check - look backwards for if/require
        preceding_code = source_code[max(0, position-200):position]
        return bool(re.search(r'\b(?:if|require)\s*\([^{]*$', preceding_code))