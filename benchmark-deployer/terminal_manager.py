import asyncio
import logging
import json
import uuid
from typing import Dict, Optional, Set
from datetime import datetime
from starlette.websockets import WebSocketState
from kubernetes import client
from kubernetes.stream import stream
import websockets
from websockets.exceptions import ConnectionClosed

from kubernetes_client import k8s_client
from config import DEFAULT_NAMESPACE

logger = logging.getLogger(__name__)

class TerminalSession:
    def __init__(self, session_id: str, job_name: str, namespace: str, 
                 pod_name: Optional[str] = None, container_name: Optional[str] = None,
                 shell: str = "/bin/bash"):
        self.session_id = session_id
        self.job_name = job_name
        self.namespace = namespace
        self.pod_name = pod_name
        self.container_name = container_name
        self.shell = shell
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.is_active = False
        self.websocket = None
        self.k8s_stream = None
        self.stdin_task = None
        self.stdout_task = None

    async def start(self, websocket):
        """Start terminal session."""
        try:
            self.websocket = websocket
            
            # Get target pod if not specified
            if not self.pod_name:
                pods = await k8s_client.get_job_pods(self.job_name, self.namespace)
                if not pods:
                    raise Exception(f"No pods found for job '{self.job_name}'")
                
                # Find a ready pod
                ready_pods = [pod for pod in pods if pod.ready]
                if ready_pods:
                    self.pod_name = ready_pods[0].pod_name
                else:
                    self.pod_name = pods[0].pod_name

            # Get container name if not specified
            if not self.container_name:
                pods = await k8s_client.get_job_pods(self.job_name, self.namespace)
                target_pod_info = next((pod for pod in pods if pod.pod_name == self.pod_name), None)
                if target_pod_info and target_pod_info.containers:
                    self.container_name = target_pod_info.containers[0]

            logger.info(f"Starting terminal session {self.session_id} for pod {self.pod_name}")

            # Create Kubernetes exec stream
            self.k8s_stream = stream(
                k8s_client.core_v1.connect_get_namespaced_pod_exec,
                name=self.pod_name,
                namespace=self.namespace,
                container=self.container_name,
                command=[self.shell],
                stderr=True,
                stdin=True,
                stdout=True,
                tty=True,
                _preload_content=False
            )

            self.is_active = True
            
            # Send initial connection message
            await self.send_to_client({
                "type": "connected",
                "session_id": self.session_id,
                "pod_name": self.pod_name,
                "container_name": self.container_name,
                "shell": self.shell
            })

            # Start stdin/stdout tasks
            self.stdin_task = asyncio.create_task(self._handle_stdin())
            self.stdout_task = asyncio.create_task(self._handle_stdout())

            # Wait for tasks to complete
            await asyncio.gather(self.stdin_task, self.stdout_task, return_exceptions=True)

        except Exception as e:
            logger.error(f"Error starting terminal session: {e}")
            await self.send_to_client({
                "type": "error",
                "message": f"Failed to start terminal: {str(e)}"
            })
            await self.stop()

    async def _handle_stdin(self):
        """Handle input from WebSocket to Kubernetes."""
        try:
            while self.is_active and self.websocket.client_state == WebSocketState.CONNECTED:
                try:
                    message = await self.websocket.receive_text()
                    
                    try:
                        data = json.loads(message)
                        if data.get("type") == "input":
                            input_data = data.get("data", "")
                            if self.k8s_stream and self.k8s_stream.is_open():
                                self.k8s_stream.write_stdin(input_data)
                                self.last_activity = datetime.now()
                        elif data.get("type") == "resize":
                            # Handle terminal resize (if supported)
                            rows = data.get("rows", 24)
                            cols = data.get("cols", 80)
                            # Note: Kubernetes doesn't support resize in current implementation
                            logger.debug(f"Terminal resize requested: {rows}x{cols}")
                        elif data.get("type") == "ping":
                            await self.send_to_client({"type": "pong"})
                            
                    except json.JSONDecodeError:
                        # Treat as raw input
                        if self.k8s_stream and self.k8s_stream.is_open():
                            self.k8s_stream.write_stdin(message)
                            self.last_activity = datetime.now()
                
                except Exception as receive_error:
                    if "websocket.disconnect" in str(receive_error).lower():
                        logger.info(f"WebSocket disconnected for session {self.session_id}")
                        break
                    else:
                        logger.error(f"Error receiving WebSocket message: {receive_error}")
                        break
                        
        except Exception as e:
            logger.error(f"Error handling stdin: {e}")
        finally:
            await self.stop()

    async def _handle_stdout(self):
        """Handle output from Kubernetes to WebSocket."""
        try:
            while self.is_active and self.k8s_stream and self.k8s_stream.is_open():
                # Check for stdout
                if self.k8s_stream.peek_stdout():
                    stdout_data = self.k8s_stream.read_stdout()
                    if stdout_data:
                        await self.send_to_client({
                            "type": "output",
                            "data": stdout_data
                        })
                        self.last_activity = datetime.now()

                # Check for stderr
                if self.k8s_stream.peek_stderr():
                    stderr_data = self.k8s_stream.read_stderr()
                    if stderr_data:
                        await self.send_to_client({
                            "type": "error_output",
                            "data": stderr_data
                        })
                        self.last_activity = datetime.now()

                # Small delay to prevent busy waiting
                await asyncio.sleep(0.01)

        except Exception as e:
            logger.error(f"Error handling stdout: {e}")
        finally:
            await self.stop()

    async def send_to_client(self, message: dict):
        """Send message to WebSocket client."""
        try:
            if self.websocket and self.websocket.client_state == WebSocketState.CONNECTED:
                await self.websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending to client: {e}")

    async def stop(self):
        """Stop terminal session."""
        if not self.is_active:
            return
            
        self.is_active = False
        logger.info(f"Stopping terminal session {self.session_id}")

        # Cancel tasks
        if self.stdin_task and not self.stdin_task.done():
            self.stdin_task.cancel()
        if self.stdout_task and not self.stdout_task.done():
            self.stdout_task.cancel()

        # Close Kubernetes stream
        if self.k8s_stream:
            try:
                self.k8s_stream.close()
            except Exception as e:
                logger.error(f"Error closing k8s stream: {e}")

        # Close WebSocket
        if self.websocket and self.websocket.client_state == WebSocketState.CONNECTED:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.error(f"Error closing websocket: {e}")

class TerminalManager:
    def __init__(self):
        self.sessions: Dict[str, TerminalSession] = {}
        self.job_sessions: Dict[str, Set[str]] = {}  # job_name -> set of session_ids
        
    async def create_session(self, job_name: str, namespace: str = DEFAULT_NAMESPACE,
                           pod_name: Optional[str] = None, container_name: Optional[str] = None,
                           shell: str = "/bin/bash") -> str:
        """Create a new terminal session."""
        session_id = str(uuid.uuid4())
        
        session = TerminalSession(
            session_id=session_id,
            job_name=job_name,
            namespace=namespace,
            pod_name=pod_name,
            container_name=container_name,
            shell=shell
        )
        
        self.sessions[session_id] = session
        
        # Track sessions by job
        if job_name not in self.job_sessions:
            self.job_sessions[job_name] = set()
        self.job_sessions[job_name].add(session_id)
        
        logger.info(f"Created terminal session {session_id} for job {job_name}")
        return session_id

    async def start_session(self, session_id: str, websocket):
        """Start a terminal session with WebSocket."""
        if session_id not in self.sessions:
            raise Exception(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        await session.start(websocket)

    async def stop_session(self, session_id: str):
        """Stop a terminal session."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            await session.stop()
            
            # Remove from tracking
            job_name = session.job_name
            if job_name in self.job_sessions:
                self.job_sessions[job_name].discard(session_id)
                if not self.job_sessions[job_name]:
                    del self.job_sessions[job_name]
            
            del self.sessions[session_id]
            logger.info(f"Stopped terminal session {session_id}")

    async def stop_job_sessions(self, job_name: str):
        """Stop all terminal sessions for a job."""
        if job_name in self.job_sessions:
            session_ids = list(self.job_sessions[job_name])
            for session_id in session_ids:
                await self.stop_session(session_id)

    def get_session_info(self, session_id: str) -> Optional[dict]:
        """Get session information."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            return {
                "session_id": session.session_id,
                "job_name": session.job_name,
                "namespace": session.namespace,
                "pod_name": session.pod_name,
                "container_name": session.container_name,
                "shell": session.shell,
                "is_active": session.is_active,
                "created_at": session.created_at,
                "last_activity": session.last_activity
            }
        return None

    def list_sessions(self, job_name: Optional[str] = None) -> dict:
        """List terminal sessions."""
        sessions = []
        active_count = 0
        
        for session_id, session in self.sessions.items():
            if job_name is None or session.job_name == job_name:
                session_info = self.get_session_info(session_id)
                if session_info:
                    sessions.append(session_info)
                    if session_info.get("is_active", False):
                        active_count += 1
        
        return {
            "sessions": sessions,
            "total_sessions": len(sessions),
            "active_sessions": active_count
        }

    async def cleanup_inactive_sessions(self, timeout_minutes: int = 30):
        """Clean up inactive sessions."""
        now = datetime.now()
        inactive_sessions = []
        
        for session_id, session in self.sessions.items():
            if not session.is_active:
                continue
            
            inactive_time = (now - session.last_activity).total_seconds() / 60
            if inactive_time > timeout_minutes:
                inactive_sessions.append(session_id)
        
        for session_id in inactive_sessions:
            logger.info(f"Cleaning up inactive session {session_id}")
            await self.stop_session(session_id)

# Global terminal manager instance
terminal_manager = TerminalManager() 