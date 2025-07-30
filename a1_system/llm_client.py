"""
LLM Client for A1 System - OpenRouter Integration
"""

import asyncio
import aiohttp
import json
import time
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from .config import Config


@dataclass
class LLMUsage:
    """Token usage tracking"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class LLMClient:
    """
    Simple OpenRouter client for LLM access
    
    Supports multiple models with cost tracking and rate limiting
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # OpenRouter API settings
        self.base_url = "https://openrouter.ai/api/v1"
        self.api_key = config.openrouter_api_key
        
        # Cost tracking
        self.total_cost = 0.0
        self.request_count = 0
        self.last_request_cost = 0.0
        self.last_usage = LLMUsage()
        
        # Rate limiting
        self.last_request_time = 0.0
        self.min_request_interval = 1.0  # 1 second between requests
        
        # Model pricing (per 1M tokens) - Updated January 2025
        self.model_pricing = {
            # OpenAI models
            "openai/o3-mini": {"input": 2.0, "output": 8.0},
            "openai/o3": {"input": 20.0, "output": 80.0},
            "openai/o3-pro": {"input": 200.0, "output": 800.0},
            "openai/gpt-4o": {"input": 2.5, "output": 10.0},
            "openai/gpt-4o-mini": {"input": 0.15, "output": 0.6},
            
            # Google models  
            "google/gemini-2.5-pro": {"input": 1.25, "output": 10.0},
            "google/gemini-2.5-flash": {"input": 0.1, "output": 0.4},
            "google/gemini-flash-1.5": {"input": 0.0, "output": 0.0},  # Free tier
            "google/gemini-pro": {"input": 0.0, "output": 0.0},  # Free tier
            
            # Anthropic models
            "anthropic/claude-3.5-sonnet": {"input": 3.0, "output": 15.0},
            "anthropic/claude-3.5-haiku": {"input": 0.8, "output": 4.0},
            
            # Other models
            "meta-llama/llama-3.3-70b-instruct": {"input": 0.35, "output": 0.4},
            "deepseek/deepseek-r1": {"input": 0.14, "output": 0.28},
            
            # Free models
            "huggingface/meta-llama/llama-3.2-1b-instruct": {"input": 0.0, "output": 0.0},
            "huggingface/microsoft/phi-3-mini-4k-instruct": {"input": 0.0, "output": 0.0},
        }
    
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Generate text using specified model
        
        Args:
            system_prompt: System instruction for the model
            user_prompt: User query/request
            model: Model to use (defaults to config.default_model)
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text response
        """
        
        model = model or self.config.default_model
        max_tokens = max_tokens or self.config.max_tokens
        
        # Rate limiting
        await self._rate_limit()
        
        # Check cost limits
        if self.config.cost_tracking and self.total_cost >= self.config.max_cost_per_analysis:
            raise ValueError(f"Cost limit exceeded: ${self.total_cost:.2f}")
        
        try:
            start_time = time.time()
            
            # Prepare request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/your-repo/a1-security",  # Required by OpenRouter
                "X-Title": "A1 Security Analysis Tool"  # Required by OpenRouter
            }
            
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False
            }
            
            # Add any additional parameters
            payload.update(kwargs)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300)  # 5 minute timeout
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"OpenRouter API error {response.status}: {error_text}")
                    
                    result = await response.json()
                    
                    # Debug: Log the full response for troubleshooting
                    self.logger.debug(f"Full API response: {result}")
                    
                    # Extract response
                    if "choices" not in result or not result["choices"]:
                        raise Exception(f"No response choices returned from API. Response: {result}")
                    
                    choice = result["choices"][0]
                    if "message" not in choice:
                        raise Exception(f"No message in choice. Choice: {choice}")
                    
                    content = choice["message"].get("content", "")
                    
                    # Check for empty content
                    if not content or not content.strip():
                        self.logger.warning(f"Empty response from model {model}")
                        self.logger.debug(f"Raw choice data: {choice}")
                        raise Exception(f"Model returned empty response. Raw data: {choice}")
                    
                    # Track usage and costs
                    if "usage" in result:
                        usage_data = result["usage"]
                        self.last_usage = LLMUsage(
                            prompt_tokens=usage_data.get("prompt_tokens", 0),
                            completion_tokens=usage_data.get("completion_tokens", 0),
                            total_tokens=usage_data.get("total_tokens", 0)
                        )
                        
                        # Calculate cost
                        self.last_request_cost = self._calculate_cost(model, self.last_usage)
                        self.total_cost += self.last_request_cost
                        self.last_usage.cost_usd = self.last_request_cost
                    
                    self.request_count += 1
                    execution_time = time.time() - start_time
                    
                    self.logger.info(
                        f"LLM request completed: {model}, "
                        f"tokens: {self.last_usage.total_tokens}, "
                        f"cost: ${self.last_request_cost:.4f}, "
                        f"time: {execution_time:.1f}s"
                    )
                    
                    return content
                    
        except Exception as e:
            self.logger.error(f"LLM generation failed: {str(e)}")
            raise
    
    async def _rate_limit(self):
        """Simple rate limiting to avoid hitting API limits"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            await asyncio.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _calculate_cost(self, model: str, usage: LLMUsage) -> float:
        """Calculate cost for a request based on token usage"""
        
        if model not in self.model_pricing:
            self.logger.warning(f"Unknown model pricing for {model}, using default rates")
            # Default to reasonable rates
            input_rate = 1.0
            output_rate = 3.0
        else:
            pricing = self.model_pricing[model]
            input_rate = pricing["input"]
            output_rate = pricing["output"]
        
        # Calculate cost (rates are per 1M tokens)
        input_cost = (usage.prompt_tokens / 1_000_000) * input_rate
        output_cost = (usage.completion_tokens / 1_000_000) * output_rate
        
        return input_cost + output_cost
    
    def get_last_request_cost(self) -> float:
        """Get cost of last request"""
        return self.last_request_cost
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics"""
        return {
            "total_requests": self.request_count,
            "total_cost_usd": self.total_cost,
            "average_cost_per_request": self.total_cost / max(self.request_count, 1),
            "last_request": {
                "tokens": self.last_usage.total_tokens,
                "cost": self.last_request_cost
            }
        }
    
    def reset_costs(self):
        """Reset cost tracking (useful for testing)"""
        self.total_cost = 0.0
        self.request_count = 0
        self.last_request_cost = 0.0
    
    async def test_connection(self) -> bool:
        """Test API connection with a simple request"""
        try:
            response = await self.generate(
                system_prompt="You are a helpful assistant.",
                user_prompt="Say 'Hello, this is a test.' and nothing else.",
                model="google/gemini-flash-1.5",  # Use free model for testing
                max_tokens=20
            )
            
            self.logger.info(f"Test response: '{response}'")
            return "hello" in response.lower() and "test" in response.lower()
            
        except Exception as e:
            self.logger.error(f"Connection test failed: {str(e)}")
            return False 