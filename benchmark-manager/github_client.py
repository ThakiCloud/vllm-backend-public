import aiohttp
import base64
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from config import GITHUB_API_BASE, SUPPORTED_CONFIG_EXTENSIONS, SUPPORTED_JOB_EXTENSIONS

# -----------------------------------------------------------------------------
# GitHub API Client
# -----------------------------------------------------------------------------

class GitHubClient:
    def __init__(self, repo_url: str, token: str):
        self.repo_url = repo_url
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "benchmark-manager-service"
        }
        if token:
            self.headers["Authorization"] = f"token {token}"

    async def fetch_folder_contents(self, folder_path: str) -> List[Dict[str, Any]]:
        """Fetch contents of a folder from GitHub repository."""
        try:
            url = f"{self.repo_url}/contents/{folder_path}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        contents = await response.json()
                        return contents if isinstance(contents, list) else []
                    elif response.status == 404:
                        logging.warning(f"Folder not found: /{folder_path}")
                        return []
                    else:
                        logging.error(f"Failed to fetch {folder_path}: {response.status}")
                        return []
        except Exception as e:
            logging.error(f"Error fetching folder contents for {folder_path}: {e}")
            return []

    async def fetch_file_content(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Fetch content of a specific file from GitHub repository."""
        try:
            url = f"{self.repo_url}/contents/{file_path}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        file_info = await response.json()
                        if file_info.get("type") == "file":
                            # Decode base64 content
                            content = base64.b64decode(file_info["content"]).decode('utf-8')
                            return {
                                "path": file_path,
                                "content": content,
                                "sha": file_info["sha"],
                                "last_modified": datetime.now().isoformat()
                            }
                    else:
                        logging.error(f"Failed to fetch file {file_path}: {response.status}")
                        return None
        except Exception as e:
            logging.error(f"Error fetching file content for {file_path}: {e}")
            return None

    async def fetch_config_files(self, config_folder: str) -> List[Dict[str, Any]]:
        """Fetch all config files from the specified folder."""
        files_data = []
        try:
            contents = await self.fetch_folder_contents(config_folder)
            
            for item in contents:
                if (item.get("type") == "file" and 
                    item.get("name") and
                    any(item["name"].endswith(ext) for ext in SUPPORTED_CONFIG_EXTENSIONS)):
                    
                    file_content = await self.fetch_file_content(item["path"])
                    if file_content:
                        # Store original text content without parsing
                        files_data.append({
                            "file_path": item["path"],
                            "file_type": "config",
                            "content": file_content["content"],  # Original text content
                            "sha": file_content["sha"],
                            "last_modified": datetime.now()
                        })
                            
        except Exception as e:
            logging.error(f"Error fetching config files: {e}")
            
        return files_data

    async def fetch_job_files(self, job_folder: str) -> List[Dict[str, Any]]:
        """Fetch all job files from the specified folder."""
        files_data = []
        try:
            contents = await self.fetch_folder_contents(job_folder)
            
            for item in contents:
                if (item.get("type") == "file" and 
                    item.get("name") and
                    any(item["name"].endswith(ext) for ext in SUPPORTED_JOB_EXTENSIONS)):
                    
                    file_content = await self.fetch_file_content(item["path"])
                    if file_content:
                        # Store original text content without parsing
                        files_data.append({
                            "file_path": item["path"],
                            "file_type": "job",
                            "content": file_content["content"],  # Original text content
                            "sha": file_content["sha"],
                            "last_modified": datetime.now()
                        })
                            
        except Exception as e:
            logging.error(f"Error fetching job files: {e}")
            
        return files_data

    async def fetch_vllm_files(self, vllm_values_path: str) -> List[Dict[str, Any]]:
        """Fetch all custom-values*.yaml files from the specified folder."""
        files_data = []
        try:
            contents = await self.fetch_folder_contents(vllm_values_path)
            
            for item in contents:
                if (item.get("type") == "file" and 
                    item.get("name") and
                    item["name"].startswith("custom-values") and 
                    item["name"].endswith(".yaml")):
                    
                    file_content = await self.fetch_file_content(item["path"])
                    if file_content:
                        # Store original text content without parsing
                        files_data.append({
                            "file_path": item["path"],
                            "file_type": "vllm",
                            "content": file_content["content"],  # Original text content
                            "sha": file_content["sha"],
                            "last_modified": datetime.now()
                        })
                            
        except Exception as e:
            logging.error(f"Error fetching VLLM files: {e}")
            
        return files_data

    async def fetch_all_files(self, config_folder: str, job_folder: str) -> List[Dict[str, Any]]:
        """Fetch all config and job files."""
        all_files = []
        
        # Fetch config files
        config_files = await self.fetch_config_files(config_folder)
        all_files.extend(config_files)
        
        # Fetch job files
        job_files = await self.fetch_job_files(job_folder)
        all_files.extend(job_files)
        
        return all_files

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------

def create_github_client(repo_url: str, token: str) -> GitHubClient:
    """Create a GitHub client instance."""
    return GitHubClient(repo_url, token) 