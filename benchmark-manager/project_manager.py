import asyncio
import logging
from typing import List, Optional
from datetime import datetime
from uuid import uuid4

from database import get_projects_collection, get_original_files_collection, get_modified_files_collection
from github_client import create_github_client
from models import Project, ProjectCreate, ProjectUpdate, ProjectWithStats, ProjectStats, SyncResponse, OriginalFile

# -----------------------------------------------------------------------------
# Project Management
# -----------------------------------------------------------------------------

async def create_project(project_data: ProjectCreate) -> Project:
    """Create a new project."""
    collection = get_projects_collection()
    
    project_id = str(uuid4())
    now = datetime.now()
    
    logging.info(f"Creating project with data: {project_data.dict()}")
    
    project_doc = {
        "project_id": project_id,
        "name": project_data.name,
        "project_type": project_data.project_type or "benchmark",
        "repository_url": project_data.repository_url,
        "github_token": project_data.github_token,
        "config_path": project_data.config_path or "config",
        "job_path": project_data.job_path or "job",
        "vllm_values_path": project_data.vllm_values_path or "",
        "created_at": now,
        "updated_at": now,
        "last_sync": None
    }
    
    await collection.insert_one(project_doc)
    
    project = Project(**project_doc)
    logging.info(f"Created project {project_id} - manual sync only")
    
    return project

async def get_project(project_id: str) -> Optional[Project]:
    """Get a project by ID."""
    collection = get_projects_collection()
    project_doc = await collection.find_one({"project_id": project_id}, {"_id": 0})
    
    if project_doc:
        # 기존 프로젝트에 새로운 필드가 없는 경우 기본값 설정
        if "project_type" not in project_doc:
            project_doc["project_type"] = "benchmark"
        if "vllm_values_path" not in project_doc:
            project_doc["vllm_values_path"] = ""
        return Project(**project_doc)
    return None

async def list_projects() -> List[Project]:
    """List all projects."""
    collection = get_projects_collection()
    cursor = collection.find({}, {"_id": 0})
    projects = []
    
    async for doc in cursor:
        # 기존 프로젝트에 새로운 필드가 없는 경우 기본값 설정
        if "project_type" not in doc:
            doc["project_type"] = "benchmark"
        if "vllm_values_path" not in doc:
            doc["vllm_values_path"] = ""
        projects.append(Project(**doc))
    
    return projects

async def update_project(project_id: str, update_data: ProjectUpdate) -> Optional[Project]:
    """Update a project."""
    collection = get_projects_collection()
    
    update_dict = {}
    for field, value in update_data.dict(exclude_unset=True).items():
        if value is not None:
            update_dict[field] = value
    
    if not update_dict:
        return await get_project(project_id)
    
    update_dict["updated_at"] = datetime.now()
    
    result = await collection.update_one(
        {"project_id": project_id},
        {"$set": update_dict}
    )
    
    if result.modified_count > 0:
        return await get_project(project_id)
    return None

async def delete_project(project_id: str) -> bool:
    """Delete a project and all its files."""
    projects_collection = get_projects_collection()
    files_collection = get_original_files_collection()
    
    await files_collection.delete_many({"project_id": project_id})
    
    result = await projects_collection.delete_one({"project_id": project_id})
    
    return result.deleted_count > 0

async def get_project_with_stats(project_id: str) -> Optional[ProjectWithStats]:
    """Get project with statistics."""
    project = await get_project(project_id)
    if not project:
        return None
    
    stats = await get_project_stats(project_id)
    
    return ProjectWithStats(project=project, stats=stats)

async def get_project_stats(project_id: str) -> ProjectStats:
    """Get project statistics."""
    files_collection = get_original_files_collection()
    modified_files_collection = get_modified_files_collection()
    
    total_files = await files_collection.count_documents({"project_id": project_id})
    
    config_files = await files_collection.count_documents({
        "project_id": project_id, 
        "file_type": "config"
    })
    job_files = await files_collection.count_documents({
        "project_id": project_id, 
        "file_type": "job"
    })
    
    project = await get_project(project_id)
    last_sync = project.last_sync if project else None
    
    # Count modified files properly
    modified_files = await modified_files_collection.count_documents({"project_id": project_id})
    
    return ProjectStats(
        total_original_files=total_files,
        total_modified_files=modified_files,
        config_files=config_files,
        job_files=job_files,
        last_sync=last_sync
    )

# -----------------------------------------------------------------------------
# File Synchronization
# -----------------------------------------------------------------------------



async def sync_project_files(project_id: str) -> SyncResponse:
    """Sync files from GitHub for a specific project."""
    project = await get_project(project_id)
    if not project:
        return SyncResponse(
            status="error",
            message="Project not found",
            synced_files=0,
            project_id=project_id
        )
        
    try:
        github_client = create_github_client(project.repository_url, project.github_token)
        
        # 프로젝트 타입에 따라 다른 파일 fetch 로직 사용
        if project.project_type == "vllm":
            # VLLM 프로젝트의 경우 custom-values*.yaml 파일들을 찾음
            all_files = await github_client.fetch_vllm_files(project.vllm_values_path)
        else:
            # Benchmark 프로젝트의 경우 벤치마크 폴더에서 종류별 파일들 가져오기
            all_files = await github_client.fetch_all_files(project.config_path)
        
        files_collection = get_original_files_collection()
        
        # 기존 파일들을 file_path를 키로 하는 딕셔너리로 조회
        existing_files = {}
        existing_cursor = files_collection.find({"project_id": project_id})
        async for doc in existing_cursor:
            existing_files[doc["file_path"]] = doc
        
        synced_count = 0
        updated_count = 0
        new_count = 0
        
        # GitHub에서 가져온 파일 경로들을 추적
        github_file_paths = set()
        
        for file_data in all_files:
            file_path = file_data["file_path"]
            github_file_paths.add(file_path)
            
            # 기존 파일이 있으면 기존 file_id 사용, 없으면 새 file_id 생성
            if file_path in existing_files:
                file_id = existing_files[file_path]["file_id"]
                updated_count += 1
            else:
                file_id = str(uuid4())
                new_count += 1
            
            file_doc = {
                "file_id": file_id,
                "project_id": project_id,
                "file_path": file_path,
                "file_type": file_data["file_type"],
                "content": file_data["content"],
                "sha": file_data["sha"],
                "last_modified": file_data["last_modified"],
                "synced_at": datetime.now()
            }
            
            await files_collection.update_one(
                {
                    "project_id": project_id,
                    "file_path": file_path
                },
                {"$set": file_doc},
                upsert=True
            )
            synced_count += 1
        
        # GitHub에 없는 기존 파일들 삭제
        deleted_count = 0
        for existing_path in existing_files.keys():
            if existing_path not in github_file_paths:
                await files_collection.delete_one({
                    "project_id": project_id,
                    "file_path": existing_path
                })
                deleted_count += 1
        
        projects_collection = get_projects_collection()
        await projects_collection.update_one(
            {"project_id": project_id},
            {"$set": {"last_sync": datetime.now()}}
        )
        
        logging.info(f"Synced {synced_count} files for project {project_id}: {new_count} new, {updated_count} updated, {deleted_count} deleted")
        
        return SyncResponse(
            status="success",
            message=f"Successfully synced {synced_count} files ({new_count} new, {updated_count} updated, {deleted_count} deleted)",
            synced_files=synced_count,
            project_id=project_id
        )
        
    except Exception as e:
        logging.error(f"Error syncing files for project {project_id}: {e}")
        return SyncResponse(
            status="error",
            message=f"Sync failed: {str(e)}",
            synced_files=0,
            project_id=project_id
        )

async def get_project_files(project_id: str, file_type: Optional[str] = None):
    """Get all files (original and modified) for a project with optional file_type filter."""
    original_files_collection = get_original_files_collection()
    modified_files_collection = get_modified_files_collection()
    
    all_files = []
    
    # Query for original files
    original_query = {"project_id": project_id}
    if file_type:
        original_query["file_type"] = file_type
    
    original_cursor = original_files_collection.find(original_query, {"_id": 0})
    
    async for doc in original_cursor:
        file_data = dict(doc)
        file_data["source"] = "original"  # Mark as original file
        
        # file_path에서 benchmark_type과 file_name 추출
        file_path = file_data.get("file_path", "")
        path_parts = file_path.split("/")
        file_data["benchmark_type"] = path_parts[-2] if len(path_parts) > 1 else ""
        file_data["file_name"] = path_parts[-1] if path_parts else file_path
        
        all_files.append(file_data)
    
    # Query for modified files
    modified_query = {"project_id": project_id}
    if file_type:
        modified_query["file_type"] = file_type
    
    modified_cursor = modified_files_collection.find(modified_query, {"_id": 0})
    
    async for doc in modified_cursor:
        file_data = dict(doc)
        file_data["source"] = "modified"  # Mark as modified file
        
        # file_path에서 benchmark_type과 file_name 추출
        file_path = file_data.get("file_path", "")
        path_parts = file_path.split("/")
        file_data["benchmark_type"] = path_parts[-2] if len(path_parts) > 1 else ""
        file_data["file_name"] = path_parts[-1] if path_parts else file_path
        
        all_files.append(file_data)
    
    return all_files

# -----------------------------------------------------------------------------
# Background Polling (DISABLED - Manual sync only)
# ----------------------------------------------------------------------------- 