"""
Abstract base class for LLM backends
Allows swapping between vLLM, Ollama, llama.cpp, etc.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from loguru import logger


class LLMBackend(ABC):
    """Base class for all LLM backends"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_name = config.get("model_name", "unknown")
        self.backend_type = config.get("backend_type", "unknown")
        logger.info(f"Initializing {self.backend_type} backend with model: {self.model_name}")
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 500,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate response from LLM
        
        Args:
            prompt: Input prompt text
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional backend-specific parameters
        
        Returns:
            {
                "text": "LLM response text",
                "tokens": 450,
                "latency": 1250,  # milliseconds
                "finish_reason": "stop"
            }
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if backend is healthy and accessible"""
        pass


def get_backend(config: Dict[str, Any]) -> LLMBackend:
    """
    Factory function to create appropriate backend based on configuration
    
    Args:
        config: Configuration dictionary
    
    Returns:
        LLMBackend instance
    """
    backend_type = config.get("backend_type", "ollama").lower()
    
    logger.info(f"Creating backend: {backend_type}")
    
    if backend_type == "vllm":
        from .vllm_backend import VLLMBackend
        return VLLMBackend(config)
    elif backend_type == "ollama":
        from .ollama_backend import OllamaBackend
        return OllamaBackend(config)
    elif backend_type == "llamacpp":
        from .llamacpp_backend import LlamaCppBackend
        return LlamaCppBackend(config)
    elif backend_type == "openai":
        from .openai_backend import OpenAIBackend
        return OpenAIBackend(config)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}. Supported: vllm, ollama, llamacpp, openai")




