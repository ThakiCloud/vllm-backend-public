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
                        result = contents if isinstance(contents, list) else []
                        return result
                    elif response.status == 404:
                        logging.warning(f"Folder not found: /{folder_path}")
                        return []
                    else:
                        error_text = await response.text()
                        logging.error(f"Failed to fetch {folder_path}: {response.status} - {error_text}")
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

    async def fetch_all_files(self, benchmark_folder: str, _unused_param: str = None) -> List[Dict[str, Any]]:
        """Fetch all benchmark files from benchmark type folders with parallel processing."""
        import asyncio
        all_files = []
        
        try:
            # 1. 지정된 폴더의 서브폴더들 조회 (벤치마크 종류별 폴더)
            benchmark_types = await self.fetch_folder_contents(benchmark_folder)
            
            # 2. 모든 벤치마크 타입별 폴더를 병렬로 처리
            benchmark_folders = [bt for bt in benchmark_types if bt.get("type") == "dir"]
            
            if not benchmark_folders:
                logging.warning(f"No benchmark folders found in {benchmark_folder}")
                return all_files
            
            logging.info(f"⚡ Processing {len(benchmark_folders)} benchmark folders in parallel")
            
            # 모든 폴더의 내용을 병렬로 가져오기
            folder_tasks = [self.fetch_folder_contents(bf["path"]) for bf in benchmark_folders]
            folder_results = await asyncio.gather(*folder_tasks, return_exceptions=True)
            
            # 3. 모든 파일들을 수집하여 병렬로 content 가져오기
            all_file_tasks = []
            file_metadata = []
            
            for i, files_in_type in enumerate(folder_results):
                if isinstance(files_in_type, Exception):
                    logging.error(f"Error fetching folder {benchmark_folders[i]['path']}: {files_in_type}")
                    continue
                    
                benchmark_type = benchmark_folders[i]
                
                for file_item in files_in_type:
                    if file_item.get("type") == "file":
                        file_name = file_item.get("name", "")
                        
                        # YAML 파일 (job) 또는 Config 파일인지 확인
                        if any(file_name.endswith(ext) for ext in SUPPORTED_JOB_EXTENSIONS):
                            file_type = "job"
                        elif any(file_name.endswith(ext) for ext in SUPPORTED_CONFIG_EXTENSIONS):
                            file_type = "config"
                        else:
                            continue
                        
                        # 파일 content 가져오기 작업 추가
                        all_file_tasks.append(self.fetch_file_content(file_item["path"]))
                        file_metadata.append({
                            "file_path": file_item["path"],
                            "file_type": file_type,
                            "benchmark_type": benchmark_type["name"]
                        })
            
            # 4. 모든 파일 content를 병렬로 가져오기
            if all_file_tasks:
                logging.info(f"⚡ Fetching {len(all_file_tasks)} files in parallel")
                file_results = await asyncio.gather(*all_file_tasks, return_exceptions=True)
                
                # 5. 결과 조합
                yaml_files = []
                config_files = []
                
                for i, file_content in enumerate(file_results):
                    if isinstance(file_content, Exception):
                        logging.error(f"Error fetching file {file_metadata[i]['file_path']}: {file_content}")
                        continue
                        
                    if file_content:
                        file_data = {
                            "file_path": file_metadata[i]["file_path"],
                            "file_type": file_metadata[i]["file_type"],
                            "content": file_content["content"],
                            "sha": file_content["sha"],
                            "last_modified": datetime.now(),
                            "benchmark_type": file_metadata[i]["benchmark_type"]
                        }
                        
                        if file_metadata[i]["file_type"] == "job":
                            yaml_files.append(file_data)
                        else:
                            config_files.append(file_data)
                
                # 6. YAML 파일들을 먼저 추가, 그 다음 Config 파일들 추가
                all_files.extend(yaml_files)
                all_files.extend(config_files)
                
                logging.info(f"✅ Successfully fetched {len(all_files)} files ({len(yaml_files)} jobs, {len(config_files)} configs)")
                    
        except Exception as e:
            logging.error(f"Error fetching benchmark files from {benchmark_folder}: {e}")
            
        return all_files

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------

def create_github_client(repo_url: str, token: str) -> GitHubClient:
    """Create a GitHub client instance."""
    return GitHubClient(repo_url, token) 