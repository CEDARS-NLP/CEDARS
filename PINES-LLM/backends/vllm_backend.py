"""
vLLM backend implementation
Best for high-throughput production use with GPU acceleration
"""

import httpx
import time
from typing import Dict, Any
from loguru import logger
from .base import LLMBackend


class VLLMBackend(LLMBackend):
    """
    vLLM backend using OpenAI-compatible API
    
    Requirements:
        - vLLM server running: 
          vllm serve meta-llama/Llama-3.1-70B-Instruct --port 8000
          
        Or with Docker:
          docker run --gpus all -p 8000:8000 vllm/vllm-openai:latest \\
            --model meta-llama/Llama-3.1-70B-Instruct
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("vllm_url", "http://localhost:8000")
        self.timeout = config.get("model_settings", {}).get("timeout", 120.0)
        self.client = httpx.AsyncClient(timeout=self.timeout)
        logger.info(f"vLLM backend initialized at {self.api_url}")
    
    async def generate(
        self,
        prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call vLLM server for text generation
        
        Args:
            prompt: Input prompt
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
        
        Returns:
            Response dictionary with text, tokens, latency, etc.
        """
        # Use config defaults if not provided
        model_settings = self.config.get("model_settings", {})
        if temperature is None:
            temperature = model_settings.get("temperature", 0.0)
        if max_tokens is None:
            max_tokens = model_settings.get("max_tokens", 500)
        
        start_time = time.time()
        
        try:
            # vLLM uses OpenAI-compatible API
            response = await self.client.post(
                f"{self.api_url}/v1/completions",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": model_settings.get("top_p", 0.95),
                    "stop": kwargs.get("stop", None)
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            latency = int((time.time() - start_time) * 1000)
            
            logger.debug(f"vLLM generation completed in {latency}ms")
            
            return {
                "text": result["choices"][0]["text"],
                "tokens": result["usage"]["total_tokens"],
                "latency": latency,
                "finish_reason": result["choices"][0]["finish_reason"]
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"vLLM HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"vLLM request failed: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"vLLM connection error: {str(e)}")
            raise Exception(f"Cannot connect to vLLM at {self.api_url}")
        except Exception as e:
            logger.error(f"vLLM generation error: {str(e)}")
            raise
    
    async def health_check(self) -> bool:
        """Check if vLLM server is healthy"""
        try:
            response = await self.client.get(f"{self.api_url}/health")
            is_healthy = response.status_code == 200
            logger.debug(f"vLLM health check: {'healthy' if is_healthy else 'unhealthy'}")
            return is_healthy
        except Exception as e:
            logger.warning(f"vLLM health check failed: {str(e)}")
            return False




