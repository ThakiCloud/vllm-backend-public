from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging
from datetime import datetime
from typing import Optional, List

# Import our modules
from config import SERVER_HOST, SERVER_PORT
from database import connect_to_mongo, close_mongo_connection
from models import (
    ProjectCreate, ProjectUpdate, Project, ProjectWithStats,
    ModifiedFile,
    SyncResponse, HealthResponse, SystemStatus
)
from project_manager import (
    create_project, get_project, list_projects, update_project, delete_project,
    get_project_with_stats, sync_project_files, get_project_files
)
from file_manager import (
    create_modified_file, get_modified_file,
    update_modified_file, delete_modified_file, delete_all_modified_files,
    get_all_project_files, get_file_by_id
)

# Configure logging
logging.basicConfig(level=logging.INFO)

# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------

app = FastAPI(
    title="Benchmark Manager API",
    description="API for managing benchmark configurations and jobs with GitHub integration",
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
    await connect_to_mongo()
    logging.info("🚀 Benchmark manager started - manual sync only")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup application."""
    await close_mongo_connection()
    logging.info("🛑 Benchmark manager stopped")

# -----------------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service="benchmark-manager",
        timestamp=datetime.now()
    )

@app.get("/status", response_model=SystemStatus)
async def get_system_status():
    """Get system status."""
    projects = await list_projects()
    total_projects = len(projects)
    
    total_files = 0
    for project in projects:
        stats = (await get_project_with_stats(project.project_id)).stats
        total_files += stats.total_original_files + stats.total_modified_files
    
    return SystemStatus(
        service="Benchmark Manager",
        status="healthy",
        total_projects=total_projects,
        total_files=total_files,
        uptime="running"
    )

# -----------------------------------------------------------------------------
# Project Management APIs
# -----------------------------------------------------------------------------

@app.post("/projects", response_model=Project)
async def create_new_project(project: ProjectCreate):
    """Create a new project."""
    try:
        return await create_project(project)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/projects", response_model=List[Project])
async def get_projects():
    """Get all projects."""
    return await list_projects()

@app.get("/projects/{project_id}", response_model=ProjectWithStats)
async def get_project_details(project_id: str):
    """Get project details with statistics."""
    project = await get_project_with_stats(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.put("/projects/{project_id}", response_model=Project)
async def update_project_details(project_id: str, update: ProjectUpdate):
    """Update a project."""
    project = await update_project(project_id, update)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.delete("/projects/{project_id}")
async def delete_project_endpoint(project_id: str):
    """Delete a project and all its files."""
    success = await delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"message": "Project deleted successfully"}

# -----------------------------------------------------------------------------
# File Synchronization APIs
# -----------------------------------------------------------------------------

@app.post("/projects/{project_id}/sync", response_model=SyncResponse)
async def sync_project(project_id: str):
    """Manually trigger project file synchronization."""
    return await sync_project_files(project_id)

@app.post("/projects/sync-all", response_model=List[SyncResponse])
async def sync_all_projects_endpoint():
    """Sync all projects in parallel."""
    import asyncio
    
    projects = await list_projects()
    
    if not projects:
        return []
    
    # 모든 프로젝트를 병렬로 sync
    sync_tasks = [sync_project_files(project.project_id) for project in projects]
    results = await asyncio.gather(*sync_tasks)
    
    return results

@app.get("/projects/{project_id}/files")
async def get_project_files_endpoint(project_id: str, file_type: Optional[str] = None):
    """Get all files for a project."""
    if file_type:
        return await get_project_files(project_id, file_type)
    else:
        return await get_all_project_files(project_id)

@app.get("/projects/{project_id}/files/{file_id}")
async def get_file_details(project_id: str, file_id: str):
    """Get file details by file ID."""
    file_data = await get_file_by_id(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")
    return file_data

# -----------------------------------------------------------------------------
# Modified Files Management APIs
# -----------------------------------------------------------------------------

@app.post("/projects/{project_id}/modified-files", response_model=ModifiedFile)
async def create_modified_file_endpoint(project_id: str, file_data: ModifiedFile):
    """Create a new modified file."""
    try:
        return await create_modified_file(project_id, file_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/modified-files/{file_id}", response_model=ModifiedFile)
async def get_modified_file_details(file_id: str):
    """Get modified file details."""
    file = await get_modified_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="Modified file not found")
    return file

@app.put("/modified-files/{file_id}", response_model=ModifiedFile)
async def update_modified_file_endpoint(file_id: str, update: ModifiedFile):
    """Update a modified file."""
    file = await update_modified_file(file_id, update)
    if not file:
        raise HTTPException(status_code=404, detail="Modified file not found")
    return file

@app.delete("/modified-files/{file_id}")
async def delete_modified_file_endpoint(file_id: str):
    """Delete a specific modified file."""
    success = await delete_modified_file(file_id)
    if not success:
        raise HTTPException(status_code=404, detail="Modified file not found")
    return {"message": "Modified file deleted successfully"}

@app.delete("/projects/{project_id}/modified-files")
async def reset_project_files(project_id: str):
    """Reset project files (delete all modified files, keep originals)."""
    deleted_count = await delete_all_modified_files(project_id)
    return {"message": f"Reset completed. Deleted {deleted_count} modified files."}

# -----------------------------------------------------------------------------
# Run Application
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",  # 문자열로 전달
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=True,
        log_level="info",
    )