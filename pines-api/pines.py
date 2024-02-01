import configparser
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pathlib import Path
from transformers import pipeline
import torch
import uvicorn


def get_parent_dir():
    """
    Returns the parent directory of the current file.
    """
    return Path(__file__).parent

config = configparser.ConfigParser()
config.read(get_parent_dir() / "config.ini")
model_dir = config["DEFAULT"].get("ModelDir")
model_name = config["DEFAULT"].get("ModelName")

models_path = get_parent_dir() / model_dir / model_name

# Path to your fine-tuned model and tokenizer

if len(model_dir) == 0:
    raise ValueError("Please specify a model dir in config.ini")

classifier = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load ML Model
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    classifier["model"] = pipeline('sentiment-analysis',
                        model=models_path,
                        device=device,
                        truncation=True
                        )
    yield
    # Clean up
    classifier.clear()


app = FastAPI(title="PINES NLP Model",
              description=f"{model_name}",
              version="0.0.1",
              lifespan=lifespan
              )


@app.post("/predict")
async def detect(text: str):
    """Label a single text"""
    predictions = classifier["model"].predict(text)
    return {"prediction": predictions[0],
            "model": model_name}


@app.post("/predict_batch")
async def detect_batch(texts: list[str]):
    """Label a batch of texts"""
    predictions = classifier["model"].predict(texts)
    return {"prediction": predictions,
            "model": model_name}


if __name__ == "__main__":
    uvicorn.run("pines:app",
                host="0.0.0.0",
                port=8036,
                reload=True)
