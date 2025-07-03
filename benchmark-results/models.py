"""Pydantic models for the benchmark results storage service."""

from pydantic import BaseModel
from typing import Any, Optional

class EvaluationPayload(BaseModel):
    """Incoming payload for both /raw_input and /standardized_output.

    * `run_id` can be omitted (None); we will auto-generate a UUID.
    * `data` may be any JSON-serialisable payload or a raw JSON string.
    """

    run_id: Optional[str] = None
    benchmark_name: str
    data: Any
    timestamp: str
    model_id: str
    tokenizer_id: str
    source: str

    class Config:
        schema_extra = {
            "example": {
                "run_id": "run-123",
                "benchmark_name": "mmlu",
                "data": {"accuracy": 0.85, "total_questions": 1000},
                "timestamp": "2024-01-01T12:00:00Z",
                "model_id": "gpt-4",
                "tokenizer_id": "gpt-4-tokenizer",
                "source": "evaluation-pipeline"
            }
        }

class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    mongodb_status: str

class SaveResponse(BaseModel):
    """Response model for save operations."""
    status: str
    run_id: str
    saved_as: str

class ResultFileInfo(BaseModel):
    """Model for result file information."""
    pk: str
    benchmark_name: str
    model_id: str
    tokenizer_id: str
    source: str
    timestamp: str

class ResultFileContent(BaseModel):
    """Model for result file content."""
    result_name: str
    data: Any 