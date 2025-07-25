import uuid
import asyncio
import logging
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, Any
from motor.motor_asyncio import AsyncIOMotorCollection

from database import get_database
from models import QueueRequest, QueueResponse, QueueStatusResponse, VLLMConfig, BenchmarkJobConfig, SchedulingConfig
from vllm_manager import vllm_manager
from config import QUEUE_SCHEDULER_AUTO_START, QUEUE_SCHEDULER_POLL_INTERVAL, JOB_MAX_FAILURES, JOB_FAILURE_RETRY_DELAY, JOB_TIMEOUT, VLLM_MAX_FAILURES, VLLM_FAILURE_RETRY_DELAY, VLLM_TIMEOUT, DEPLOYER_SERVICE_URL

logger = logging.getLogger(__name__)

class QueueManager:
    def __init__(self, poll_interval: int = 30, auto_start: bool = True):
        self.queue_requests: Dict[str, Dict[str, Any]] = {}
        self.scheduler_running = False
        self.scheduler_task = None
        self.poll_interval = poll_interval  # seconds
        self.auto_start = auto_start
        self._background_task = None

    async def initialize(self):
        """Initialize the queue manager and optionally start the scheduler"""
        if self.auto_start:
            await self.start_scheduler()
            logger.info(f"Queue scheduler auto-started with {self.poll_interval}s interval")

    async def shutdown(self):
        """Shutdown the queue manager and stop the scheduler"""
        await self.stop_scheduler()

    def set_poll_interval(self, interval: int):
        """Set the polling interval for the scheduler"""
        old_interval = self.poll_interval
        self.poll_interval = interval
        logger.info(f"Poll interval changed from {old_interval}s to {interval}s")
        
        # If scheduler is running, restart it with new interval
        if self.scheduler_running:
            asyncio.create_task(self._restart_scheduler())

    async def _restart_scheduler(self):
        """Restart the scheduler with new settings"""
        logger.info("Restarting scheduler with new poll interval...")
        await self.stop_scheduler()
        await asyncio.sleep(1)  # Brief pause
        await self.start_scheduler()

    async def add_to_queue(self, queue_request: QueueRequest) -> QueueResponse:
        """Add a deployment request to the queue"""
        try:
            queue_request_id = str(uuid.uuid4())
            
            # Create queue request document
            queue_doc = {
                "queue_request_id": queue_request_id,
                "priority": queue_request.priority,
                "status": "pending",
                "vllm_config": queue_request.vllm_config.dict() if queue_request.vllm_config else {},
                "benchmark_configs": [config.dict() for config in queue_request.benchmark_configs],
                "scheduling_config": queue_request.scheduling_config.dict() if queue_request.scheduling_config else {},
                "created_at": datetime.utcnow(),
                "started_at": None,
                "completed_at": None,
                "deployment_id": None,
                "error_message": None,
                # Add Helm deployment fields
                "helm_deployment": getattr(queue_request, 'helm_deployment', False),
                "helm_config": getattr(queue_request, 'helm_config', None),
                # Add skip_vllm_creation field
                "skip_vllm_creation": getattr(queue_request, 'skip_vllm_creation', False),
                # Add GitHub token for private repository access
                "github_token": getattr(queue_request, 'github_token', None),
                # Add repository URL for charts cloning
                "repository_url": getattr(queue_request, 'repository_url', None)
            }
            
            # Store in memory
            self.queue_requests[queue_request_id] = queue_doc
            
            # Store in database
            await self._save_queue_request_to_db(queue_doc)
            
            logger.info(f"Added request {queue_request_id} to queue with priority {queue_request.priority}")
            
            return QueueResponse(
                queue_request_id=queue_request_id,
                priority=queue_request.priority,
                status="pending",
                vllm_config=queue_request.vllm_config,
                benchmark_configs=queue_request.benchmark_configs,
                scheduling_config=queue_request.scheduling_config or SchedulingConfig(),
                created_at=queue_doc["created_at"]
            )
            
        except Exception as e:
            logger.error(f"Failed to add request to queue: {e}")
            raise

    async def get_queue_list(self) -> List[QueueResponse]:
        """Get list of all queue requests"""
        try:
            # Load from database if not in memory
            await self._load_queue_requests_from_db()
            
            result = []
            for queue_doc in self.queue_requests.values():
                # Handle scheduling_config properly
                scheduling_config_data = queue_doc.get("scheduling_config", {})
                if scheduling_config_data:
                    scheduling_config = SchedulingConfig(**scheduling_config_data)
                else:
                    scheduling_config = SchedulingConfig()
                
                result.append(QueueResponse(
                    queue_request_id=queue_doc["queue_request_id"],
                    priority=queue_doc["priority"],
                    status=queue_doc["status"],
                    vllm_config=VLLMConfig(**queue_doc["vllm_config"]) if queue_doc["vllm_config"] else None,
                    benchmark_configs=[BenchmarkJobConfig(**config) for config in queue_doc["benchmark_configs"]],
                    scheduling_config=scheduling_config,
                    created_at=queue_doc["created_at"],
                    started_at=queue_doc.get("started_at"),
                    completed_at=queue_doc.get("completed_at"),
                    deployment_id=queue_doc.get("deployment_id"),
                    error_message=queue_doc.get("error_message"),
                    # Add Helm deployment fields
                    helm_deployment=queue_doc.get("helm_deployment", False),
                    helm_config=queue_doc.get("helm_config", None)
                ))
            
            # Sort by created_at (newest first), then by priority
            priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
            result.sort(key=lambda x: (x.created_at, priority_order.get(x.priority, 4)), reverse=True)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get queue list: {e}")
            raise

    async def get_queue_status(self) -> QueueStatusResponse:
        """Get queue status overview"""
        try:
            await self._load_queue_requests_from_db()
            
            status_counts = {
                "pending": 0,
                "processing": 0, 
                "completed": 0,
                "failed": 0,
                "cancelled": 0
            }
            
            for queue_doc in self.queue_requests.values():
                status = queue_doc["status"]
                if status in status_counts:
                    status_counts[status] += 1
            
            return QueueStatusResponse(
                total_requests=len(self.queue_requests),
                pending_requests=status_counts["pending"],
                processing_requests=status_counts["processing"],
                completed_requests=status_counts["completed"],
                failed_requests=status_counts["failed"],
                cancelled_requests=status_counts["cancelled"]
            )
            
        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")
            raise

    async def cancel_queue_request(self, queue_request_id: str) -> bool:
        """Cancel a queue request and terminate any running jobs/deployments"""
        try:
            logger.info(f"=== Starting cancellation of queue request {queue_request_id} ===")
            
            if queue_request_id not in self.queue_requests:
                await self._load_queue_requests_from_db()
                
            if queue_request_id not in self.queue_requests:
                logger.warning(f"Queue request {queue_request_id} not found")
                return False
            
            queue_doc = self.queue_requests[queue_request_id]
            current_status = queue_doc["status"]
            
            # Only allow cancellation of pending or processing requests
            if current_status not in ["pending", "processing"]:
                logger.warning(f"Cannot cancel queue request {queue_request_id} with status {current_status}")
                return False
            
            logger.info(f"Cancelling queue request {queue_request_id} with status {current_status}")
            logger.info(f"Request has {len(queue_doc.get('benchmark_configs', []))} benchmark configs")
            logger.info(f"Request has {len(queue_doc.get('created_job_names', []))} tracked job names")
            
            # If request is currently processing, we need to clean up resources
            if current_status == "processing":
                logger.info(f"Request {queue_request_id} is processing - performing resource cleanup")
                await self._cleanup_processing_request(queue_request_id, queue_doc)
            else:
                logger.info(f"Request {queue_request_id} is pending - no active resources to clean up")
            
            # Update status
            queue_doc["status"] = "cancelled"
            queue_doc["completed_at"] = datetime.utcnow()
            queue_doc["error_message"] = "Cancelled by user"
            
            # Update in database
            await self._update_queue_request_in_db(queue_request_id, queue_doc)
            
            logger.info(f"=== Successfully cancelled queue request {queue_request_id} ===")
            return True
            
        except Exception as e:
            logger.error(f"=== Failed to cancel queue request {queue_request_id}: {e} ===")
            return False

    async def _cleanup_processing_request(self, queue_request_id: str, queue_doc: Dict[str, Any]):
        """Clean up resources for a processing request being cancelled"""
        try:
            logger.info(f"Cleaning up processing request {queue_request_id}")
            
            # 1. Stop any running benchmark jobs
            await self._cleanup_benchmark_jobs(queue_request_id, queue_doc)
            
            # 2. Stop VLLM deployment if it was created by this request
            await self._cleanup_vllm_deployment(queue_request_id, queue_doc)
            
            logger.info(f"Completed cleanup for processing request {queue_request_id}")
            
        except Exception as e:
            logger.error(f"Error during cleanup of processing request {queue_request_id}: {e}")
            # Don't re-raise - cancellation should still proceed

    async def _cleanup_benchmark_jobs(self, queue_request_id: str, queue_doc: Dict[str, Any]):
        """Clean up any running benchmark jobs"""
        try:
            benchmark_configs = queue_doc.get("benchmark_configs", [])
            if not benchmark_configs:
                logger.info(f"No benchmark jobs to clean up for request {queue_request_id}")
                return
            
            logger.info(f"Cleaning up benchmark jobs for request {queue_request_id}")
            
            # Try to delete jobs via deployer API
            deployer_base_url = DEPLOYER_SERVICE_URL  # Use the configured deployer service URL
            
            # Method 1: Try to delete jobs based on stored job names in queue_doc
            stored_job_names = queue_doc.get("created_job_names", [])
            if stored_job_names:
                logger.info(f"Found {len(stored_job_names)} stored job names to delete")
                for job_info in stored_job_names:
                    if isinstance(job_info, dict):
                        job_name = job_info.get('name')
                        namespace = job_info.get('namespace', 'default')
                    else:
                        # Backward compatibility - job_info might be just a string
                        job_name = job_info
                        namespace = 'default'
                    
                    if job_name:
                        await self._delete_single_job(job_name, namespace, deployer_base_url)
            else:
                # Method 2: Fallback to using benchmark_configs (original method)
                logger.info(f"No stored job names found, using benchmark configs as fallback")
                for i, config in enumerate(benchmark_configs):
                    job_name = config.get('name', f'benchmark-job-{i+1}')
                    namespace = config.get('namespace', 'default')
                    await self._delete_single_job(job_name, namespace, deployer_base_url)
            
            # Method 3: Additional cleanup - search for jobs by queue_request_id label (if supported)
            await self._cleanup_jobs_by_queue_id(queue_request_id, deployer_base_url)
            
        except Exception as e:
            logger.error(f"Error cleaning up benchmark jobs: {e}")

    async def _delete_single_job(self, job_name: str, namespace: str, deployer_base_url: str):
        """Delete a single job by name"""
        try:
            logger.info(f"Attempting to delete job {job_name} in namespace {namespace}")
            
            async with aiohttp.ClientSession() as session:
                delete_url = f"{deployer_base_url}/jobs/{job_name}/delete"
                params = {"namespace": namespace}
                
                async with session.delete(delete_url, params=params) as response:
                    if response.status in [200, 204, 404]:  # 404 means already deleted
                        logger.info(f"Successfully deleted job {job_name}")
                    else:
                        error_text = await response.text()
                        logger.warning(f"Failed to delete job {job_name}: HTTP {response.status} - {error_text}")
                        
        except Exception as e:
            logger.warning(f"Error deleting job {job_name}: {e}")

    async def _cleanup_jobs_by_queue_id(self, queue_request_id: str, deployer_base_url: str):
        """Additional cleanup method - search for jobs by queue_request_id label"""
        try:
            # This is an additional safety net to find and delete any jobs that might have been missed
            # We'll try to get a list of all deployments and find ones related to this queue request
            logger.info(f"Performing additional cleanup search for queue request {queue_request_id}")
            
            async with aiohttp.ClientSession() as session:
                list_url = f"{deployer_base_url}/deployments"
                
                async with session.get(list_url) as response:
                    if response.status == 200:
                        deployments = await response.json()
                        
                        # Look for jobs that might be related to this queue request
                        # This could be based on naming patterns or metadata
                        for deployment in deployments:
                            if (deployment.get('resource_type', '').lower() == 'job' and 
                                deployment.get('status') not in ['deleted', 'completed']):
                                
                                # Check if job name contains queue_request_id or similar pattern
                                job_name = deployment.get('resource_name', '')
                                namespace = deployment.get('namespace', 'default')
                                
                                # This is a heuristic - you might want to adjust based on your naming patterns
                                if (queue_request_id in job_name or 
                                    job_name.startswith('benchmark-job-') or
                                    'benchmark' in job_name.lower()):
                                    
                                    logger.info(f"Found potential related job {job_name} for cleanup")
                                    await self._delete_single_job(job_name, namespace, deployer_base_url)
                    else:
                        logger.warning(f"Could not list deployments for additional cleanup: HTTP {response.status}")
                        
        except Exception as e:
            logger.warning(f"Error during additional cleanup by queue ID: {e}")

    async def _cleanup_vllm_deployment(self, queue_request_id: str, queue_doc: Dict[str, Any]):
        """Clean up VLLM deployment if it was created by this request"""
        try:
            deployment_id = queue_doc.get("deployment_id")
            if not deployment_id or deployment_id == "existing-vllm":
                logger.info(f"No VLLM deployment to clean up for request {queue_request_id}")
                return
            
            logger.info(f"Cleaning up VLLM deployment {deployment_id} for request {queue_request_id}")
            
            # Check if this deployment is used by other requests
            other_requests_using_deployment = []
            for other_request_id, other_queue_doc in self.queue_requests.items():
                if (other_request_id != queue_request_id and 
                    other_queue_doc.get("deployment_id") == deployment_id and
                    other_queue_doc.get("status") in ["pending", "processing"]):
                    other_requests_using_deployment.append(other_request_id)
            
            if other_requests_using_deployment:
                logger.info(f"VLLM deployment {deployment_id} is used by other requests {other_requests_using_deployment}, not deleting")
                return
            
            # Stop the VLLM deployment
            success = await vllm_manager.stop_deployment(deployment_id)
            if success:
                logger.info(f"Successfully stopped VLLM deployment {deployment_id}")
            else:
                logger.warning(f"Failed to stop VLLM deployment {deployment_id}")
                
        except Exception as e:
            logger.error(f"Error cleaning up VLLM deployment: {e}")

    async def change_queue_priority(self, queue_request_id: str, new_priority: str) -> bool:
        """Change priority of a queue request"""
        try:
            if queue_request_id not in self.queue_requests:
                await self._load_queue_requests_from_db()
                
            if queue_request_id not in self.queue_requests:
                return False
            
            queue_doc = self.queue_requests[queue_request_id]
            
            # Only allow priority change for pending requests
            if queue_doc["status"] != "pending":
                return False
            
            # Update priority
            queue_doc["priority"] = new_priority
            
            # Update in database
            await self._update_queue_request_in_db(queue_request_id, queue_doc)
            
            logger.info(f"Changed priority of queue request {queue_request_id} to {new_priority}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to change priority for queue request {queue_request_id}: {e}")
            return False

    async def update_queue_request_status(self, queue_request_id: str, update_data: Dict[str, Any]) -> bool:
        """Update queue request status (used by benchmark-deployer for Helm deployments)"""
        try:
            if queue_request_id not in self.queue_requests:
                await self._load_queue_requests_from_db()
                
            if queue_request_id not in self.queue_requests:
                return False

            queue_doc = self.queue_requests[queue_request_id]
            
            # Update fields
            for key, value in update_data.items():
                if key == "completed_at" and isinstance(value, str):
                    # Parse ISO format datetime string
                    from datetime import datetime
                    queue_doc[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                else:
                    queue_doc[key] = value
            
            # Update in database
            await self._update_queue_request_in_db(queue_request_id, queue_doc)
            
            logger.info(f"Updated queue request {queue_request_id} status to {update_data.get('status', 'unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update queue request status {queue_request_id}: {e}")
            return False

    async def delete_queue_request(self, queue_request_id: str, force: bool = False) -> bool:
        """Delete a queue request (only pending or completed/failed requests, unless force=True)"""
        try:
            logger.info(f"Attempting to delete queue request {queue_request_id} (force={force})")
            logger.info(f"Current queue_requests keys: {list(self.queue_requests.keys())}")
            
            if queue_request_id not in self.queue_requests:
                logger.info(f"Queue request {queue_request_id} not in memory, loading from DB")
                await self._load_queue_requests_from_db()
                logger.info(f"After DB load, queue_requests keys: {list(self.queue_requests.keys())}")
                
            if queue_request_id not in self.queue_requests:
                logger.warning(f"Queue request {queue_request_id} not found in database")
                return False

            queue_doc = self.queue_requests[queue_request_id]
            logger.info(f"Found queue request {queue_request_id} with status: {queue_doc['status']}")
            
            # If force=True, allow deletion of any status including processing
            # If force=False, only allow deletion of non-processing requests
            if not force and queue_doc["status"] == "processing":
                logger.warning(f"Cannot delete queue request {queue_request_id} - currently processing. Use force=True to override.")
                return False
            
            # If processing and force=True, perform cleanup first
            if force and queue_doc["status"] == "processing":
                logger.info(f"Force deleting processing request {queue_request_id} - performing cleanup first")
                try:
                    await self._cleanup_processing_request(queue_request_id, queue_doc)
                    logger.info(f"Cleanup completed for force-deleted request {queue_request_id}")
                except Exception as e:
                    logger.error(f"Error during cleanup of force-deleted request {queue_request_id}: {e}")
                    # Continue with deletion even if cleanup fails
            
            # Remove from memory
            del self.queue_requests[queue_request_id]
            
            # Remove from database
            await self._delete_queue_request_from_db(queue_request_id)
            
            logger.info(f"Successfully deleted queue request {queue_request_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete queue request {queue_request_id}: {e}")
            return False

    async def force_delete_queue_request(self, queue_request_id: str) -> bool:
        """Force delete a queue request regardless of status"""
        return await self.delete_queue_request(queue_request_id, force=True)

    async def start_scheduler(self):
        """Start the queue scheduler"""
        if self.scheduler_running:
            logger.warning("Queue scheduler is already running")
            return
            
        try:
            self.scheduler_running = True
            self.scheduler_task = asyncio.create_task(self._scheduler_loop())
            logger.info(f"Queue scheduler started with {self.poll_interval}s polling interval")
        except Exception as e:
            self.scheduler_running = False
            logger.error(f"Failed to start queue scheduler: {e}")
            raise

    async def stop_scheduler(self):
        """Stop the queue scheduler"""
        if not self.scheduler_running:
            logger.info("Queue scheduler is already stopped")
            return
            
        try:
            self.scheduler_running = False
            if self.scheduler_task:
                self.scheduler_task.cancel()
                try:
                    await self.scheduler_task
                except asyncio.CancelledError:
                    logger.debug("Scheduler task cancelled successfully")
                self.scheduler_task = None
            logger.info("Queue scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping queue scheduler: {e}")

    async def get_scheduler_status(self):
        """Get detailed scheduler status"""
        return {
            "running": self.scheduler_running,
            "poll_interval": self.poll_interval,
            "auto_start": self.auto_start,
            "task_running": self.scheduler_task is not None and not self.scheduler_task.done() if self.scheduler_task else False,
            "active_requests": len([r for r in self.queue_requests.values() if r.get("status") == "processing"]),
            "pending_requests": len([r for r in self.queue_requests.values() if r.get("status") == "pending"])
        }

    async def _scheduler_loop(self):
        """Main scheduler loop with improved error handling"""
        logger.info("Scheduler loop started")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.scheduler_running:
            try:
                await self._process_next_request()
                consecutive_errors = 0  # Reset error counter on success
                
            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Error in scheduler loop (attempt {consecutive_errors}/{max_consecutive_errors}): {e}")
                
                # If too many consecutive errors, increase wait time
                if consecutive_errors >= max_consecutive_errors:
                    error_wait_time = min(self.poll_interval * 2, 300)  # Max 5 minutes
                    logger.warning(f"Too many consecutive errors, waiting {error_wait_time}s before retrying")
                    await asyncio.sleep(error_wait_time)
                    consecutive_errors = 0  # Reset after long wait
                    continue
            
            # Normal polling interval
            if self.scheduler_running:  # Check again in case it was stopped during processing
                await asyncio.sleep(self.poll_interval)
        
        logger.info("Scheduler loop ended")

    async def _process_next_request(self):
        """Process the next pending request in the queue"""
        try:
            logger.info(f"🔍 [SCHEDULER] Checking for pending requests...")
            await self._load_queue_requests_from_db()
            
            logger.info(f"🔍 [SCHEDULER] Total queue requests in memory: {len(self.queue_requests)}")
            for req_id, req_doc in self.queue_requests.items():
                logger.info(f"🔍 [SCHEDULER] Request {req_id}: status={req_doc.get('status', 'unknown')}")
            
            # Find the next pending request with highest priority
            pending_requests = [
                (request_id, queue_doc) for request_id, queue_doc in self.queue_requests.items()
                if queue_doc["status"] == "pending"
            ]
            
            logger.info(f"🔍 [SCHEDULER] Found {len(pending_requests)} pending requests")
            
            if not pending_requests:
                logger.info(f"🔍 [SCHEDULER] No pending requests found - sleeping...")
                return
            
            # Sort by priority and created_at
            priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
            pending_requests.sort(key=lambda x: (priority_order.get(x[1]["priority"], 4), x[1]["created_at"]))
            
            request_id, queue_doc = pending_requests[0]
            
            logger.info(f"🔍 [SCHEDULER] Processing next request: {request_id}")
            
            # Update status to processing immediately when starting
            queue_doc["status"] = "processing"
            queue_doc["started_at"] = datetime.utcnow()
            queue_doc["current_step"] = "vllm_deployment"
            await self._update_queue_request_in_db(request_id, queue_doc)
            
            try:
                # Process both regular and Helm deployment requests
                # (deployer now only registers requests in queue, benchmark-vllm handles all deployments)
                
                # Check if this is a Helm deployment (now processed by benchmark-vllm)
                is_helm_deployment = queue_doc.get("helm_deployment", False)
                if is_helm_deployment:
                    logger.info(f"Processing Helm deployment queue request {request_id} (registered by deployer)")
                else:
                    logger.info(f"Processing regular queue request {request_id}")
                
                # Unified processing logic for both regular and Helm deployments:
                # Check if VLLM creation should be skipped
                skip_vllm_creation = queue_doc.get("skip_vllm_creation", False)
                
                # Debug logging to troubleshoot skip_vllm_creation flag
                logger.info(f"🚨 [BENCHMARK-VLLM] =================================================")
                logger.info(f"🚨 [BENCHMARK-VLLM] Processing queue request: {request_id}")
                logger.info(f"🚨 [BENCHMARK-VLLM] skip_vllm_creation flag = {skip_vllm_creation}")
                logger.info(f"🚨 [BENCHMARK-VLLM] queue_doc keys = {list(queue_doc.keys())}")
                logger.info(f"🚨 [BENCHMARK-VLLM] queue_doc type = {type(queue_doc)}")
                if "skip_vllm_creation" in queue_doc:
                    logger.info(f"🚨 [BENCHMARK-VLLM] ✅ queue_doc['skip_vllm_creation'] = {queue_doc['skip_vllm_creation']} (type: {type(queue_doc['skip_vllm_creation'])})")
                else:
                    logger.info(f"🚨 [BENCHMARK-VLLM] ❌ 'skip_vllm_creation' key NOT FOUND in queue_doc")
                logger.info(f"🚨 [BENCHMARK-VLLM] =================================================")
                
                if skip_vllm_creation:
                    logger.info(f"🚨 [BENCHMARK-VLLM] ✅ SKIPPING VLLM creation for request {request_id} - using existing VLLM")
                    
                    # Get current running VLLM model name
                    current_vllm_model = await self._get_current_vllm_model()
                    if current_vllm_model:
                        queue_doc["deployment_id"] = f"existing-{current_vllm_model}"
                        logger.info(f"🚨 [BENCHMARK-VLLM] ✅ Using existing VLLM model: {current_vllm_model}")
                    else:
                        queue_doc["deployment_id"] = "existing-vllm"
                        logger.info(f"🚨 [BENCHMARK-VLLM] ⚠️ Could not detect current VLLM model, using generic name")
                    
                    queue_doc["current_step"] = "benchmark_jobs"
                    logger.info(f"🚨 [BENCHMARK-VLLM] ✅ Set deployment_id='{queue_doc['deployment_id']}', current_step='benchmark_jobs'")
                else:
                    logger.info(f"🚨 [BENCHMARK-VLLM] ❌ NOT SKIPPING VLLM creation - proceeding with deployment for request {request_id}")
                    # Regular VLLM deployment
                    logger.info(f"Processing VLLM deployment queue request {request_id}")
                    
                    # Check if vllm_config is valid before deploying
                    if not queue_doc["vllm_config"] or not queue_doc["vllm_config"].get("model_name"):
                        raise Exception("Invalid or empty VLLM configuration")
                    
                    deployment_response = None
                    try:
                        # Deploy VLLM using Helm chart
                        logger.info(f"Creating VLLMConfig from queue data for request {request_id}")
                        
                        # Log custom values information
                        vllm_config_data = queue_doc["vllm_config"]
                        custom_values_content = vllm_config_data.get("custom_values_content")
                        custom_values_path = vllm_config_data.get("custom_values_path")
                        
                        if custom_values_content:
                            logger.info(f"✅ Found custom_values_content in queue (size: {len(custom_values_content)} chars)")
                            logger.info(f"Custom values preview: {custom_values_content[:200]}..." if len(custom_values_content) > 200 else f"Custom values content: {custom_values_content}")
                        elif custom_values_path:
                            logger.info(f"✅ Found custom_values_path in queue: {custom_values_path}")
                        else:
                            logger.info(f"❌ No custom values found in queue - will use generated values from config")
                        
                        vllm_config = VLLMConfig(**queue_doc["vllm_config"])
                        github_token = queue_doc.get("github_token")  # Get GitHub token from queue
                        repository_url = queue_doc.get("repository_url")  # Get repository URL from queue
                        deployment_response = await vllm_manager.deploy_vllm_with_helm(vllm_config, request_id, github_token, repository_url)
                        
                        queue_doc["deployment_id"] = deployment_response.deployment_id
                        queue_doc["helm_release_name"] = getattr(deployment_response, 'helm_release_name', None)
                        
                        # Wait for VLLM to be ready (this can now fail after 3 attempts)
                        logger.info(f"Waiting for VLLM Helm deployment {deployment_response.deployment_id} to be ready...")
                        await vllm_manager.wait_for_helm_deployment_ready(
                            deployment_response.deployment_id,
                            timeout=VLLM_TIMEOUT,
                            max_failures=VLLM_MAX_FAILURES,
                            failure_retry_delay=VLLM_FAILURE_RETRY_DELAY
                        )
                        logger.info(f"VLLM deployment {deployment_response.deployment_id} is ready, proceeding with benchmark jobs")
                        
                    except Exception as vllm_error:
                        # VLLM deployment failed - do NOT proceed with benchmark jobs
                        logger.error(f"=== VLLM DEPLOYMENT FAILED for request {request_id} ===")
                        logger.error(f"VLLM Error: {vllm_error}")
                        
                        # Always try to clean up if we have deployment info
                        cleanup_attempted = False
                        cleanup_successful = False
                        
                        # Clean up failed deployment if Helm install was attempted
                        if deployment_response is not None:
                            logger.info(f"🧹 Attempting cleanup of failed VLLM deployment {deployment_response.deployment_id}")
                            cleanup_attempted = True
                            
                            try:
                                cleanup_successful = await vllm_manager.cleanup_failed_helm_deployment(deployment_response.deployment_id)
                                if cleanup_successful:
                                    logger.info(f"✅ Successfully cleaned up failed deployment {deployment_response.deployment_id}")
                                else:
                                    logger.error(f"❌ Failed to clean up deployment {deployment_response.deployment_id}")
                                    
                                    # Force cleanup using release name if available
                                    if hasattr(deployment_response, 'deployment_name') and deployment_response.deployment_name:
                                        logger.info(f"🔄 Attempting force cleanup using release name: {deployment_response.deployment_name}")
                                        await self._force_helm_cleanup(deployment_response.deployment_name, 'vllm')
                                        logger.info(f"🧹 Force cleanup completed for {deployment_response.deployment_name}")
                                        
                            except Exception as cleanup_error:
                                logger.error(f"💥 Exception during cleanup: {cleanup_error}")
                                
                                # Last resort: try force cleanup with release name
                                if hasattr(deployment_response, 'deployment_name') and deployment_response.deployment_name:
                                    try:
                                        logger.info(f"🚨 Last resort: force cleaning release {deployment_response.deployment_name}")
                                        await self._force_helm_cleanup(deployment_response.deployment_name, 'vllm')
                                        logger.info(f"🧹 Last resort cleanup completed")
                                    except Exception as force_cleanup_error:
                                        logger.error(f"💥 Force cleanup also failed: {force_cleanup_error}")
                        else:
                            logger.info(f"🚫 No cleanup needed - VLLM deployment was not attempted or failed before Helm install")
                        
                        # Update queue status to failed
                        queue_doc["status"] = "failed"
                        queue_doc["error"] = str(vllm_error)
                        queue_doc["cleanup_attempted"] = cleanup_attempted
                        queue_doc["cleanup_successful"] = cleanup_successful
                        queue_doc["current_step"] = "failed"
                        
                        logger.error(f"🚫 Skipping ALL benchmark jobs due to VLLM deployment failure")
                        logger.error(f"📋 Cleanup summary - Attempted: {cleanup_attempted}, Successful: {cleanup_successful}")
                        logger.info(f"This request will be marked as failed and no further processing will occur")
                        
                        # Save failed state and exit processing for this request
                        await self._save_queue_request_to_db(queue_doc)
                        raise Exception(f"VLLM deployment failed after {VLLM_MAX_FAILURES} attempts: {vllm_error}")
                    
                # Execute benchmark jobs if any (both for skip_vllm_creation=True and normal VLLM deployment)
                if queue_doc["benchmark_configs"]:
                    if skip_vllm_creation:
                        logger.info(f"🚨 [BENCHMARK-VLLM] ✅ VLLM creation was skipped, starting benchmark jobs for request {request_id}")
                    else:
                        logger.info(f"VLLM is ready, starting benchmark jobs for request {request_id}")
                    
                    queue_doc["current_step"] = "benchmark_jobs"
                    await self._update_queue_request_in_db(request_id, queue_doc)
                    
                    try:
                        created_jobs = await self._execute_benchmark_jobs(
                            queue_doc["benchmark_configs"],
                            queue_doc["deployment_id"],  # Use deployment_id from queue_doc instead
                            request_id  # Pass queue_request_id for job tracking
                        )
                        
                        # Check if any jobs failed
                        failed_jobs = [job for job in created_jobs if job.get('failed', False)]
                        if failed_jobs:
                            failed_job_names = [job['name'] for job in failed_jobs]
                            raise Exception(f"Benchmark jobs failed: {', '.join(failed_job_names)}")
                        
                        logger.info(f"✅ All {len(created_jobs)} benchmark jobs completed successfully for request {request_id}")
                        
                    except Exception as benchmark_error:
                        logger.error(f"❌ Benchmark jobs failed for request {request_id}: {benchmark_error}")
                        raise Exception(f"Benchmark execution failed: {benchmark_error}")
                else:
                    logger.info(f"No benchmark jobs configured for request {request_id}")
                
                # Update status to completed ONLY if we reach here (no exceptions)
                queue_doc["status"] = "completed"
                queue_doc["completed_at"] = datetime.utcnow()
                queue_doc["current_step"] = "completed"
                
                if skip_vllm_creation:
                    logger.info(f"🚨 [BENCHMARK-VLLM] ✅ Successfully processed queue request {request_id} (VLLM creation skipped)")
                else:
                    logger.info(f"✅ Successfully processed regular queue request {request_id}")
                
                logger.info(f"🎉 Queue request {request_id} marked as COMPLETED")
                
            except Exception as e:
                # Update status to failed
                queue_doc["status"] = "failed"
                queue_doc["error_message"] = str(e)
                queue_doc["completed_at"] = datetime.utcnow()
                queue_doc["current_step"] = "failed"
                
                logger.error(f"Failed to process queue request {request_id}: {e}")
            
            # Update final status in database
            await self._update_queue_request_in_db(request_id, queue_doc)
            
        except Exception as e:
            logger.error(f"Error processing next request: {e}")

    async def _wait_for_vllm_ready(self, deployment_id: str, timeout: int = 600, max_failures: int = 3, failure_retry_delay: int = 30):
        """Wait for VLLM deployment to be ready with failure tracking and retry logic"""
        start_time = datetime.utcnow()
        failure_count = 0
        consecutive_failures = 0
        last_status = None
        
        logger.info(f"Waiting for VLLM deployment {deployment_id} to be ready (timeout: {timeout}s, max_failures: {max_failures})")
        
        while True:
            try:
                deployment_info = await vllm_manager.get_deployment_status(deployment_id)
                if not deployment_info:
                    raise Exception(f"Deployment {deployment_id} not found")
                
                current_status = deployment_info["status"]
                logger.debug(f"VLLM deployment {deployment_id} status: {current_status}")
                
                if current_status == "running":
                    logger.info(f"VLLM deployment {deployment_id} is ready")
                    return
                
                if current_status in ["failed", "error"]:
                    failure_count += 1
                    consecutive_failures += 1
                    
                    logger.warning(f"VLLM deployment {deployment_id} failed with status: {current_status} (failure #{failure_count})")
                    
                    # Check if we've exceeded maximum failures
                    if failure_count >= max_failures:
                        logger.error(f"VLLM deployment {deployment_id} has failed {failure_count} times, exceeding maximum of {max_failures}")
                        
                        # Attempt to clean up the failed deployment
                        try:
                            await self._cleanup_failed_vllm_deployment(deployment_id)
                            logger.info(f"Successfully cleaned up failed VLLM deployment {deployment_id}")
                        except Exception as cleanup_error:
                            logger.error(f"Failed to clean up VLLM deployment {deployment_id}: {cleanup_error}")
                        
                        raise Exception(f"VLLM deployment {deployment_id} failed {failure_count} times, exceeding maximum failures ({max_failures}). Deployment has been terminated.")
                    
                    # Wait longer before retrying after failure
                    logger.info(f"VLLM deployment {deployment_id} failed, waiting {failure_retry_delay} seconds before next check...")
                    await asyncio.sleep(failure_retry_delay)
                    continue
                
                # Reset consecutive failures if deployment is recovering
                if current_status in ["starting", "pending"] and last_status in ["failed", "error"]:
                    consecutive_failures = 0
                    logger.info(f"VLLM deployment {deployment_id} is recovering from failure")
                
                last_status = current_status
                
                # Check timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    logger.error(f"Timeout waiting for VLLM deployment {deployment_id} to be ready after {elapsed}s (timeout: {timeout}s)")
                    
                    # Attempt to clean up the timed-out deployment
                    try:
                        await self._cleanup_failed_vllm_deployment(deployment_id)
                        logger.info(f"Successfully cleaned up timed-out VLLM deployment {deployment_id}")
                    except Exception as cleanup_error:
                        logger.error(f"Failed to clean up timed-out VLLM deployment {deployment_id}: {cleanup_error}")
                    
                    raise Exception(f"Timeout waiting for VLLM deployment {deployment_id} to be ready (timeout: {timeout}s). Deployment has been terminated.")
                
                # Normal polling interval
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                if "failed" in str(e).lower() or "timeout" in str(e).lower():
                    # These are expected failures, re-raise them
                    raise
                else:
                    # Unexpected error, log and continue
                    logger.warning(f"Unexpected error checking VLLM deployment status: {e}")
                    await asyncio.sleep(10)

    async def _cleanup_failed_vllm_deployment(self, deployment_id: str):
        """Clean up a failed VLLM deployment"""
        try:
            logger.info(f"Cleaning up failed VLLM deployment {deployment_id}")
            
            # Attempt to stop the deployment using vllm_manager
            success = await vllm_manager.stop_deployment(deployment_id)
            
            if success:
                logger.info(f"Successfully stopped failed VLLM deployment {deployment_id}")
            else:
                logger.warning(f"Failed to stop VLLM deployment {deployment_id} - it may not exist or already be stopped")
                
        except Exception as e:
            logger.error(f"Error during cleanup of failed VLLM deployment {deployment_id}: {e}")
            # Don't re-raise - cleanup failure shouldn't prevent error reporting

    async def _execute_benchmark_jobs(self, benchmark_configs: List[Dict[str, Any]], deployment_id: str, queue_request_id: str = None):
        """Execute benchmark jobs sequentially via Benchmark Deployer service and track created jobs"""
        logger.info(f"🚀 Starting execution of {len(benchmark_configs)} benchmark jobs for deployment {deployment_id}")
        
        if not benchmark_configs:
            logger.info("No benchmark jobs to execute")
            return []

        # Benchmark Deployer service URL - environment-aware configuration
        import os
        if os.getenv("KUBERNETES_SERVICE_HOST") or os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
            # Running in Kubernetes - use cluster service names
            deployer_base_url = DEPLOYER_SERVICE_URL
        else:
            # Local development - use localhost
            deployer_base_url = DEPLOYER_SERVICE_URL
            
        logger.info(f"Using Deployer service URL: {deployer_base_url}")
        
        # Track created job names for cleanup purposes
        created_job_names = []
        successful_jobs = 0
        failed_jobs = 0
        
        for i, config in enumerate(benchmark_configs):
            job_name = config.get('name', f'benchmark-job-{i+1}')
            yaml_content = config.get('yaml_content', '')
            namespace = config.get('namespace', 'default')
            
            logger.info(f"🔧 Executing benchmark job {i+1}/{len(benchmark_configs)}: {job_name} in namespace {namespace}")
            logger.debug(f"Job YAML content preview: {yaml_content[:200]}..." if len(yaml_content) > 200 else f"Job YAML content: {yaml_content}")
            
            job_start_time = datetime.utcnow()
            
            try:
                # Call Benchmark Deployer API to deploy the job
                logger.info(f"📤 Deploying job {job_name} to deployer service...")
                deployment_error = None
                actual_job_name = job_name  # Default to job_name
                
                try:
                    deployment_result = await self._deploy_benchmark_job_to_deployer(
                        yaml_content=yaml_content,
                        namespace=namespace,
                        job_name=job_name,
                        deployer_base_url=deployer_base_url
                    )
                    
                    # Get the actual resource name from deployment response
                    actual_job_name = deployment_result.get('actual_resource_name', job_name)
                    logger.info(f"✅ Job {job_name} deployed successfully as {actual_job_name}")
                    
                except Exception as deploy_error:
                    deployment_error = deploy_error
                    logger.error(f"⚠️ Deployer API error for job {job_name}: {deploy_error}")
                    logger.info(f"🔍 Checking if job was actually created despite API error...")
                    
                    # Check if job was actually created despite the API error
                    job_exists, actual_job_name = await self._check_if_job_exists(actual_job_name, namespace, deployer_base_url, yaml_content)
                    if job_exists:
                        logger.info(f"✅ Job {actual_job_name} was created despite API error - continuing with monitoring")
                    else:
                        logger.error(f"❌ Job {actual_job_name} was not created - deployment actually failed")
                        raise deploy_error  # Re-raise the original error
                
                # Store the created job information for later cleanup
                job_info = {
                    'name': actual_job_name,
                    'namespace': namespace,
                    'original_name': job_name,
                    'had_deployment_error': deployment_error is not None
                }
                created_job_names.append(job_info)
                
                # Update queue request with created job names for cleanup purposes
                if queue_request_id:
                    await self._update_queue_request_job_names(queue_request_id, created_job_names)
                
                # Wait for the job to complete before starting the next one
                logger.info(f"⏳ Waiting for job {actual_job_name} to complete...")
                wait_start_time = datetime.utcnow()
                
                await self._wait_for_job_completion(
                    job_name=actual_job_name,
                    namespace=namespace,
                    deployer_base_url=deployer_base_url,
                    timeout=JOB_TIMEOUT,
                    max_failures=JOB_MAX_FAILURES
                )
                
                wait_duration = (datetime.utcnow() - wait_start_time).total_seconds()
                job_total_duration = (datetime.utcnow() - job_start_time).total_seconds()
                
                logger.info(f"✅ Benchmark job {actual_job_name} completed successfully!")
                logger.info(f"📊 Job timing - Wait: {wait_duration:.1f}s, Total: {job_total_duration:.1f}s")
                if deployment_error:
                    logger.info(f"📝 Note: Job completed successfully despite initial deployment API error")
                successful_jobs += 1
                
            except Exception as e:
                failed_jobs += 1
                job_duration = (datetime.utcnow() - job_start_time).total_seconds()
                
                logger.error(f"❌ Failed to execute benchmark job {job_name}: {e}")
                logger.error(f"⏱️ Job failed after {job_duration:.1f}s")
                
                # Even if job failed to complete, if it was created, we should track it for cleanup
                if 'actual_job_name' in locals() and actual_job_name:
                    job_info = {
                        'name': actual_job_name,
                        'namespace': namespace,
                        'original_name': job_name,
                        'failed': True
                    }
                    created_job_names.append(job_info)
                    if queue_request_id:
                        await self._update_queue_request_job_names(queue_request_id, created_job_names)
                
                # Continue with next job even if current one fails
                logger.warning(f"⏭️ Continuing with next job despite failure of {job_name}")
                continue
        
        total_duration = sum((job.get('duration', 0) for job in created_job_names), 0)
        
        logger.info(f"🏁 Completed execution of {len(benchmark_configs)} benchmark jobs")
        logger.info(f"📈 Results: {successful_jobs} successful, {failed_jobs} failed, {len(created_job_names)} total created")
        
        if failed_jobs > 0:
            logger.warning(f"⚠️ {failed_jobs} jobs failed but queue processing will continue")
        
        return created_job_names

    async def _deploy_benchmark_job_to_deployer(self, yaml_content: str, namespace: str, job_name: str, deployer_base_url: str):
        """Deploy a benchmark job via Benchmark Deployer API"""
        deploy_url = f"{deployer_base_url}/deploy"
        
        payload = {
            "yaml_content": yaml_content,
            "namespace": namespace
        }
        
        logger.info(f"Deploying job {job_name} to {deploy_url} in namespace {namespace}")
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            async with session.post(deploy_url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Deployer API error for job {job_name}: HTTP {response.status}")
                    logger.error(f"Error response: {error_text}")
                    raise Exception(f"Failed to deploy job {job_name}: HTTP {response.status} - {error_text}")
                
                result = await response.json()
                logger.info(f"Successfully deployed job {job_name}: {result.get('message', 'No message')}")
                
                # Extract actual resource name from deployment response
                actual_resource_name = result.get('resource_name', job_name)
                result['actual_resource_name'] = actual_resource_name
                
                return result

    async def _check_if_job_exists(self, job_name: str, namespace: str, deployer_base_url: str, yaml_content: str = None) -> tuple[bool, str]:
        """Check if a job exists by trying to get its status. Returns (exists, actual_job_name)"""
        try:
            # Wait a moment for the job to be created
            await asyncio.sleep(2)
            
            # First try with the provided job_name
            actual_job_name = job_name
            job_found = False
            
            async with aiohttp.ClientSession() as session:
                status_url = f"{deployer_base_url}/jobs/{job_name}/status"
                params = {"namespace": namespace}
                
                async with session.get(status_url, params=params) as response:
                    if response.status == 200:
                        # Job exists and we can get its status
                        status_data = await response.json()
                        logger.info(f"🔍 Job {job_name} exists with status: {status_data.get('status', 'unknown')}")
                        return True, job_name
                    elif response.status == 404:
                        logger.info(f"🔍 Job {job_name} not found, checking for actual job name from YAML...")
                        job_found = False
                    else:
                        # Other error - try to extract actual name from YAML
                        logger.warning(f"🔍 Could not check job {job_name} status: HTTP {response.status}")
                        job_found = False
            
            # If job not found with provided name, try to extract actual name from YAML
            if not job_found and yaml_content:
                try:
                    import yaml
                    yaml_docs = list(yaml.safe_load_all(yaml_content))
                    
                    for doc in yaml_docs:
                        if doc and doc.get('kind', '').lower() == 'job':
                            actual_job_name = doc.get('metadata', {}).get('name', job_name)
                            logger.info(f"🔍 Found actual job name in YAML: {actual_job_name}")
                            break
                    
                    # Try with the actual job name from YAML
                    if actual_job_name != job_name:
                        async with aiohttp.ClientSession() as session:
                            status_url = f"{deployer_base_url}/jobs/{actual_job_name}/status"
                            params = {"namespace": namespace}
                            
                            async with session.get(status_url, params=params) as response:
                                if response.status == 200:
                                    status_data = await response.json()
                                    logger.info(f"🔍 Job {actual_job_name} (from YAML) exists with status: {status_data.get('status', 'unknown')}")
                                    return True, actual_job_name
                                else:
                                    logger.info(f"🔍 Job {actual_job_name} (from YAML) not found either")
                
                except Exception as yaml_error:
                    logger.warning(f"🔍 Error parsing YAML to find job name: {yaml_error}")
            
            # Job doesn't exist with either name
            logger.info(f"🔍 Job not found with any name - deployment failed")
            return False, actual_job_name
                        
        except Exception as e:
            logger.warning(f"🔍 Error checking if job {job_name} exists: {e}")
            return False, job_name

    async def _wait_for_job_completion(self, job_name: str, namespace: str, deployer_base_url: str, timeout: int = 3600, max_failures: int = 3):
        """Wait for job completion with failure tracking and retry logic"""
        start_time = datetime.utcnow()
        failure_count = 0
        consecutive_failures = 0
        last_status = None
        check_count = 0  # 총 체크 횟수 추적
        max_checks = timeout // 30 + 10  # 최대 체크 횟수 제한 (안전장치)
        not_found_count = 0  # job이 연속으로 찾을 수 없는 횟수
        
        logger.info(f"Waiting for job {job_name} to complete (timeout: {timeout}s, max_failures: {max_failures})")
        
        while check_count < max_checks:
            check_count += 1
            
            try:
                async with aiohttp.ClientSession() as session:
                    status_url = f"{deployer_base_url}/jobs/{job_name}/status"
                    params = {"namespace": namespace}
                    
                    async with session.get(status_url, params=params) as response:
                        if response.status == 200:
                            not_found_count = 0  # Reset not found counter
                            status_data = await response.json()
                            job_status = status_data.get("status", "unknown").lower()
                            
                            logger.debug(f"Job {job_name} status: {job_status} (check #{check_count})")
                            
                            if job_status in ['succeeded', 'completed']:
                                logger.info(f"✅ Job {job_name} reported as {job_status}")
                                
                                # Double-check by verifying job completion one more time
                                await asyncio.sleep(5)  # Wait a bit to ensure job is truly completed
                                
                                # Final verification
                                async with aiohttp.ClientSession() as verify_session:
                                    async with verify_session.get(status_url, params=params) as verify_response:
                                        if verify_response.status == 200:
                                            verify_data = await verify_response.json()
                                            final_status = verify_data.get("status", "unknown").lower()
                                            if final_status in ['succeeded', 'completed']:
                                                logger.info(f"✅ Job {job_name} completion VERIFIED - final status: {final_status}")
                                                return
                                            else:
                                                logger.warning(f"⚠️ Job {job_name} status changed during verification: {job_status} -> {final_status}")
                                                # Don't return, continue monitoring
                                        elif verify_response.status == 404:
                                            logger.info(f"✅ Job {job_name} completed and was cleaned up during verification")
                                            return
                                        else:
                                            logger.warning(f"⚠️ Could not verify job {job_name} completion: HTTP {verify_response.status}")
                                            # Assume it completed since it was reported as succeeded
                                            return
                            
                            if job_status in ['failed', 'error']:
                                failure_count += 1
                                consecutive_failures += 1
                                
                                logger.warning(f"Job {job_name} failed with status: {job_status} (failure #{failure_count}/{max_failures}, check #{check_count})")
                                
                                # Check if we've exceeded maximum failures
                                if failure_count >= max_failures:
                                    logger.error(f"🚨 Job {job_name} has failed {failure_count} times, exceeding maximum of {max_failures}. Terminating job.")
                                    
                                    # Attempt to delete the failed job
                                    try:
                                        await self._terminate_failed_job(job_name, namespace, deployer_base_url)
                                        logger.info(f"✅ Successfully terminated failed job {job_name}")
                                    except Exception as terminate_error:
                                        logger.error(f"❌ Failed to terminate job {job_name}: {terminate_error}")
                                    
                                    raise Exception(f"Job {job_name} failed {failure_count} times, exceeding maximum failures ({max_failures}). Job has been terminated.")
                                
                                # Wait longer before retrying after failure
                                logger.info(f"⏳ Job {job_name} failed, waiting {JOB_FAILURE_RETRY_DELAY} seconds before next check...")
                                await asyncio.sleep(JOB_FAILURE_RETRY_DELAY)
                                continue
                            
                            # Reset consecutive failures if job is running again
                            if job_status in ['running', 'pending'] and last_status in ['failed', 'error']:
                                consecutive_failures = 0
                                logger.info(f"🔄 Job {job_name} is recovering from failure")
                            
                            last_status = job_status
                        
                        elif response.status == 404:
                            not_found_count += 1
                            logger.warning(f"Job {job_name} not found (attempt {not_found_count}/5), checking if it was deleted or never created")
                            
                            # If job is not found multiple times consecutively, check more carefully
                            if not_found_count >= 5:
                                # Before assuming completion, try to verify if job ever existed or completed
                                logger.warning(f"❌ Job {job_name} not found for {not_found_count} consecutive checks")
                                
                                # Check if there are any pods with this job name that completed
                                try:
                                    pod_status = await self._check_job_pods_status(job_name, namespace)
                                    if pod_status == "completed":
                                        logger.info(f"✅ Job {job_name} pods show completed status - job finished and was cleaned up")
                                        return
                                    elif pod_status == "not_found":
                                        logger.error(f"❌ Job {job_name} and its pods not found - job may have never been created or failed to start")
                                        raise Exception(f"Job {job_name} not found and no evidence of completion")
                                    else:
                                        logger.warning(f"⚠️ Job {job_name} pods status: {pod_status}")
                                except Exception as pod_check_error:
                                    logger.error(f"Failed to check pod status for job {job_name}: {pod_check_error}")
                                
                                # If we can't verify completion, treat as error
                                raise Exception(f"Job {job_name} disappeared without clear completion evidence")
                        
                        else:
                            logger.warning(f"Failed to get status for job {job_name}: HTTP {response.status}")
                            # Don't immediately fail, but log the issue
                            if response.status >= 500:
                                logger.warning(f"Server error ({response.status}) checking job {job_name}, will retry")
                
            except Exception as e:
                # Don't count connection/API errors as job failures
                if "failed with status" in str(e) and "exceeding maximum failures" in str(e):
                    # This is our termination exception, re-raise it
                    raise e
                else:
                    # This is a connection/API error, log but don't count as failure
                    logger.warning(f"Error checking job {job_name} status (check #{check_count}): {e}")
            
            # Check timeout
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed > timeout:
                logger.error(f"🕐 Timeout waiting for job {job_name} to complete after {elapsed}s (timeout: {timeout}s, checks: {check_count})")
                
                # Attempt to terminate the timed-out job
                try:
                    await self._terminate_failed_job(job_name, namespace, deployer_base_url)
                    logger.info(f"✅ Successfully terminated timed-out job {job_name}")
                except Exception as terminate_error:
                    logger.error(f"❌ Failed to terminate timed-out job {job_name}: {terminate_error}")
                
                raise Exception(f"Timeout waiting for job {job_name} to complete (timeout: {timeout}s). Job has been terminated.")
            
            # Wait before next check
            await asyncio.sleep(30)  # Check every 30 seconds
        
        # If we've exceeded max checks, something is wrong
        logger.error(f"🚨 Exceeded maximum checks ({max_checks}) for job {job_name}. Terminating due to safety limit.")
        try:
            await self._terminate_failed_job(job_name, namespace, deployer_base_url)
            logger.info(f"✅ Successfully terminated job {job_name} due to check limit")
        except Exception as terminate_error:
            logger.error(f"❌ Failed to terminate job {job_name}: {terminate_error}")
        
        raise Exception(f"Job {job_name} exceeded maximum check limit ({max_checks}). Job has been terminated for safety.")

    async def _terminate_failed_job(self, job_name: str, namespace: str, deployer_base_url: str):
        """Terminate a failed job by deleting it from Kubernetes"""
        try:
            logger.info(f"Attempting to terminate job {job_name} in namespace {namespace}")
            
            # Call deployer API to delete the job
            delete_url = f"{deployer_base_url}/jobs/{job_name}/delete"
            params = {"namespace": namespace}
            
            async with aiohttp.ClientSession() as session:
                async with session.delete(delete_url, params=params) as response:
                    if response.status in [200, 204, 404]:  # 404 means already deleted
                        logger.info(f"Job {job_name} terminated successfully")
                    else:
                        error_text = await response.text()
                        logger.warning(f"Failed to terminate job {job_name}: HTTP {response.status} - {error_text}")
                        
        except Exception as e:
            logger.error(f"Error terminating job {job_name}: {e}")
            raise e

    async def _save_queue_request_to_db(self, queue_doc: Dict[str, Any]):
        """Save or update queue request to database using upsert"""
        try:
            db = get_database()
            collection = db.vllm_deployment_queue
            
            # Use upsert to avoid duplicate key errors
            queue_request_id = queue_doc.get("queue_request_id")
            if queue_request_id:
                await collection.update_one(
                    {"queue_request_id": queue_request_id},
                    {"$set": queue_doc},
                    upsert=True
                )
                logger.debug(f"Upserted queue request {queue_request_id} to database")
            else:
                # Fallback to insert if no queue_request_id
                await collection.insert_one(queue_doc)
                logger.debug(f"Inserted new queue request to database")
                
        except Exception as e:
            logger.error(f"Failed to save queue request to database: {e}")

    async def _update_queue_request_in_db(self, queue_request_id: str, queue_doc: Dict[str, Any]):
        """Update queue request in database"""
        try:
            db = get_database()
            collection = db.vllm_deployment_queue
            await collection.update_one(
                {"queue_request_id": queue_request_id},
                {"$set": queue_doc}
            )
        except Exception as e:
            logger.error(f"Failed to update queue request in database: {e}")

    async def _load_queue_requests_from_db(self):
        """Load existing queue requests from database"""
        try:
            db = get_database()
            collection = db.vllm_deployment_queue
            
            logger.info(f"🔍 [DB-LOAD] Loading queue requests from collection: vllm_deployment_queue")
            
            # Load ALL requests to maintain history, but prioritize pending and processing for scheduling
            all_requests_count = 0
            pending_and_processing_count = 0
            
            async for queue_doc in collection.find().sort("created_at", -1):  # Load all, newest first
                request_id = queue_doc["queue_request_id"]
                all_requests_count += 1
                
                # Always load into memory for history purposes
                self.queue_requests[request_id] = queue_doc
                
                # Count pending and processing separately
                if queue_doc['status'] in ["pending", "processing"]:
                    pending_and_processing_count += 1
                    logger.info(f"🔍 [DB-LOAD] Loading active request {request_id} with status {queue_doc['status']}")
                
            logger.info(f"🔍 [DB-LOAD] Loaded {all_requests_count} total requests ({pending_and_processing_count} active)")
            
        except Exception as e:
            logger.error(f"Failed to load queue requests from database: {e}")

    async def _delete_queue_request_from_db(self, queue_request_id: str):
        """Delete queue request from database"""
        try:
            db = get_database()
            collection = db.vllm_deployment_queue
            await collection.delete_one({"queue_request_id": queue_request_id})
        except Exception as e:
            logger.error(f"Failed to delete queue request from database: {e}")

    async def _update_queue_request_job_names(self, queue_request_id: str, created_job_names: List[Dict[str, Any]]):
        """Update queue request with created job names for cleanup purposes"""
        try:
            if queue_request_id in self.queue_requests:
                self.queue_requests[queue_request_id]["created_job_names"] = created_job_names
                await self._update_queue_request_in_db(queue_request_id, self.queue_requests[queue_request_id])
                logger.debug(f"Updated queue request {queue_request_id} with {len(created_job_names)} created job names")
        except Exception as e:
            logger.warning(f"Failed to update queue request job names: {e}")

    async def _force_helm_cleanup(self, release_name: str, namespace: str = 'vllm'):
        """Force cleanup of a Helm release by directly executing helm uninstall command"""
        try:
            logger.info(f"🚨 Force cleanup: Executing helm uninstall for release: {release_name} in namespace: {namespace}")
            
            import subprocess
            
            # Execute Helm uninstall command
            helm_cmd = [
                "helm", "uninstall", release_name,
                "--namespace", namespace
            ]
            
            logger.info(f"🔧 Executing force cleanup command: {' '.join(helm_cmd)}")
            
            result = subprocess.run(
                helm_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"✅ Force cleanup successful: {result.stdout}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Force cleanup failed - Helm uninstall error: {e.stderr}")
            # Don't re-raise - this is a last resort cleanup attempt
            return False
        except Exception as e:
            logger.error(f"💥 Force cleanup failed - Unexpected error: {e}")
            return False

    async def _get_current_vllm_model(self) -> Optional[str]:
        """Get the name of the currently running VLLM model from Kubernetes."""
        try:
            from kubernetes import client, config
            
            # Load Kubernetes config
            try:
                config.load_incluster_config()  # For in-cluster
            except:
                try:
                    config.load_kube_config()  # For local development
                except Exception as e:
                    logger.warning(f"Could not load Kubernetes config: {e}")
                    return None
            
            v1 = client.AppsV1Api()
            
            # Look for VLLM deployments in the vllm namespace
            try:
                deployments = v1.list_namespaced_deployment(namespace='vllm')
                
                for deployment in deployments.items:
                    # Check if deployment is ready and running
                    if (deployment.status.ready_replicas and 
                        deployment.status.ready_replicas > 0 and
                        deployment.metadata.name.startswith('vllm-')):
                        
                        model_name = deployment.metadata.name
                        logger.info(f"Found running VLLM model: {model_name}")
                        return model_name
                        
                logger.info("No running VLLM deployments found in vllm namespace")
                return None
                
            except Exception as e:
                logger.warning(f"Error listing deployments in vllm namespace: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting current VLLM model: {e}")
            return None

    async def _check_job_pods_status(self, job_name: str, namespace: str) -> str:
        """Check the status of pods associated with a job."""
        try:
            from kubernetes import client, config
            
            # Load Kubernetes config
            try:
                config.load_incluster_config()  # For in-cluster
            except:
                try:
                    config.load_kube_config()  # For local development
                except Exception as e:
                    logger.warning(f"Could not load Kubernetes config for pod status check: {e}")
                    return "error"
            
            v1 = client.CoreV1Api()
            
            # List pods in the namespace
            pods = v1.list_namespaced_pod(namespace=namespace)
            
            for pod in pods.items:
                # Check if the pod is associated with the job
                if pod.metadata.owner_references and pod.metadata.owner_references[0].name == job_name:
                    # Check the pod's status
                    if pod.status.phase == "Succeeded":
                        return "completed"
                    elif pod.status.phase == "Failed":
                        return "failed"
                    elif pod.status.phase == "Pending":
                        return "pending"
                    elif pod.status.phase == "Running":
                        return "running"
                    else:
                        return pod.status.phase
            return "not_found" # Job not found or no pods found
        except Exception as e:
            logger.error(f"Error checking pod status for job {job_name}: {e}")
            return "error"

# Global queue manager instance
queue_manager = QueueManager(
    poll_interval=QUEUE_SCHEDULER_POLL_INTERVAL,
    auto_start=QUEUE_SCHEDULER_AUTO_START
) 