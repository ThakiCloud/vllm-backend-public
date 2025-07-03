import logging
from typing import List, Optional
from datetime import datetime
from uuid import uuid4

from database import get_modified_files_collection, get_original_files_collection
from models import ModifiedFile, OriginalFile

# -----------------------------------------------------------------------------
# Modified Files Management
# -----------------------------------------------------------------------------

async def create_modified_file(project_id: str, file_data: ModifiedFile) -> ModifiedFile:
    """Create a new modified file."""
    collection = get_modified_files_collection()
    
    file_id = str(uuid4())
    now = datetime.now()
    
    modified_doc = {
        "file_id": file_id,
        "project_id": project_id,
        "modified": True,
        "file_type": file_data.file_type,
        "file_path": file_data.file_path,
        "content": file_data.content,
        "created_at": now,
        "modified_at": now
    }
    
    await collection.insert_one(modified_doc)
    
    return ModifiedFile(**modified_doc)

async def get_modified_file(file_id: str) -> Optional[ModifiedFile]:
    """Get a modified file by ID."""
    collection = get_modified_files_collection()
    file_doc = await collection.find_one({"file_id": file_id}, {"_id": 0})
    
    if file_doc:
        return ModifiedFile(**file_doc)
    return None

async def update_modified_file(file_id: str, update_data: ModifiedFile) -> Optional[ModifiedFile]:
    """Update a modified file."""
    collection = get_modified_files_collection()
    
    update_dict = {}
    for field, value in update_data.dict(exclude_unset=True).items():
        if value is not None and field != "file_id":  # Don't update file_id
            update_dict[field] = value
    
    if not update_dict:
        return await get_modified_file(file_id)
    
    update_dict["modified_at"] = datetime.now()
    
    result = await collection.update_one(
        {"file_id": file_id},
        {"$set": update_dict}
    )
    
    if result.modified_count > 0:
        return await get_modified_file(file_id)
    return None

async def delete_modified_file(file_id: str) -> bool:
    """Delete a specific modified file."""
    collection = get_modified_files_collection()
    
    result = await collection.delete_one({"file_id": file_id})
    
    if result.deleted_count > 0:
        logging.info(f"Deleted modified file: {file_id}")
        return True
    return False

async def delete_all_modified_files(project_id: str) -> int:
    """Delete all modified files for a project (초기화 기능)."""
    collection = get_modified_files_collection()
    
    result = await collection.delete_many({"project_id": project_id})
    
    logging.info(f"Deleted {result.deleted_count} modified files for project {project_id}")
    return result.deleted_count

# -----------------------------------------------------------------------------
# Original Files Management
# -----------------------------------------------------------------------------

async def get_original_file_by_id(file_id: str) -> Optional[OriginalFile]:
    """Get an original file by ID."""
    collection = get_original_files_collection()
    file_doc = await collection.find_one({"file_id": file_id}, {"_id": 0})
    
    if file_doc:
        return OriginalFile(**file_doc)
    return None

# -----------------------------------------------------------------------------
# Independent File Operations
# -----------------------------------------------------------------------------

async def get_file_by_id(file_id: str):
    """Get a file by ID - searches both original and modified files."""
    # First try to find in original files
    original_file = await get_original_file_by_id(file_id)
    if original_file:
        return {
            "file_type": "original",
            "file": original_file
        }
    
    # If not found, try modified files
    modified_file = await get_modified_file(file_id)
    if modified_file:
        return {
            "file_type": "modified", 
            "file": modified_file
        }
    
    return None

async def get_all_project_files(project_id: str):
    """Get all files (original and modified) for a project - independently managed."""
    original_files_collection = get_original_files_collection()
    modified_files_collection = get_modified_files_collection()
    
    all_files = []
    
    # Get original files
    original_cursor = original_files_collection.find({"project_id": project_id}, {"_id": 0})
    
    async for doc in original_cursor:
        file_data = dict(doc)
        file_data["source"] = "original"  # Mark as original file
        all_files.append(file_data)
    
    # Get modified files
    modified_cursor = modified_files_collection.find({"project_id": project_id}, {"_id": 0})
    
    async for doc in modified_cursor:
        file_data = dict(doc)
        file_data["source"] = "modified"  # Mark as modified file
        all_files.append(file_data)
    
    return all_files 