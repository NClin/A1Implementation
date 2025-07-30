#!/usr/bin/env python3
"""
A1 Smart Contract Security Analysis Tool
Main entry point for defensive vulnerability analysis

Usage:
    python main.py --chain 1 --address 0x123... --block 18000000
    python main.py --config config.yaml --target-list contracts.txt
"""

import asyncio
import argparse
import logging
import json
import sys
from pathlib import Path
from typing import List, Dict, Any

from a1_system import A1Agent, Config
from a1_system.agent import AnalysisResult


def setup_logging(level: str = "INFO", log_file: str = "a1_analysis.log"):
    """Configure logging for the application"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file)
        ]
    )


async def analyze_single_contract(
    agent: A1Agent,
    chain_id: int,
    contract_address: str,
    block_number: int = None
) -> AnalysisResult:
    """Analyze a single smart contract"""
    
    logger = logging.getLogger(__name__)
    
    logger.info(f"Starting analysis of {contract_address} on chain {chain_id}")
    
    if block_number:
        logger.info(f"Using historical block: {block_number}")
    
    try:
        result = await agent.analyze_contract(
            chain_id=chain_id,
            contract_address=contract_address,
            block_number=block_number
        )
        
        # Log results
        if result.success and result.profitable:
            logger.info(f"🚨 VULNERABILITY FOUND!")
            logger.info(f"   Revenue: {result.revenue_eth:.4f} ETH (${result.revenue_usd:.2f})")
            logger.info(f"   Type: {result.vulnerability_type}")
            logger.info(f"   Iterations: {result.iterations}")
            logger.info(f"   Cost: ${result.total_cost:.2f}")
            logger.info(f"   Time: {result.execution_time:.1f}s")
        elif result.success:
            logger.info(f"✅ Analysis complete - No profitable vulnerabilities found")
            logger.info(f"   Iterations: {result.iterations}")
            logger.info(f"   Cost: ${result.total_cost:.2f}")
        else:
            logger.error(f"❌ Analysis failed: {result.error_message}")
        
        return result
        
    except Exception as e:
        logger.error(f"Analysis exception: {str(e)}")
        raise


async def analyze_contract_list(
    agent: A1Agent,
    contract_list: List[Dict[str, Any]]
) -> List[AnalysisResult]:
    """Analyze multiple contracts"""
    
    logger = logging.getLogger(__name__)
    results = []
    
    for i, contract_info in enumerate(contract_list):
        logger.info(f"Analyzing contract {i+1}/{len(contract_list)}")
        
        try:
            result = await analyze_single_contract(
                agent=agent,
                chain_id=contract_info["chain_id"],
                contract_address=contract_info["address"],
                block_number=contract_info.get("block_number")
            )
            results.append(result)
            
        except Exception as e:
            logger.error(f"Failed to analyze {contract_info['address']}: {str(e)}")
            continue
    
    return results


def print_summary(results: List[AnalysisResult]):
    """Print analysis summary"""
    
    total_contracts = len(results)
    successful_analyses = sum(1 for r in results if r.success)
    vulnerabilities_found = sum(1 for r in results if r.success and r.profitable)
    total_cost = sum(r.total_cost for r in results)
    total_revenue = sum(r.revenue_usd for r in results if r.profitable)
    
    print("\n" + "="*60)
    print("A1 ANALYSIS SUMMARY")
    print("="*60)
    print(f"Total contracts analyzed: {total_contracts}")
    print(f"Successful analyses: {successful_analyses}")
    print(f"Vulnerabilities found: {vulnerabilities_found}")
    print(f"Success rate: {(vulnerabilities_found/total_contracts)*100:.1f}%")
    print(f"Total cost: ${total_cost:.2f}")
    print(f"Total potential revenue: ${total_revenue:.2f}")
    
    if vulnerabilities_found > 0:
        print(f"ROI: {(total_revenue/total_cost)*100:.1f}%")
        print("\nVulnerabilities by type:")
        vuln_types = {}
        for result in results:
            if result.profitable:
                vuln_type = result.vulnerability_type or "unknown"
                vuln_types[vuln_type] = vuln_types.get(vuln_type, 0) + 1
        
        for vuln_type, count in vuln_types.items():
            print(f"  {vuln_type}: {count}")
    
    print("="*60)


def save_results(results: List[AnalysisResult], output_file: str):
    """Save results to JSON file"""
    
    results_data = []
    for result in results:
        results_data.append({
            "success": result.success,
            "profitable": result.profitable,
            "revenue_eth": result.revenue_eth,
            "revenue_usd": result.revenue_usd,
            "iterations": result.iterations,
            "total_cost": result.total_cost,
            "execution_time": result.execution_time,
            "vulnerability_type": result.vulnerability_type,
            "error_message": result.error_message,
            "exploit_code": result.exploit_code if result.exploit_code else None
        })
    
    with open(output_file, 'w') as f:
        json.dump(results_data, f, indent=2)
    
    print(f"Results saved to {output_file}")


async def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(
        description="A1 Smart Contract Security Analysis Tool"
    )
    
    # Single contract analysis
    parser.add_argument("--chain", type=int, help="Chain ID (1=Ethereum, 56=BSC)")
    parser.add_argument("--address", type=str, help="Contract address to analyze")
    parser.add_argument("--block", type=int, help="Historical block number (optional)")
    
    # Batch analysis
    parser.add_argument("--contract-list", type=str, help="JSON file with contract list")
    
    # Configuration
    parser.add_argument("--model", type=str, default=None, 
                       help="LLM model to use (default from config)")
    parser.add_argument("--max-iterations", type=int, default=None,
                       help="Maximum iterations per contract (default from config)")
    parser.add_argument("--output", type=str, default="a1_results.json",
                       help="Output file for results")
    
    # Logging
    parser.add_argument("--log-level", type=str, default=None,
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Log level (default from config)")
    
    args = parser.parse_args()
    
    # Load configuration first to get defaults
    try:
        config = Config.from_env()
        
        # Apply CLI overrides only if provided
        if args.model is not None:
            config.default_model = args.model
        if args.max_iterations is not None:
            config.max_iterations = args.max_iterations
        
        # Use config log level if not provided via CLI
        log_level = args.log_level if args.log_level is not None else config.log_level
        
        config.validate()
        
    except Exception as e:
        # Setup basic logging for error reporting
        setup_logging("ERROR")
        logger = logging.getLogger(__name__)
        logger.error(f"Configuration error: {str(e)}")
        print("\nRequired environment variables:")
        print("  OPENROUTER_API_KEY")
        print("  ETHEREUM_RPC_URL")
        print("  ETHERSCAN_API_KEY")
        print("  BSC_RPC_URL (for BSC analysis)")
        print("  BSCSCAN_API_KEY (for BSC analysis)")
        sys.exit(1)
    
    # Setup logging with config values
    setup_logging(log_level, config.log_file)
    logger = logging.getLogger(__name__)
    
    # Initialize agent
    agent = A1Agent(config)
    
    try:
        # Single contract analysis
        if args.chain and args.address:
            logger.info("Starting single contract analysis")
            
            result = await analyze_single_contract(
                agent=agent,
                chain_id=args.chain,
                contract_address=args.address,
                block_number=args.block
            )
            
            results = [result]
        
        # Batch analysis
        elif args.contract_list:
            logger.info("Starting batch contract analysis")
            
            with open(args.contract_list, 'r') as f:
                contract_list = json.load(f)
            
            results = await analyze_contract_list(agent, contract_list)
        
        else:
            logger.error("Please specify either --chain and --address, or --contract-list")
            parser.print_help()
            sys.exit(1)
        
        # Print summary and save results
        print_summary(results)
        save_results(results, args.output)
        
    except KeyboardInterrupt:
        logger.info("Analysis interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 