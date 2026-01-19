"""
Ollama backend implementation
Easiest for local development and testing
"""

import httpx
import time
from typing import Dict, Any
from loguru import logger
from .base import LLMBackend


class OllamaBackend(LLMBackend):
    """
    Ollama backend for local LLM inference
    
    Requirements:
        - Ollama installed: https://ollama.ai
        - Model pulled: ollama pull llama3.1:70b
        
    Quick start:
        curl -fsSL https://ollama.com/install.sh | sh
        ollama pull llama3.1:8b
        ollama serve
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_url = config.get("ollama_url", "http://localhost:11434")
        self.timeout = config.get("model_settings", {}).get("timeout", 180.0)
        self.client = httpx.AsyncClient(timeout=self.timeout)
        logger.info(f"Ollama backend initialized at {self.api_url}")
    
    async def generate(
        self,
        prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Call Ollama API for text generation
        
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
            max_tokens = model_settings.get("max_tokens", 20)
        
        start_time = time.time()
        
        try:
            response = await self.client.post(
                f"{self.api_url}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "temperature": temperature,
                    "options": {
                        "num_predict": max_tokens,
                        "top_p": model_settings.get("top_p", 0.95),
                    },
                    "stream": False
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            latency = int((time.time() - start_time) * 1000)
            
            logger.debug(f"Ollama generation completed in {latency}ms")
            
            # Ollama returns tokens separately
            prompt_tokens = result.get("prompt_eval_count", 0)
            response_tokens = result.get("eval_count", 0)
            total_tokens = prompt_tokens + response_tokens
            
            return {
                "text": result["response"],
                "tokens": total_tokens,
                "latency": latency,
                "finish_reason": "stop" if result.get("done", False) else "length"
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Ollama request failed: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Ollama connection error: {str(e)}")
            raise Exception(f"Cannot connect to Ollama at {self.api_url}. Is Ollama running?")
        except Exception as e:
            logger.error(f"Ollama generation error: {str(e)}")
            raise
    
    async def health_check(self) -> bool:
        """Check if Ollama server is healthy"""
        try:
            response = await self.client.get(f"{self.api_url}/api/tags")
            is_healthy = response.status_code == 200
            
            if is_healthy:
                models = response.json().get("models", [])
                model_names = [m["name"] for m in models]
                logger.debug(f"Ollama available models: {model_names}")
                
                # Check if our model is available
                if not any(self.model_name in name for name in model_names):
                    logger.warning(f"Model {self.model_name} not found in Ollama. Available: {model_names}")
            
            return is_healthy
            
        except Exception as e:
            logger.warning(f"Ollama health check failed: {str(e)}")
            return False




