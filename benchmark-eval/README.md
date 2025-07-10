# Benchmark Evaluation Service

FastAPI-based service for managing vLLM model evaluations. This service receives model configuration requests, processes evaluation templates, and forwards deployment requests to the benchmark-deploy service.

## Features

- **Scheduled Evaluation**: Schedules evaluations to run 10 minutes after request
- **Model Configuration Processing**: Accepts model name and vLLM URL configurations
- **Dynamic Template Loading**: Fetches evaluation config templates from GitHub in real-time
- **Template Processing**: Processes evaluation config templates with dynamic placeholders
- **Background Task Processing**: Uses FastAPI BackgroundTasks for delayed execution
- **Deployment Integration**: Forwards processed configurations to benchmark-deploy service
- **Health Monitoring**: Built-in health check endpoints
- **Error Handling**: Comprehensive error handling and logging

## API Endpoints

### POST /evaluate
Schedules a new vLLM evaluation deployment to run after the configured delay (default: 10 minutes), fetching the latest config from GitHub.

**Request Body:**
```json
{
    "model_name": "your-model-name",
    "vllm-url": "http://your-vllm-service:8000"
}
```

**Response:**
```json
{
    "message": "Evaluation deployment scheduled successfully - will execute in 10 minutes",
    "model_name": "your-model-name",
    "vllm_url": "http://your-vllm-service:8000",
    "deployment_response": {
        "status": "scheduled",
        "delay_minutes": 10
    }
}
```

**Note:** The `delay_minutes` value in the response reflects the current `EVALUATION_DELAY_MINUTES` setting.

### GET /
Health check endpoint.

**Response:**
```json
{
    "status": "ok",
    "service": "benchmark-eval"
}
```

## Configuration

The service uses environment variables for configuration:

- `BENCHMARK_DEPLOY_URL`: URL of the benchmark-deploy service (default: "http://benchmark-deploy:8002")
- `HOST`: Server host (default: "0.0.0.0")
- `PORT`: Server port (default: 8004)
- `LOG_LEVEL`: Logging level (default: "INFO")

### GitHub Configuration

- `GITHUB_OWNER`: GitHub repository owner (default: "thakicloud")
- `GITHUB_REPO`: GitHub repository name (default: "mlflow-vllm")
- `GITHUB_CONFIG_PATH`: Path to the config file in the repository (default: "evaluate/evaluate.config")
- `GITHUB_TOKEN`: GitHub personal access token (optional for public repositories)

### Evaluation Configuration

- `EVALUATION_DELAY_MINUTES`: Delay in minutes before evaluation execution (default: 10)

## Template System

The service dynamically fetches template files from GitHub (`evaluate/evaluate.config`) that contain placeholders:

- `{model_name}`: Replaced with the provided model name
- `{vllm-url}`: Replaced with the provided vLLM URL

Each time the `/evaluate` endpoint is called, the service schedules a background task that will execute in 10 minutes, fetching the latest version of the configuration file from GitHub at execution time, ensuring always up-to-date templates.

## Dependencies

- FastAPI: Web framework
- Uvicorn: ASGI server
- Pydantic: Data validation
- httpx: HTTP client
- PyYAML: YAML processing

## Development

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the service:
```bash
uvicorn main:app --host 0.0.0.0 --port 8004 --reload
```

3. Access the API documentation at `http://localhost:8004/docs`

### Docker Development

1. Build the Docker image:
```bash
docker build -t benchmark-eval .
```

2. Run the container:
```bash
docker run -p 8004:8004 \
  -e GITHUB_OWNER=thakicloud \
  -e GITHUB_REPO=mlflow-vllm \
  -e GITHUB_CONFIG_PATH=evaluate/evaluate.config \
  -e EVALUATION_DELAY_MINUTES=10 \
  benchmark-eval
```

## Deployment

The service is designed to be deployed on Kubernetes using the provided deployment configuration.

### Environment Variables

Set the following environment variables in your deployment:

- `BENCHMARK_DEPLOY_URL`: URL of the benchmark-deploy service
- `GITHUB_OWNER`: GitHub repository owner (optional, defaults to "thakicloud")
- `GITHUB_REPO`: GitHub repository name (optional, defaults to "mlflow-vllm")
- `GITHUB_CONFIG_PATH`: Path to config file in repository (optional, defaults to "evaluate/evaluate.config")
- `GITHUB_TOKEN`: GitHub token for private repositories (optional)
- `EVALUATION_DELAY_MINUTES`: Delay in minutes before evaluation execution (optional, defaults to 10)

### Health Checks

The service includes health check endpoints for Kubernetes:

- Liveness probe: `GET /`
- Readiness probe: `GET /`

## Usage Example

```bash
# Schedule a new evaluation (will execute after configured delay)
curl -X POST "http://localhost:8004/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "my-llama-model",
    "vllm-url": "http://my-vllm-service:8000"
  }'

# Health check
curl "http://localhost:8004/"
```

## Error Handling

The service provides detailed error responses:

- **400 Bad Request**: Invalid input data or YAML generation errors
- **500 Internal Server Error**: Template loading errors or deployment service failures

## Logging

The service logs all important events including:

- Request processing
- GitHub API calls for template fetching
- Template processing
- Deployment requests
- Error conditions

Log level can be configured using the `LOG_LEVEL` environment variable.

## ⏰ Evaluation Scheduling

The service implements a **configurable delay** for all evaluation requests (default: 10 minutes):

1. **POST /evaluate** immediately returns confirmation that the evaluation has been scheduled
2. **Background task** waits for the configured delay using `asyncio.sleep()`
3. **GitHub fetch** happens at execution time to get the latest config
4. **Template processing** and **deployment request** are sent to benchmark-deploy service

### Why delay evaluation?

- Allows time for any last-minute configuration changes
- Prevents immediate resource consumption
- Provides buffer time for cancellation if needed (future feature)
- Configurable delay allows adaptation to different use cases

### Configuring Delay

Set the `EVALUATION_DELAY_MINUTES` environment variable:

```bash
# 5 minute delay
EVALUATION_DELAY_MINUTES=5

# 30 minute delay  
EVALUATION_DELAY_MINUTES=30

# 1 hour delay
EVALUATION_DELAY_MINUTES=60
```

### Monitoring

Check application logs to monitor:
- When evaluations are scheduled: `"Evaluation scheduled for model 'X' - will execute in N minutes"`
- When evaluations start: `"Starting evaluation for model 'X' after N minute delay"`
- When evaluations complete: `"Evaluation deployment completed for model 'X'"` 