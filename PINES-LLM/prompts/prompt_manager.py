"""
Prompt Manager
Loads and manages prompt templates for different clinical tasks
"""

import yaml
from pathlib import Path
from typing import Dict, Any
from string import Template
from loguru import logger


class PromptManager:
    """Manages prompt templates for clinical event detection tasks"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.prompts_dir = Path(__file__).parent
        self.prompts = {}
        self.default_task = config.get("default_task", "default")
        self._load_prompts()
    
    def _load_prompts(self):
        """Load all YAML prompt templates from the prompts directory"""
        logger.info(f"Loading prompts from {self.prompts_dir}")
        
        prompt_files = list(self.prompts_dir.glob("*_prompt.yaml"))
        
        if not prompt_files:
            logger.warning(f"No prompt files found in {self.prompts_dir}")
            # Create a default prompt
            self.prompts["default"] = self._get_default_prompt()
            return
        
        for prompt_file in prompt_files:
            task_name = prompt_file.stem.replace("_prompt", "")
            try:
                with open(prompt_file) as f:
                    self.prompts[task_name] = yaml.safe_load(f)
                logger.info(f"Loaded prompt: {task_name}")
            except Exception as e:
                logger.error(f"Failed to load prompt {prompt_file}: {e}")
        
        # Ensure default exists
        if "default" not in self.prompts and self.prompts:
            # Use first prompt as default
            first_key = list(self.prompts.keys())[0]
            self.prompts["default"] = self.prompts[first_key]
            logger.info(f"Using '{first_key}' as default prompt")
    
    def _get_default_prompt(self) -> Dict[str, Any]:
        """Fallback default prompt"""
        return {
            "task_name": "default",
            "description": "Generic clinical event detection",
            "system": """You are a clinical event detection AI. 
Analyze the provided clinical note and determine if it describes a clinically significant event.

Return ONLY valid JSON in this format:
{
  "label": 0 or 1,
  "score": 0.0 to 1.0,
  "reasoning": "brief explanation"
}

Where:
- label: 1 if event present, 0 if not
- score: confidence level (0.0 = no confidence, 1.0 = very confident)
- reasoning: brief explanation of your decision""",
            "user": "Clinical Note:\n\n${note_text}\n\nJSON Response:"
        }
    
    def build_prompt(self, task: str, note_text: str) -> str:
        """
        Build a complete prompt from template
        
        Args:
            task: Task name (e.g., 'vte_detection')
            note_text: Clinical note text to analyze
        
        Returns:
            Formatted prompt string ready for LLM
        """
        # Get prompt template
        if task not in self.prompts:
            logger.warning(f"Task '{task}' not found, using default")
            task = "default"
            if task not in self.prompts:
                self.prompts["default"] = self._get_default_prompt()
        
        template_data = self.prompts[task]
        
        # Extract system and user prompts
        system_prompt = template_data.get("system", "")
        user_template_str = template_data.get("user", "${note_text}")
        
        # Substitute note text in user prompt
        user_template = Template(user_template_str)
        user_prompt = user_template.safe_substitute(note_text=note_text)
        
        # Format for Llama 3.1 chat template
        full_prompt = self._format_for_llama(system_prompt, user_prompt)
        
        return full_prompt
    
    def _format_for_llama(self, system_prompt: str, user_prompt: str) -> str:
        """
        Format prompts using Llama 3.1 chat template
        
        Llama 3.1 uses special tokens:
        <|begin_of_text|><|start_header_id|>system<|end_header_id|>
        {system}<|eot_id|><|start_header_id|>user<|end_header_id|>
        {user}<|eot_id|><|start_header_id|>assistant<|end_header_id|>
        """
        formatted = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>

{user_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        return formatted
    
    def get_available_tasks(self) -> list:
        """Return list of available task names"""
        return list(self.prompts.keys())



