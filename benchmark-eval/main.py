from fastapi import FastAPI, HTTPException, BackgroundTasks
import httpx
import yaml
import logging
import base64
import asyncio
from typing import Dict, Any
from config import settings
from models import ModelRequest, EvaluationResponse, HealthResponse, DeploymentRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Benchmark Evaluation Service", version="1.0.0")

# DeploymentRequest is now imported from models

async def load_evaluate_config_template() -> str:
    """Load the evaluate.yaml template file from GitHub"""
    try:
        github_url = f"https://api.github.com/repos/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/contents/{settings.GITHUB_CONFIG_PATH}"
        
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "benchmark-eval-service"
        }
        
        # Add token if provided
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(github_url, headers=headers, timeout=30.0)
            response.raise_for_status()
            
            data = response.json()
            
            # GitHub API returns file content as base64 encoded
            if "content" in data:
                content = base64.b64decode(data["content"]).decode("utf-8")
                return content
            else:
                raise ValueError("No content found in GitHub response")
                
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch config from GitHub: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load config from GitHub: {str(e)}")
    except Exception as e:
        logger.error(f"Error loading config from GitHub: {e}")
        raise HTTPException(status_code=500, detail=f"Error loading config: {str(e)}")

def process_template(template: str, model_name: str, vllm_url: str) -> str:
    """Replace placeholders in template with actual values"""
    processed = template.replace("{model_name}", model_name).replace("{vllm_url}", vllm_url).replace("{model_name_lower}", model_name.lower())
    return processed

async def send_deployment_request(yaml_content: str, namespace: str, name: str) -> Dict[str, Any]:
    """Send deployment request to benchmark-deploy service"""
    deployment_data = {
        "yaml_content": yaml_content,
        "namespace": namespace,
        "name": name
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.BENCHMARK_DEPLOY_URL}/deploy",
                json=deployment_data,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to send deployment request: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deploy evaluation: {str(e)}"
        )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(status="ok", service="benchmark-eval")

async def execute_evaluation_after_delay(model_name: str, vllm_url: str, delay_minutes: int = None):
    """
    Execute evaluation after specified delay
    
    Args:
        model_name: Name of the model to evaluate
        vllm_url: URL of the vLLM service
        delay_minutes: Delay in minutes before execution (defaults to settings value)
    """
    try:
        if delay_minutes is None:
            delay_minutes = settings.EVALUATION_DELAY_MINUTES
            
        logger.info(f"Scheduled evaluation for model '{model_name}' will start in {delay_minutes} minutes")
        
        # Wait for specified delay
        await asyncio.sleep(delay_minutes * 60)  # Convert minutes to seconds
        
        logger.info(f"Starting evaluation for model '{model_name}' after {delay_minutes} minute delay")
        
        # Load and process the template
        template = await load_evaluate_config_template()
        processed_yaml = process_template(template, model_name.replace('_', '-').replace('.', '-'), vllm_url)
        
        # Validate YAML
        try:
            yaml.safe_load(processed_yaml)
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML generated for delayed evaluation: {e}")
            return
        
        # Send deployment request
        deployment_response = await send_deployment_request(
            yaml_content=processed_yaml,
            namespace="default",
            name="New vLLM Evaluation"
        )
        
        logger.info(f"Evaluation deployment completed for model '{model_name}': {deployment_response}")
        
    except Exception as e:
        logger.error(f"Error in delayed evaluation for model '{model_name}': {e}")

@app.post("/evaluate", response_model=EvaluationResponse)
async def create_evaluation(request: ModelRequest, background_tasks: BackgroundTasks):
    """
    Schedule a new vLLM evaluation deployment to run in 10 minutes
    
    Args:
        request: ModelRequest containing model_name and vllm_url
        background_tasks: FastAPI background tasks
        
    Returns:
        Confirmation that evaluation has been scheduled
    """
    try:
        # Add the evaluation task to background tasks with configured delay
        background_tasks.add_task(
            execute_evaluation_after_delay,
            request.model_name,
            request.vllm_url
        )
        
        delay_minutes = settings.EVALUATION_DELAY_MINUTES
        logger.info(f"Evaluation scheduled for model '{request.model_name}' - will execute in {delay_minutes} minutes")
        
        return EvaluationResponse(
            message=f"Evaluation deployment scheduled successfully - will execute in {delay_minutes} minutes",
            model_name=request.model_name,
            vllm_url=request.vllm_url,
            deployment_response={"status": "scheduled", "delay_minutes": delay_minutes}
        )
        
    except Exception as e:
        logger.error(f"Error scheduling evaluation request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004, reload=True) 