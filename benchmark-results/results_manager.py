"""Results management for benchmark results storage and retrieval."""

import json
import logging
from uuid import uuid4
from typing import List, Dict, Any
from fastapi import HTTPException

from database import get_raw_collection, get_standardized_collection
from models import EvaluationPayload, SaveResponse, ResultFileInfo, ResultFileContent

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Storage Functions
# -----------------------------------------------------------------------------

async def save_raw_result(payload: EvaluationPayload) -> SaveResponse:
    """Save raw benchmark result to the database."""
    try:
        run_id = payload.run_id or None
        pk = f"{payload.timestamp}-{payload.benchmark_name}-{run_id}"

        # Attempt to parse JSON strings so that stored files are always objects
        raw_data = payload.data
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                pass  # leave as string

        document = {
            "pk": pk, 
            "benchmark_name": payload.benchmark_name, 
            "data": raw_data, 
            "model_id": payload.model_id, 
            "tokenizer_id": payload.tokenizer_id, 
            "source": payload.source, 
            "timestamp": payload.timestamp
        }

        raw_collection = get_raw_collection()
        await raw_collection.update_one(
            {"pk": pk}, {"$set": document}, upsert=True
        )

        logger.info(f"Raw input saved with pk: {pk}")
        return SaveResponse(status="success", run_id=run_id, saved_as=pk)
    
    except Exception as e:
        logger.error(f"Error saving raw input: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save raw input: {str(e)}")

async def save_standardized_result(payload: EvaluationPayload) -> SaveResponse:
    """Save standardized benchmark result to the database."""
    try:
        run_id = payload.run_id or None
        pk = f"{payload.timestamp}-{payload.benchmark_name}-{run_id}"

        raw_data = payload.data
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                pass

        document = {
            "pk": pk, 
            "benchmark_name": payload.benchmark_name, 
            "data": raw_data, 
            "model_id": payload.model_id, 
            "tokenizer_id": payload.tokenizer_id, 
            "source": payload.source, 
            "timestamp": payload.timestamp
        }

        standardized_collection = get_standardized_collection()
        await standardized_collection.update_one(
            {"pk": pk}, {"$set": document}, upsert=True
        )

        logger.info(f"Standardized output saved with pk: {pk}")
        return SaveResponse(status="success", run_id=run_id, saved_as=pk)
    
    except Exception as e:
        logger.error(f"Error saving standardized output: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save standardized output: {str(e)}")

# -----------------------------------------------------------------------------
# Retrieval Functions
# -----------------------------------------------------------------------------

async def list_raw_results() -> List[ResultFileInfo]:
    """Get list of raw input result files."""
    try:
        raw_collection = get_raw_collection()
        cursor = raw_collection.find(
            {}, 
            {"pk": 1, "benchmark_name": 1, "model_id": 1, "tokenizer_id": 1, "source": 1, "timestamp": 1, "_id": 0}
        )
        results = [doc async for doc in cursor]
        logger.info(f"Retrieved {len(results)} raw input files")
        return results
    
    except Exception as e:
        logger.error(f"Error retrieving raw input list: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve raw input list: {str(e)}")

async def list_standardized_results() -> List[ResultFileInfo]:
    """Get list of standardized output result files."""
    try:
        standardized_collection = get_standardized_collection()
        cursor = standardized_collection.find(
            {}, 
            {"pk": 1, "benchmark_name": 1, "model_id": 1, "tokenizer_id": 1, "source": 1, "timestamp": 1, "_id": 0}
        )
        results = [doc async for doc in cursor]
        logger.info(f"Retrieved {len(results)} standardized output files")
        return results
    
    except Exception as e:
        logger.error(f"Error retrieving standardized output list: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve standardized output list: {str(e)}")

async def get_raw_result(result_name: str) -> ResultFileContent:
    """Get contents of a raw input result file."""
    try:
        raw_collection = get_raw_collection()
        document = await raw_collection.find_one({"pk": result_name})

        if not document:
            raise HTTPException(status_code=404, detail="File not found")

        logger.info(f"Retrieved raw input file: {result_name}")
        return ResultFileContent(result_name=result_name, data=document.get("data"))
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving raw input file {result_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve raw input file: {str(e)}")

async def get_standardized_result(result_name: str) -> ResultFileContent:
    """Get contents of a standardized output result file."""
    try:
        standardized_collection = get_standardized_collection()
        document = await standardized_collection.find_one({"pk": result_name})

        if not document:
            raise HTTPException(status_code=404, detail="File not found")

        logger.info(f"Retrieved standardized output file: {result_name}")
        return ResultFileContent(result_name=result_name, data=document.get("data"))
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving standardized output file {result_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve standardized output file: {str(e)}") 