#!/usr/bin/env python3
"""
Extract Contract Source Code from A1 System Run
This script extracts the original and sanitized source code from a completed run
to analyze what functions the LLM actually sees.
"""

import json
import asyncio
import sys
from pathlib import Path
from a1_system.config import Config
from a1_system.tools.source_fetcher import SourceCodeFetcher
from a1_system.tools.code_sanitizer import CodeSanitizerTool

async def extract_contract_source():
    """Extract and save contract source code"""
    
    # Target contract from the run
    contract_address = "0x418C24191aE947A78C99fDc0e45a1f96Afb254BE"
    chain_id = 1
    block_number = 15767837
    
    print(f"🔍 Extracting source code for {contract_address}")
    
    # Initialize config and tools
    config = Config.from_env()
    source_fetcher = SourceCodeFetcher(config)
    code_sanitizer = CodeSanitizerTool(config)
    
    # Fetch source code
    print("📥 Fetching source code...")
    source_result = await source_fetcher.execute({
        "chain_id": chain_id,
        "contract_address": contract_address,
        "block_number": block_number
    })
    
    if not source_result.success:
        print(f"❌ Failed to fetch source code: {source_result.error_message}")
        return
    
    source_code = source_result.data.get("source_code", "")
    contract_name = source_result.data.get("contract_name", "Unknown")
    
    print(f"✅ Source code fetched: {len(source_code)} characters")
    print(f"📋 Contract name: {contract_name}")
    
    # Sanitize source code
    print("🧹 Sanitizing source code...")
    sanitizer_result = await code_sanitizer.execute({
        "source_code": source_code
    })
    
    if not sanitizer_result.success:
        print(f"❌ Failed to sanitize code: {sanitizer_result.error_message}")
        return
    
    sanitized_code = sanitizer_result.data.get("sanitized_code", "")
    
    print(f"✅ Sanitized code: {len(sanitized_code)} characters")
    
    # Save to files
    output_dir = Path("contract_analysis")
    output_dir.mkdir(exist_ok=True)
    
    # Save original source code
    original_file = output_dir / f"{contract_name}_original.sol"
    original_file.write_text(source_code)
    print(f"💾 Original source code saved to: {original_file}")
    
    # Save sanitized source code  
    sanitized_file = output_dir / f"{contract_name}_sanitized.sol"
    sanitized_file.write_text(sanitized_code)
    print(f"💾 Sanitized source code saved to: {sanitized_file}")
    
    # Save contract metadata
    metadata = {
        "contract_address": contract_address,
        "contract_name": contract_name,
        "chain_id": chain_id,
        "block_number": block_number,
        "original_length": len(source_code),
        "sanitized_length": len(sanitized_code),
        "reduction_percent": sanitizer_result.data.get("reduction_percent", 0),
        "compiler_version": source_result.data.get("compiler_version", "Unknown"),
        "verification_status": source_result.data.get("verification_status", "Unknown")
    }
    
    metadata_file = output_dir / f"{contract_name}_metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2))
    print(f"💾 Contract metadata saved to: {metadata_file}")
    
    # Analyze function signatures
    print("\n🔍 Analyzing function signatures...")
    
    # Extract function signatures from source code
    import re
    
    # Find all function definitions
    function_pattern = r'function\s+(\w+)\s*\([^)]*\)\s*(?:external|public|internal|private)?\s*(?:pure|view|payable)?\s*(?:returns\s*\([^)]*\))?\s*{'
    functions = re.findall(function_pattern, source_code, re.IGNORECASE)
    
    print(f"📋 Functions found in original source:")
    for func in functions:
        print(f"  - {func}()")
    
    # Check if mint function exists
    mint_functions = [f for f in functions if 'mint' in f.lower()]
    if mint_functions:
        print(f"🎯 MINT functions found: {mint_functions}")
    else:
        print("❌ No mint functions found in source code")
    
    # Look for the exact function signature that was called
    print(f"\n🔍 Looking for function signature 1249c58b (mint with no params)...")
    
    # Check if parameterless mint exists
    parameterless_mint_pattern = r'function\s+mint\s*\(\s*\)'
    parameterless_mint = re.search(parameterless_mint_pattern, source_code, re.IGNORECASE)
    
    if parameterless_mint:
        print("✅ Found parameterless mint() function")
    else:
        print("❌ No parameterless mint() function found")
        
        # Look for mint functions with parameters
        mint_with_params_pattern = r'function\s+mint\s*\([^)]+\)'
        mint_with_params = re.findall(mint_with_params_pattern, source_code, re.IGNORECASE)
        
        if mint_with_params:
            print(f"🎯 Found mint functions with parameters:")
            for match in mint_with_params:
                print(f"  - {match}")
        else:
            print("❌ No mint functions found at all")
    
    print(f"\n✅ Analysis complete! Check the {output_dir} directory for extracted files.")

if __name__ == "__main__":
    asyncio.run(extract_contract_source()) 