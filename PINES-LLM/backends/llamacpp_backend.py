"""
llama.cpp backend implementation
Good for CPU inference and custom model formats (GGUF)
"""

import httpx
import time
from typing import Dict, Any
from loguru import logger
from .base import LLMBackend


class LlamaCppBackend(LLMBackend):
    """
    llama.cpp backend using server mode
    
    Requirements:
        - llama.cpp compiled with server support
        - Model in GGUF format
        
    Quick start:
        git clone https://github.com/ggerganov/llama.cpp
        cd llama.cpp && make
        ./server -m models/llama-3.1-70b-instruct-q4_0.gguf --port 8080
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("llamacpp_url", "http://localhost:8080")
        self.timeout = config.get("model_settings", {}).get("timeout", 180.0)
        self.client = httpx.AsyncClient(timeout=self.timeout)
        logger.info(f"llama.cpp backend initialized at {self.api_url}")
    
    async def generate(
        self,
        prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call llama.cpp server for text generation
        
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
                f"{self.api_url}/completion",
                json={
                    "prompt": prompt,
                    "temperature": temperature,
                    "n_predict": max_tokens,
                    "top_p": model_settings.get("top_p", 0.95),
                    "stop": kwargs.get("stop", []),
                    "stream": False
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            latency = int((time.time() - start_time) * 1000)
            
            logger.debug(f"llama.cpp generation completed in {latency}ms")
            
            return {
                "text": result["content"],
                "tokens": result.get("tokens_predicted", 0) + result.get("tokens_evaluated", 0),
                "latency": latency,
                "finish_reason": "stop" if result.get("stopped_word", False) else "length"
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"llama.cpp HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"llama.cpp request failed: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"llama.cpp connection error: {str(e)}")
            raise Exception(f"Cannot connect to llama.cpp at {self.api_url}")
        except Exception as e:
            logger.error(f"llama.cpp generation error: {str(e)}")
            raise
    
    async def health_check(self) -> bool:
        """Check if llama.cpp server is healthy"""
        try:
            response = await self.client.get(f"{self.api_url}/health")
            is_healthy = response.status_code == 200
            logger.debug(f"llama.cpp health check: {'healthy' if is_healthy else 'unhealthy'}")
            return is_healthy
        except Exception as e:
            logger.warning(f"llama.cpp health check failed: {str(e)}")
            return False




