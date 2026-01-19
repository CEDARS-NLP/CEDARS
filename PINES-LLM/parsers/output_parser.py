"""
Output Parser
Extracts structured data from LLM responses with multiple fallback strategies
"""

import json
import re
from typing import Dict, Any
from loguru import logger


class OutputParser:
    """
    Parse LLM output into standardized format
    Handles various output formats with robust fallbacks
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.use_fallback = config.get("fallback_parser", True)
    
    def parse(self, llm_output: Dict[str, Any], task: str) -> Dict[str, Any]:
        """
        Parse LLM response text into structured format
        
        Args:
            llm_output: Output from LLM backend with 'text' field
            task: Task name (for logging)
        
        Returns:
            {
                "label": 0 or 1,
                "score": 0.0 - 1.0,
                "reasoning": "explanation"
            }
        """
        text = llm_output["text"].strip()
        
        logger.debug(f"Parsing output for task '{task}': {text[:200]}...")
        
        # Strategy 1: Try clean JSON parsing
        try:
            result = self._parse_json(text)
            logger.debug(f"Successfully parsed JSON: label={result['label']}, score={result['score']}")
            return result
        except Exception as e:
            logger.debug(f"JSON parsing failed: {str(e)}")
        
        # Strategy 2: Try to extract JSON from markdown code blocks
        if self.use_fallback:
            try:
                result = self._extract_json_from_markdown(text)
                logger.debug(f"Extracted JSON from markdown: label={result['label']}, score={result['score']}")
                return result
            except Exception as e:
                logger.debug(f"Markdown extraction failed: {str(e)}")
        
        # Strategy 3: Regex-based extraction (last resort)
        if self.use_fallback:
            try:
                result = self._parse_regex(text)
                logger.warning(f"Used regex fallback parser: label={result['label']}, score={result['score']}")
                return result
            except Exception as e:
                logger.error(f"All parsing strategies failed: {str(e)}")
        
        # Strategy 4: Return conservative default
        logger.error("Could not parse LLM output, returning conservative default")
        return {
            "label": 0,
            "score": 0.5,
            "reasoning": "Failed to parse LLM output"
        }
    
    def _parse_json(self, text: str) -> Dict[str, Any]:
        """
        Parse clean JSON from response
        Handles various JSON formats
        """
        # Try to find JSON object in text
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        
        if not json_match:
            raise ValueError("No JSON object found in text")
        
        json_str = json_match.group(0)
        data = json.loads(json_str)
        
        return self._normalize_output(data)
    
    def _extract_json_from_markdown(self, text: str) -> Dict[str, Any]:
        """
        Extract JSON from markdown code blocks
        Handles ```json ... ``` format
        """
        # Look for markdown code blocks
        code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        
        if code_block_match:
            json_str = code_block_match.group(1)
            data = json.loads(json_str)
            return self._normalize_output(data)
        
        raise ValueError("No JSON in markdown code block")
    
    def _parse_regex(self, text: str) -> Dict[str, Any]:
        """
        Fallback: Extract information using regex patterns
        Used when JSON parsing fails
        """
        logger.debug("Using regex fallback parser")
        
        # Initialize defaults
        label = 0
        score = 0.5
        reasoning = ""
        
        # Try to find label
        # Look for various patterns: "label": 1, "label: 1", label=1, etc.
        label_patterns = [
            r'["\']?label["\']?\s*[:=]\s*["\']?(\d)["\']?',
            r'\blabel\s+is\s+(\d)\b',
            r'\blabel\s*:\s*(\d)\b',
        ]
        
        for pattern in label_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                label = int(match.group(1))
                break
        
        # If no explicit label, look for keywords
        if label == 0:
            positive_keywords = [
                r'\bconfirmed\b', r'\bdiagnosed\b', r'\bpresent\b', 
                r'\bevent\s+detected\b', r'\byes\b', r'\bpositive\b'
            ]
            for keyword in positive_keywords:
                if re.search(keyword, text, re.IGNORECASE):
                    label = 1
                    break
        
        # Try to find score
        score_patterns = [
            r'["\']?score["\']?\s*[:=]\s*["\']?([0-9]*\.?[0-9]+)["\']?',
            r'\bconfidence\s*[:=]\s*([0-9]*\.?[0-9]+)',
            r'\bscore\s+is\s+([0-9]*\.?[0-9]+)',
        ]
        
        for pattern in score_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                score_val = float(match.group(1))
                # Normalize if needed (some models return 0-100)
                if score_val > 1.0:
                    score_val = score_val / 100.0
                score = score_val
                break
        
        # If we found a label but no score, use heuristic
        if score == 0.5 and label != 0:
            score = 0.7  # Moderate confidence for regex extraction
        
        # Try to extract reasoning
        reasoning_patterns = [
            r'["\']?reasoning["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'\breasoning\s*:\s*(.+?)(?:\n|$)',
            r'\bexplanation\s*:\s*(.+?)(?:\n|$)',
        ]
        
        for pattern in reasoning_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                reasoning = match.group(1).strip()[:200]  # Limit length
                break
        
        if not reasoning:
            reasoning = text[:200]  # Use first 200 chars as reasoning
        
        return {
            "label": label,
            "score": score,
            "reasoning": reasoning
        }
    
    def _normalize_output(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize parsed data to standard format
        Handles various field names and formats
        """
        # Extract label (try multiple field names)
        label = data.get("label", data.get("prediction", data.get("class", 0)))
        
        # Handle string labels like "LABEL_1", "LABEL_0"
        if isinstance(label, str):
            if "1" in label or "positive" in label.lower() or "yes" in label.lower():
                label = 1
            else:
                label = 0
        else:
            label = int(label)
        
        # Extract score (try multiple field names)
        score = data.get("score", data.get("confidence", data.get("probability", 0.5)))
        score = float(score)
        
        # Normalize score if needed (0-100 to 0-1)
        if score > 1.0:
            score = score / 100.0
        
        # Clamp to valid range
        score = max(0.0, min(1.0, score))
        
        # Extract reasoning
        reasoning = data.get("reasoning", data.get("explanation", data.get("rationale", "")))
        if isinstance(reasoning, str):
            reasoning = reasoning.strip()[:500]  # Limit length
        else:
            reasoning = str(reasoning)[:500]
        
        return {
            "label": label,
            "score": score,
            "reasoning": reasoning
        }



