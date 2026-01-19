"""
OpenAI-compatible API backend
Works with OpenAI, Azure OpenAI, or any OpenAI-compatible endpoint
"""

import httpx
import time
from typing import Dict, Any
from loguru import logger
from .base import LLMBackend


class OpenAIBackend(LLMBackend):
    """
    OpenAI-compatible API backend
    
    Can be used with:
    - OpenAI API (requires BAA for PHI)
    - Azure OpenAI
    - Together.ai
    - Anyscale Endpoints
    - Any OpenAI-compatible API
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("openai_url", "https://api.openai.com/v1")
        self.api_key = config.get("openai_api_key", "")
        self.timeout = config.get("model_settings", {}).get("timeout", 120.0)
        
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        self.client = httpx.AsyncClient(timeout=self.timeout, headers=headers)
        logger.info(f"OpenAI-compatible backend initialized at {self.api_url}")
    
    async def generate(
        self,
        prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call OpenAI-compatible API for text generation
        
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
            response = await self.client.post(
                f"{self.api_url}/completions",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": model_settings.get("top_p", 0.95),
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            latency = int((time.time() - start_time) * 1000)
            
            logger.debug(f"OpenAI generation completed in {latency}ms")
            
            return {
                "text": result["choices"][0]["text"],
                "tokens": result["usage"]["total_tokens"],
                "latency": latency,
                "finish_reason": result["choices"][0]["finish_reason"]
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenAI HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"OpenAI request failed: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"OpenAI connection error: {str(e)}")
            raise Exception(f"Cannot connect to OpenAI at {self.api_url}")
        except Exception as e:
            logger.error(f"OpenAI generation error: {str(e)}")
            raise
    
    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible"""
        try:
            response = await self.client.get(f"{self.api_url}/models")
            is_healthy = response.status_code == 200
            logger.debug(f"OpenAI health check: {'healthy' if is_healthy else 'unhealthy'}")
            return is_healthy
        except Exception as e:
            logger.warning(f"OpenAI health check failed: {str(e)}")
            return False




