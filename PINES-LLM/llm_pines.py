"""
LLM-based PINES Service
Main FastAPI service for clinical event detection using Large Language Models.
Compatible with original PINES API for seamless CEDARS integration.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import yaml
from pathlib import Path
from loguru import logger
import sys

from backends import get_backend
from prompts import PromptManager
from parsers import OutputParser

# Configure logging
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

# Load configuration
config_path = Path(__file__).parent / "llm_config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

logger.info(f"Loading LLM-PINES with backend: {config['backend_type']}")

# Initialize components
backend = get_backend(config)
prompt_manager = PromptManager(config)
parser = OutputParser(config)

# FastAPI app
app = FastAPI(
    title="PINES-LLM",
    description="Clinical Event Detection using Large Language Models",
    version="2.0.0"
)


class Note(BaseModel):
    """Note input (backward compatible with original PINES)"""
    text: str = Field(..., description="Clinical note text")


class PredictionRequest(BaseModel):
    """Extended prediction request"""
    text: str = Field(..., description="Clinical note text")
    task: Optional[str] = Field("default", description="Task type (e.g., vte_detection)")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict, description="LLM options")


class PredictionResponse(BaseModel):
    """Prediction response (backward compatible)"""
    prediction: Dict[str, Any]
    model: str
    metadata: Optional[Dict[str, Any]] = None


@app.get("/")
async def read_root():
    """Root endpoint"""
    return {
        "message": f"Welcome to PINES-LLM\n\nCurrent Backend: {backend.backend_type}\nModel: {backend.model_name}"
    }


@app.get("/healthcheck")
async def healthcheck():
    """Health check endpoint"""
    is_healthy = await backend.health_check()
    
    return {
        "message": f"PINES-LLM\n\nBackend: {backend.backend_type}\nModel: {backend.model_name}",
        "status": "Healthy" if is_healthy else "Unhealthy",
        "backend_healthy": is_healthy
    }


@app.post("/predict")
async def predict(request: Note) -> Dict[str, Any]:
    """
    Main prediction endpoint - backward compatible with original PINES
    Accepts either Note or PredictionRequest format
    """
    try:
        # Convert to PredictionRequest if needed
        if isinstance(request, Note):
            pred_request = PredictionRequest(text=request.text)
        else:
            pred_request = request
        
        logger.info(f"Processing prediction for task: {pred_request.task}")
        
        # 1. Build prompt from template
        prompt = prompt_manager.build_prompt(
            task=pred_request.task,
            note_text=pred_request.text
        )
        
        logger.debug(f"Generated prompt (first 200 chars): {prompt[:200]}...")
        
        # 2. Call LLM backend
        llm_response = await backend.generate(
            prompt=prompt,
            **pred_request.options
        )
        
        logger.debug(f"LLM response: {llm_response['text'][:200]}...")
        
        # 3. Parse structured output
        parsed = parser.parse(llm_response, task=pred_request.task)
        
        logger.info(f"Prediction: label={parsed['label']}, score={parsed['score']:.3f}")
        
        # 4. Format response (backward compatible with original PINES)
        return {
            "prediction": {
                "label": parsed["label"],
                "score": parsed["score"]
            },
            "model": backend.model_name,
            "metadata": {
                "reasoning": parsed.get("reasoning", ""),
                "tokens_used": llm_response.get("tokens", 0),
                "latency_ms": llm_response.get("latency", 0),
                "finish_reason": llm_response.get("finish_reason", "unknown")
            }
        }
        
    except Exception as e:
        logger.error(f"Prediction failed: {str(e)}")
        logger.exception(e)
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@app.post("/predict_batch")
async def predict_batch(notes: list[Note]) -> Dict[str, Any]:
    """
    Batch prediction endpoint
    Currently processes sequentially, can be optimized for batching
    """
    try:
        predictions = []
        
        for note in notes:
            result = await predict(note)
            predictions.append(result)
        
        return {
            "predictions": predictions,
            "model": backend.model_name,
            "count": len(predictions)
        }
        
    except Exception as e:
        logger.error(f"Batch prediction failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch prediction failed: {str(e)}")


@app.get("/tasks")
async def list_tasks():
    """List available tasks/prompts"""
    return {
        "available_tasks": list(prompt_manager.prompts.keys()),
        "default_task": config.get("default_task", "default")
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "llm_pines:app",
        host="0.0.0.0",
        port=8036,
        reload=True
    )


