"""
Network utilities for distributed rendering
Handles network communication, port management, and HTTP requests
"""

import socket
import time
import json
import threading
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ..utils.logging_utils import get_logger


class NetworkUtils:
    """
    Network utility functions
    """

    @staticmethod
    def is_port_available(port: int, host: str = 'localhost') -> bool:
        """
        Check if a port is available for binding

        Args:
            port: Port number to check
            host: Host address to check

        Returns:
            True if port is available
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((host, port))
                return result != 0  # Port is available if connection failed
        except Exception:
            return False

    @staticmethod
    def find_available_port(start_port: int = 8080, end_port: int = 8180, host: str = 'localhost') -> Optional[int]:
        """
        Find an available port in range

        Args:
            start_port: Starting port number
            end_port: Ending port number
            host: Host address to check

        Returns:
            Available port number or None if none found
        """
        for port in range(start_port, end_port + 1):
            if NetworkUtils.is_port_available(port, host):
                return port
        return None

    @staticmethod
    def wait_for_port_open(host: str, port: int, timeout: int = 30) -> bool:
        """
        Wait for a port to become available (server to start)

        Args:
            host: Host address
            port: Port number
            timeout: Maximum time to wait in seconds

        Returns:
            True if port became available
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex((host, port))
                    if result == 0:  # Connection successful
                        return True
            except Exception:
                pass

            time.sleep(0.5)

        return False

    @staticmethod
    def get_local_ip() -> str:
        """
        Get local IP address

        Returns:
            Local IP address as string
        """
        try:
            # Connect to a remote address to determine local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                local_ip = sock.getsockname()[0]
                return local_ip
        except Exception:
            return "127.0.0.1"


class ContainerClient:
    """
    HTTP client for communicating with render containers
    """

    def __init__(self, host: str = 'localhost', port: int = 8080, timeout: int = 30):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout
        self.logger = get_logger(__name__)

        # Setup session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def health_check(self) -> bool:
        """
        Check if container is healthy and responding

        Returns:
            True if container is healthy
        """
        try:
            response = self.session.get(
                urljoin(self.base_url, "/health"),
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            self.logger.debug(f"Health check failed for {self.base_url}: {e}")
            return False

    def get_status(self) -> Optional[Dict[str, Any]]:
        """
        Get container status

        Returns:
            Status dictionary or None if failed
        """
        try:
            response = self.session.get(
                urljoin(self.base_url, "/status"),
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to get status from {self.base_url}: {e}")
            return None

    def start_render(self, render_data: Dict[str, Any]) -> Optional[str]:
        """
        Start rendering on container

        Args:
            render_data: Render job data

        Returns:
            Job ID if successful, None otherwise
        """
        try:
            response = self.session.post(
                urljoin(self.base_url, "/render/start"),
                json=render_data,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            return result.get('job_id')
        except Exception as e:
            self.logger.error(f"Failed to start render on {self.base_url}: {e}")
            return None

    def get_render_progress(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get rendering progress

        Args:
            job_id: Job identifier

        Returns:
            Progress data or None if failed
        """
        try:
            response = self.session.get(
                urljoin(self.base_url, f"/render/progress/{job_id}"),
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.debug(f"Failed to get progress for job {job_id}: {e}")
            return None

    def stop_render(self, job_id: str) -> bool:
        """
        Stop rendering job

        Args:
            job_id: Job identifier

        Returns:
            True if successful
        """
        try:
            response = self.session.post(
                urljoin(self.base_url, f"/render/stop/{job_id}"),
                timeout=self.timeout
            )
            response.raise_for_status()
            return True
        except Exception as e:
            self.logger.error(f"Failed to stop job {job_id}: {e}")
            return False

    def download_result(self, job_id: str, output_path: str) -> bool:
        """
        Download render result

        Args:
            job_id: Job identifier
            output_path: Local path to save result

        Returns:
            True if successful
        """
        try:
            response = self.session.get(
                urljoin(self.base_url, f"/render/result/{job_id}"),
                timeout=self.timeout * 2,  # Longer timeout for downloads
                stream=True
            )
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True
        except Exception as e:
            self.logger.error(f"Failed to download result for job {job_id}: {e}")
            return False

    def cleanup(self):
        """Clean up session"""
        self.session.close()


class ProgressMonitor:
    """
    Monitors progress of multiple containers
    """

    def __init__(self):
        self.clients: Dict[str, ContainerClient] = {}
        self.jobs: Dict[str, str] = {}  # container_id -> job_id
        self.progress_data: Dict[str, Dict[str, Any]] = {}
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.logger = get_logger(__name__)

    def add_container(self, container_id: str, host: str, port: int):
        """
        Add container to monitor

        Args:
            container_id: Container identifier
            host: Container host
            port: Container port
        """
        client = ContainerClient(host, port)
        self.clients[container_id] = client
        self.progress_data[container_id] = {
            'status': 'idle',
            'progress': 0.0,
            'last_update': time.time()
        }

    def start_monitoring(self, update_interval: float = 2.0):
        """
        Start monitoring all containers

        Args:
            update_interval: How often to check progress in seconds
        """
        if self.monitoring:
            return

        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(update_interval,),
            daemon=True
        )
        self.monitor_thread.start()
        self.logger.info("Started progress monitoring")

    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

        # Cleanup clients
        for client in self.clients.values():
            client.cleanup()

        self.logger.info("Stopped progress monitoring")

    def _monitor_loop(self, update_interval: float):
        """Main monitoring loop"""
        while self.monitoring:
            try:
                for container_id, client in self.clients.items():
                    job_id = self.jobs.get(container_id)

                    if job_id:
                        # Get progress for active job
                        progress = client.get_render_progress(job_id)
                        if progress:
                            self.progress_data[container_id].update(progress)
                            self.progress_data[container_id]['last_update'] = time.time()
                    else:
                        # Check container status
                        status = client.get_status()
                        if status:
                            self.progress_data[container_id]['status'] = status.get('status', 'unknown')
                            self.progress_data[container_id]['last_update'] = time.time()

                time.sleep(update_interval)

            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(update_interval)

    def assign_job(self, container_id: str, job_id: str):
        """
        Assign job to container

        Args:
            container_id: Container identifier
            job_id: Job identifier
        """
        self.jobs[container_id] = job_id
        self.progress_data[container_id]['status'] = 'rendering'
        self.progress_data[container_id]['job_id'] = job_id

    def complete_job(self, container_id: str):
        """
        Mark job as complete

        Args:
            container_id: Container identifier
        """
        if container_id in self.jobs:
            del self.jobs[container_id]

        self.progress_data[container_id]['status'] = 'idle'
        self.progress_data[container_id]['progress'] = 100.0
        if 'job_id' in self.progress_data[container_id]:
            del self.progress_data[container_id]['job_id']

    def get_progress(self, container_id: str) -> Dict[str, Any]:
        """
        Get progress for specific container

        Args:
            container_id: Container identifier

        Returns:
            Progress data
        """
        return self.progress_data.get(container_id, {})

    def get_all_progress(self) -> Dict[str, Dict[str, Any]]:
        """
        Get progress for all containers

        Returns:
            Dictionary of all progress data
        """
        return self.progress_data.copy()

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of all container progress

        Returns:
            Summary statistics
        """
        total_containers = len(self.clients)
        active_jobs = len(self.jobs)

        if not self.progress_data:
            return {
                'total_containers': total_containers,
                'active_jobs': 0,
                'overall_progress': 0.0,
                'status': 'idle'
            }

        # Calculate overall progress
        total_progress = sum(data.get('progress', 0) for data in self.progress_data.values())
        overall_progress = total_progress / total_containers if total_containers > 0 else 0

        # Determine overall status
        statuses = [data.get('status', 'unknown') for data in self.progress_data.values()]
        if any(s == 'rendering' for s in statuses):
            overall_status = 'rendering'
        elif any(s == 'error' for s in statuses):
            overall_status = 'error'
        elif all(s == 'idle' for s in statuses):
            overall_status = 'idle'
        else:
            overall_status = 'mixed'

        return {
            'total_containers': total_containers,
            'active_jobs': active_jobs,
            'overall_progress': overall_progress,
            'status': overall_status,
            'container_statuses': statuses
        }