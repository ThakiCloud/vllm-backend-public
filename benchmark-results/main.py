"""FastAPI application for benchmark results storage service."""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import List

from config import (
    APP_TITLE, APP_DESCRIPTION, APP_VERSION, LOG_LEVEL, LOG_FORMAT,
    CORS_ORIGINS, CORS_CREDENTIALS, CORS_METHODS, CORS_HEADERS
)
from database import connect_to_mongo, close_mongo_connection, check_mongo_health
from models import EvaluationPayload, SaveResponse, HealthResponse, ResultFileInfo, ResultFileContent
from results_manager import (
    save_raw_result, save_standardized_result,
    list_raw_results, list_standardized_results,
    get_raw_result, get_standardized_result
)

# -----------------------------------------------------------------------------
# Logging configuration
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# FastAPI application setup
# -----------------------------------------------------------------------------

app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    on_startup=[connect_to_mongo],
    on_shutdown=[close_mongo_connection],
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_CREDENTIALS,
    allow_methods=CORS_METHODS,
    allow_headers=CORS_HEADERS,
)

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

@app.post("/raw_input", response_model=SaveResponse)
async def post_raw_input(payload: EvaluationPayload):
    """Receive and persist raw benchmark results."""
    return await save_raw_result(payload)

@app.post("/standardized_output", response_model=SaveResponse)
async def post_standardized_output(payload: EvaluationPayload):
    """Receive and persist standardized/parsed benchmark results."""
    return await save_standardized_result(payload)

@app.get("/raw_input", response_model=List[ResultFileInfo])
async def list_raw_input_files():
    """Return a list of raw input result files available on the server."""
    return await list_raw_results()

@app.get("/standardized_output", response_model=List[ResultFileInfo])
async def list_standardized_output_files():
    """Return a list of standardized output files available on the server."""
    return await list_standardized_results()

@app.get("/raw_input/{result_name}", response_model=ResultFileContent)
async def get_raw_input_file(result_name: str):
    """Return the contents of a raw input result file."""
    return await get_raw_result(result_name)

@app.get("/standardized_output/{result_name}", response_model=ResultFileContent)
async def get_standardized_output_file(result_name: str):
    """Return the contents of a standardized output result file."""
    return await get_standardized_result(result_name)

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for monitoring and k8s probes."""
    mongo_healthy = await check_mongo_health()
    mongo_status = "connected" if mongo_healthy else "disconnected"
    
    return HealthResponse(status="ok", mongodb_status=mongo_status)