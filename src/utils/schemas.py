"""
schemas.py  (from student's LLM Configurator — adapted for LandIQ)
----------
Pydantic validation for LLM Configuration creation.
Enforces: contiguous priorities (1,2,3...), operation/mode match,
model exists in litellm catalogue (or has custom api_base).
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Dict, Optional
import re
import litellm

VALID_OPERATIONS = {"chat", "completion", "embedding", "image_generation",
                     "audio_transcription", "audio_speech"}
RESERVED_SEGMENTS = VALID_OPERATIONS | {"vision", "completions", "embeddings",
                                         "images", "audio", "usage", "capabilities"}


class ModelConfig(BaseModel):
    litellm_model: str
    priority: int
    api_key_env: Optional[str] = None   # used if model has no DB-stored key
    api_base: Optional[str] = None
    rpm: Optional[int] = Field(default=None, gt=0)
    tpm: Optional[int] = Field(default=None, gt=0)


class CustomOperation(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    models: List[ModelConfig]

    @field_validator('models')
    @classmethod
    def validate_models_not_empty(cls, v):
        if not v:
            raise ValueError("Custom operation must have at least one model.")
        priorities = sorted(m.priority for m in v)
        if priorities != list(range(1, len(v) + 1)):
            raise ValueError(f"Priorities must be contiguous from 1 (got {priorities}).")
        return v


class Restrictions(BaseModel):
    tpm: int = Field(gt=0)
    rpm: int = Field(gt=0)
    tpr: int = Field(gt=0)


class Guardrails(BaseModel):
    pii_masking: bool
    profanity_filter: bool


class ConfigRequest(BaseModel):
    usecase_name: str = Field(..., max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    config_name: str = Field(..., max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    operations: Dict[str, List[ModelConfig]]
    custom_operations: Optional[Dict[str, CustomOperation]] = None
    restrictions: Restrictions
    guardrails: Guardrails

    @model_validator(mode='after')
    def validate_operations(self) -> 'ConfigRequest':
        if "chat" not in self.operations or not self.operations["chat"]:
            raise ValueError("The 'chat' operation group is required and cannot be empty.")

        for op, models in self.operations.items():
            if op not in VALID_OPERATIONS:
                raise ValueError(f"Invalid operation '{op}'. Must be one of {VALID_OPERATIONS}")
            if not models:
                raise ValueError(f"Operation group '{op}' is empty.")

            priorities = []
            for m in models:
                priorities.append(m.priority)
                cost_info = litellm.model_cost.get(m.litellm_model)
                if not cost_info:
                    if m.api_base is None:
                        raise ValueError(f"Unknown model '{m.litellm_model}', check spelling")
                else:
                    mode = cost_info.get('mode')
                    if mode and mode != op:
                        raise ValueError(f"{m.litellm_model} is a {mode} model; cannot be in the {op} chain.")

            sorted_priorities = sorted(priorities)
            expected = list(range(1, len(models) + 1))
            if sorted_priorities != expected:
                raise ValueError(
                    f"Priorities in operation '{op}' must be contiguous from 1 "
                    f"(expected {expected}, got {sorted_priorities})."
                )

        if self.custom_operations:
            if len(self.custom_operations) > 10:
                raise ValueError("Maximum 10 custom operations allowed per config.")
            for op_name, custom_op in self.custom_operations.items():
                if not re.match(r"^[a-zA-Z0-9_-]+$", op_name):
                    raise ValueError(f"Custom operation name '{op_name}' contains invalid characters.")
                if op_name in RESERVED_SEGMENTS:
                    raise ValueError(f"Custom operation name '{op_name}' is reserved.")

        return self