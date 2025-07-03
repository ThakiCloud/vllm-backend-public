from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# Import our modules
from config import SERVER_HOST, SERVER_PORT
from models import (
    DeploymentRequest, DeploymentResponse, LogRequest, LogResponse,
    DeleteRequest, DeleteResponse, JobStatusResponse,
    HealthResponse, SystemStatus,
    TerminalSessionRequest, TerminalSessionResponse, TerminalSessionInfo, TerminalSessionListResponse
)
from deployer_manager import deployer_manager
from terminal_manager import terminal_manager
from database import close_mongo_connection

# Configure logging
logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------

app = FastAPI(
    title="Benchmark Deployer API",
    description="API for deploying and managing benchmark jobs on Kubernetes with real-time terminal access",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Startup/Shutdown Events
# -----------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    """Initialize application."""
    await deployer_manager.initialize()

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup application."""
    await close_mongo_connection()

# -----------------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    health_info = await deployer_manager.get_system_health()
    
    return HealthResponse(
        status="healthy" if health_info["service_status"] == "healthy" else "unhealthy",
        service="benchmark-deployer",
        timestamp=datetime.now(),
        kubernetes_connected=health_info["kubernetes_connected"]
    )

@app.get("/status", response_model=SystemStatus)
async def get_system_status():
    """Get system status."""
    health_info = await deployer_manager.get_system_health()
    
    return SystemStatus(
        service="Benchmark Deployer",
        status=health_info["service_status"],
        kubernetes_version=health_info["kubernetes_version"],
        active_deployments=health_info["active_deployments"],
        uptime="running"
    )

# -----------------------------------------------------------------------------
# Deployment APIs
# -----------------------------------------------------------------------------

@app.post("/deploy", response_model=DeploymentResponse)
async def deploy_yaml(request: DeploymentRequest):
    """Deploy Kubernetes resources from YAML content."""
    try:
        return await deployer_manager.deploy_yaml(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/delete", response_model=DeleteResponse)
async def delete_yaml(request: DeleteRequest):
    """Delete Kubernetes resources from YAML content."""
    try:
        return await deployer_manager.delete_yaml(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/deployments")
async def list_deployments():
    """List active deployments."""
    try:
        return await deployer_manager.list_active_deployments()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Job Management APIs
# -----------------------------------------------------------------------------

@app.get("/jobs/{job_name}/status", response_model=JobStatusResponse)
async def get_job_status(job_name: str, namespace: str = "default"):
    """Get job status."""
    try:
        return await deployer_manager.get_job_status(job_name, namespace)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/jobs/{job_name}/logs")
async def get_job_logs_simple(job_name: str, namespace: str = "default", tail_lines: int = 100):
    """Get job logs with simple parameters."""
    try:
        request = LogRequest(
            job_name=job_name,
            namespace=namespace,
            tail_lines=tail_lines
        )
        return await deployer_manager.get_job_logs(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/jobs/logs", response_model=LogResponse)
async def get_job_logs(request: LogRequest):
    """Get logs from a job with detailed options."""
    try:
        return await deployer_manager.get_job_logs(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# -----------------------------------------------------------------------------
# Terminal APIs 🔥
# -----------------------------------------------------------------------------

@app.post("/terminal/create", response_model=TerminalSessionResponse)
async def create_terminal_session(request: TerminalSessionRequest):
    """Create a new terminal session for a job."""
    try:
        return await deployer_manager.create_terminal_session(request, SERVER_HOST, SERVER_PORT)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/jobs/{job_name}/terminal", response_model=TerminalSessionResponse)
async def create_job_terminal(
    job_name: str,
    namespace: str = "default",
    pod_name: Optional[str] = None,
    container_name: Optional[str] = None,
    shell: str = "/bin/bash"
):
    """Create terminal session for a specific job (convenience endpoint)."""
    try:
        request = TerminalSessionRequest(
            job_name=job_name,
            namespace=namespace,
            pod_name=pod_name,
            container_name=container_name,
            shell=shell
        )
        return await deployer_manager.create_terminal_session(request, SERVER_HOST, SERVER_PORT)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/terminal/sessions", response_model=TerminalSessionListResponse)
async def list_terminal_sessions(job_name: Optional[str] = None):
    """List terminal sessions."""
    try:
        return await deployer_manager.list_terminal_sessions(job_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/terminal/{session_id}", response_model=TerminalSessionInfo)
async def get_terminal_session(session_id: str):
    """Get terminal session information."""
    try:
        session = await deployer_manager.get_terminal_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Terminal session not found")
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/terminal/{session_id}")
async def stop_terminal_session(session_id: str):
    """Stop a terminal session."""
    try:
        await deployer_manager.stop_terminal_session(session_id)
        return {"message": f"Terminal session {session_id} stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/terminal/job/{job_name}")
async def stop_job_terminal_sessions(job_name: str):
    """Stop all terminal sessions for a job."""
    try:
        await deployer_manager.stop_job_terminal_sessions(job_name)
        return {"message": f"All terminal sessions for job '{job_name}' stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.websocket("/terminal/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for terminal access."""
    await websocket.accept()
    
    try:
        # Start terminal session
        await terminal_manager.start_session(session_id, websocket)
        
    except WebSocketDisconnect:
        logging.info(f"WebSocket disconnected for terminal session {session_id}")
    except Exception as e:
        logging.error(f"Terminal WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Terminal error: {str(e)}"
            })
        except:
            pass
    finally:
        # Clean up session
        try:
            await terminal_manager.stop_session(session_id)
        except:
            pass

# -----------------------------------------------------------------------------
# Development and Testing
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT) 