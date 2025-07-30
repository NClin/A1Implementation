"""
Code Sanitizer Tool - Removes non-essential elements for focused analysis
"""

import re
import time
from typing import Dict, Any
from .base import BaseTool, ToolResult


class CodeSanitizerTool(BaseTool):
    """
    Tool for cleaning smart contract source code for analysis
    
    Features:
    - Remove comments (single-line and multi-line)
    - Remove empty lines and excessive whitespace
    - Remove import statements and pragmas
    - Focus on contract logic only
    """
    
    def get_name(self) -> str:
        return "code_sanitizer"
    
    def get_description(self) -> str:
        return "Removes comments, imports, and non-essential code elements for focused analysis"
    
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """
        Sanitize Solidity source code
        
        Args:
            params: {
                "source_code": str - Raw Solidity source code
                "keep_imports": bool - Whether to keep import statements (default: False)
                "keep_pragmas": bool - Whether to keep pragma statements (default: False)
            }
        
        Returns:
            ToolResult with sanitized code
        """
        
        start_time = time.time()
        
        try:
            source_code = params.get("source_code", "")
            keep_imports = params.get("keep_imports", False)
            keep_pragmas = params.get("keep_pragmas", False)
            
            if not source_code:
                return ToolResult(
                    success=False,
                    data={},
                    error_message="No source code provided",
                    tool_name=self.get_name()
                )
            
            # Sanitize the code
            sanitized = self._sanitize_solidity(source_code, keep_imports, keep_pragmas)
            
            # Calculate reduction statistics
            original_lines = len(source_code.splitlines())
            sanitized_lines = len(sanitized.splitlines())
            reduction_percent = ((original_lines - sanitized_lines) / original_lines) * 100 if original_lines > 0 else 0
            
            execution_time = time.time() - start_time
            
            self.logger.info(f"Code sanitized: {original_lines} → {sanitized_lines} lines ({reduction_percent:.1f}% reduction)")
            
            return ToolResult(
                success=True,
                data={
                    "sanitized_code": sanitized,
                    "original_lines": original_lines,
                    "sanitized_lines": sanitized_lines,
                    "reduction_percent": reduction_percent,
                    "removed_imports": not keep_imports,
                    "removed_pragmas": not keep_pragmas
                },
                execution_time=execution_time,
                tool_name=self.get_name()
            )
            
        except Exception as e:
            self.logger.error(f"Code sanitization failed: {str(e)}")
            return ToolResult(
                success=False,
                data={},
                error_message=f"Sanitization error: {str(e)}",
                execution_time=time.time() - start_time,
                tool_name=self.get_name()
            )
    
    def _sanitize_solidity(self, source_code: str, keep_imports: bool, keep_pragmas: bool) -> str:
        """
        Perform the actual sanitization of Solidity code
        """
        
        lines = source_code.splitlines()
        sanitized_lines = []
        
        in_multiline_comment = False
        brace_depth = 0
        
        for line in lines:
            original_line = line
            
            # Handle multi-line comments
            if in_multiline_comment:
                if "*/" in line:
                    # End of multi-line comment
                    line = line[line.index("*/") + 2:]
                    in_multiline_comment = False
                else:
                    # Skip entire line (still in comment)
                    continue
            
            # Check for start of multi-line comment
            if "/*" in line:
                comment_start = line.index("/*")
                if "*/" in line[comment_start:]:
                    # Single-line multi-line comment
                    comment_end = line.index("*/", comment_start) + 2
                    line = line[:comment_start] + line[comment_end:]
                else:
                    # Multi-line comment starts
                    line = line[:comment_start]
                    in_multiline_comment = True
            
            # Remove single-line comments
            if "//" in line:
                # Make sure it's not in a string literal
                in_string = False
                quote_char = None
                for i, char in enumerate(line):
                    if char in ['"', "'"] and (i == 0 or line[i-1] != "\\"):
                        if not in_string:
                            in_string = True
                            quote_char = char
                        elif char == quote_char:
                            in_string = False
                    elif char == "/" and i < len(line) - 1 and line[i+1] == "/" and not in_string:
                        line = line[:i]
                        break
            
            # Strip whitespace
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Handle imports
            if line.startswith("import ") and not keep_imports:
                continue
            
            # Handle pragmas
            if line.startswith("pragma ") and not keep_pragmas:
                continue
            
            # Handle SPDX license identifiers
            if line.startswith("// SPDX-License-Identifier"):
                continue
            
            # Skip pure comment lines that might have survived
            if line.startswith("//") or line.startswith("/*"):
                continue
            
            # Add the cleaned line
            sanitized_lines.append(line)
        
        return "\n".join(sanitized_lines)
    
    def _is_essential_line(self, line: str) -> bool:
        """
        Determine if a line contains essential contract logic
        """
        
        line = line.strip()
        
        if not line:
            return False
        
        # Essential keywords that indicate contract logic
        essential_keywords = [
            "contract ", "interface ", "library ",
            "function ", "modifier ", "constructor",
            "mapping", "struct", "enum", "event",
            "require(", "assert(", "revert(",
            "if (", "for (", "while (", "do {",
            "msg.sender", "msg.value", "block.",
            "address(", "uint", "int", "bool",
            "public", "private", "internal", "external",
            "view", "pure", "payable", "nonReentrant"
        ]
        
        # Check if line contains essential keywords
        for keyword in essential_keywords:
            if keyword in line:
                return True
        
        # Check for variable assignments and operations
        if "=" in line and not line.startswith("//"):
            return True
        
        # Check for function calls
        if "(" in line and ")" in line and not line.startswith("//"):
            return True
        
        return False
    
    def preview_changes(self, source_code: str) -> Dict[str, Any]:
        """
        Preview what would be removed without actually sanitizing
        """
        
        lines = source_code.splitlines()
        preview = {
            "original_lines": len(lines),
            "comments_removed": 0,
            "empty_lines_removed": 0,
            "imports_removed": 0,
            "pragmas_removed": 0,
            "example_removed_lines": []
        }
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            if not stripped:
                preview["empty_lines_removed"] += 1
            elif stripped.startswith("//") or "/*" in stripped:
                preview["comments_removed"] += 1
                if len(preview["example_removed_lines"]) < 3:
                    preview["example_removed_lines"].append(f"Line {i+1}: {line[:60]}...")
            elif stripped.startswith("import "):
                preview["imports_removed"] += 1
            elif stripped.startswith("pragma "):
                preview["pragmas_removed"] += 1
        
        preview["estimated_final_lines"] = (
            preview["original_lines"] -
            preview["comments_removed"] -
            preview["empty_lines_removed"] -
            preview["imports_removed"] -
            preview["pragmas_removed"]
        )
        
        return preview 