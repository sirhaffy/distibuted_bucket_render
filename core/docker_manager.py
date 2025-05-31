"""
Docker manager for distributed rendering
Handles Docker container lifecycle and communication
"""

import subprocess
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path
from ..utils.logging_utils import get_logger, PerformanceTimer
from ..utils.network_utils import NetworkUtils


@dataclass
class RenderContainer:
    """
    Represents a Docker container for rendering
    """
    id: str
    name: str
    port: int
    status: str = "starting"  # starting, ready, busy, error, stopped
    current_bucket: Optional[int] = None
    start_time: Optional[float] = None
    last_activity: Optional[float] = None
    cpu_usage: float = 0.0
    memory_usage: float = 0.0

    def is_available(self) -> bool:
        """Check if container is available for new work"""
        return self.status == "ready"

    def is_healthy(self) -> bool:
        """Check if container is healthy"""
        return self.status in ["ready", "busy"] and self.last_activity and (time.time() - self.last_activity) < 300


class DockerManager:
    """
    Manages Docker containers for distributed rendering
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.prefs = context.preferences.addons[__package__.split('.')[0]].preferences
        self.logger = get_logger(__name__)

        self.containers: List[RenderContainer] = []
        self.base_port = self.prefs.base_port
        self.docker_image = self.prefs.docker_image
        self.max_containers = min(self.scene.distributed_render_containers, self.prefs.max_containers)

        # Paths
        self.temp_dir = Path(self.context.blend_data.filepath).parent / "bucket_resources"
        self.container_logs_dir = self.temp_dir / "container_logs"
        self.container_logs_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"DockerManager initialized - max containers: {self.max_containers}")

    def start_containers(self) -> List[RenderContainer]:
        """
        Start Docker containers for rendering

        Returns:
            List of started containers
        """
        self.logger.info(f"Starting {self.max_containers} Docker containers...")

        with PerformanceTimer("container_startup", "docker"):
            # Check Docker availability
            if not self._check_docker_available():
                raise RuntimeError("Docker is not available or not working")

            # Check if image exists
            if not self._check_image_exists():
                raise RuntimeError(f"Docker image '{self.docker_image}' not found")

            # Start containers
            for i in range(self.max_containers):
                container = self._start_single_container(i)
                if container:
                    self.containers.append(container)

            # Wait for containers to be ready
            self._wait_for_containers_ready()

        self.logger.info(f"Successfully started {len(self.containers)} containers")
        return self.containers

    def _check_docker_available(self) -> bool:
        """Check if Docker is available and working"""
        try:
            result = subprocess.run(
                [self.prefs.docker_executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                self.logger.info(f"Docker available: {result.stdout.strip()}")
                return True
            else:
                self.logger.error(f"Docker not working: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self.logger.error("Docker command timed out")
            return False
        except FileNotFoundError:
            self.logger.error(f"Docker executable not found: {self.prefs.docker_executable}")
            return False
        except Exception as e:
            self.logger.error(f"Error checking Docker: {e}")
            return False

    def _check_image_exists(self) -> bool:
        """Check if Docker image exists"""
        try:
            result = subprocess.run(
                [self.prefs.docker_executable, "images", self.docker_image, "--format", "{{.Repository}}:{{.Tag}}"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if self.docker_image in result.stdout:
                self.logger.info(f"Docker image found: {self.docker_image}")
                return True
            else:
                self.logger.error(f"Docker image not found: {self.docker_image}")
                return False

        except Exception as e:
            self.logger.error(f"Error checking Docker image: {e}")
            return False

    def _start_single_container(self, container_index: int) -> Optional[RenderContainer]:
        """
        Start a single Docker container

        Args:
            container_index: Index of container to start

        Returns:
            RenderContainer object if successful, None otherwise
        """
        container_name = f"blender-render-{container_index:02d}"
        port = self.base_port + container_index

        try:
            # Check if port is available
            if not NetworkUtils.is_port_available(port):
                self.logger.warning(f"Port {port} is not available, trying next port")
                port = NetworkUtils.find_available_port(self.base_port + 100, self.base_port + 200)
                if not port:
                    self.logger.error("No available ports found")
                    return None

            # Remove existing container with same name
            self._remove_container(container_name)

            # Build Docker command
            docker_cmd = [
                self.prefs.docker_executable, "run",
                "--name", container_name,
                "--detach",
                "--rm",  # Auto-remove when stopped
                "-p", f"{port}:8080",  # Map container port 8080 to host port
                "-v", f"{self.temp_dir}:/workspace",  # Mount workspace
                "--memory", self.prefs.container_memory,
                "--cpus", "2.0",  # Limit CPU usage
                self.docker_image
            ]

            # Start container
            self.logger.debug(f"Starting container: {' '.join(docker_cmd)}")
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                container_id = result.stdout.strip()
                container = RenderContainer(
                    id=container_id,
                    name=container_name,
                    port=port,
                    status="starting",
                    start_time=time.time()
                )

                self.logger.info(f"Started container {container_name} (ID: {container_id[:12]}) on port {port}")
                return container
            else:
                self.logger.error(f"Failed to start container {container_name}: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout starting container {container_name}")
            return None
        except Exception as e:
            self.logger.error(f"Error starting container {container_name}: {e}")
            return None

    def _wait_for_containers_ready(self, timeout: int = 120):
        """
        Wait for all containers to be ready

        Args:
            timeout: Maximum time to wait in seconds
        """
        self.logger.info("Waiting for containers to be ready...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            ready_count = 0

            for container in self.containers:
                if container.status == "ready":
                    ready_count += 1
                elif container.status == "starting":
                    # Check if container is ready
                    if self._check_container_ready(container):
                        container.status = "ready"
                        container.last_activity = time.time()
                        ready_count += 1
                        self.logger.info(f"Container {container.name} is ready")

            if ready_count == len(self.containers):
                self.logger.info(f"All {ready_count} containers are ready")
                return

            time.sleep(2)

        # Timeout reached
        ready_containers = [c for c in self.containers if c.status == "ready"]
        self.logger.warning(f"Timeout waiting for containers - {len(ready_containers)}/{len(self.containers)} ready")

        # Remove containers that didn't start properly
        failed_containers = [c for c in self.containers if c.status != "ready"]
        for container in failed_containers:
            self.logger.error(f"Container {container.name} failed to start, removing")
            self._stop_container(container)
            self.containers.remove(container)

    def _check_container_ready(self, container: RenderContainer) -> bool:
        """
        Check if a container is ready to accept work

        Args:
            container: Container to check

        Returns:
            True if container is ready
        """
        try:
            # Check if container is running
            result = subprocess.run(
                [self.prefs.docker_executable, "ps", "--filter", f"id={container.id}", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if "Up" not in result.stdout:
                return False

            # Try to connect to container's HTTP endpoint
            import requests
            response = requests.get(f"http://localhost:{container.port}/health", timeout=5)

            if response.status_code == 200:
                return True

        except Exception as e:
            self.logger.debug(f"Container {container.name} not ready yet: {e}")

        return False

    def get_available_container(self) -> Optional[RenderContainer]:
        """
        Get an available container for rendering

        Returns:
            Available container or None if none available
        """
        for container in self.containers:
            if container.is_available():
                return container
        return None

    def assign_bucket_to_container(self, container: RenderContainer, bucket_id: int) -> bool:
        """
        Assign a bucket to a container for rendering

        Args:
            container: Container to assign work to
            bucket_id: ID of bucket to render

        Returns:
            True if assignment successful
        """
        try:
            container.status = "busy"
            container.current_bucket = bucket_id
            container.last_activity = time.time()

            self.logger.info(f"Assigned bucket {bucket_id} to container {container.name}")
            return True

        except Exception as e:
            self.logger.error(f"Error assigning bucket {bucket_id} to container {container.name}: {e}")
            container.status = "error"
            return False

    def get_container_status(self, container: RenderContainer) -> Dict[str, Any]:
        """
        Get detailed status of a container

        Args:
            container: Container to check

        Returns:
            Dictionary with container status information
        """
        try:
            # Get Docker stats
            result = subprocess.run(
                [self.prefs.docker_executable, "stats", container.id, "--no-stream", "--format",
                 "{{.CPUPerc}},{{.MemUsage}}"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 and result.stdout.strip():
                stats = result.stdout.strip().split(',')
                if len(stats) >= 2:
                    cpu_str = stats[0].replace('%', '')
                    try:
                        container.cpu_usage = float(cpu_str)
                    except ValueError:
                        pass

            return {
                'name': container.name,
                'status': container.status,
                'current_bucket': container.current_bucket,
                'cpu_usage': container.cpu_usage,
                'memory_usage': container.memory_usage,
                'uptime': time.time() - container.start_time if container.start_time else 0,
                'last_activity': container.last_activity
            }

        except Exception as e:
            self.logger.error(f"Error getting container status for {container.name}: {e}")
            return {
                'name': container.name,
                'status': 'error',
                'error': str(e)
            }

    def _stop_container(self, container: RenderContainer):
        """
        Stop a specific container

        Args:
            container: Container to stop
        """
        try:
            self.logger.info(f"Stopping container {container.name}")

            subprocess.run(
                [self.prefs.docker_executable, "stop", container.id],
                capture_output=True,
                timeout=30
            )

            container.status = "stopped"

        except Exception as e:
            self.logger.error(f"Error stopping container {container.name}: {e}")

    def _remove_container(self, container_name: str):
        """
        Remove container by name (cleanup)

        Args:
            container_name: Name of container to remove
        """
        try:
            subprocess.run(
                [self.prefs.docker_executable, "rm", "-f", container_name],
                capture_output=True,
                timeout=30
            )
        except Exception:
            pass  # Ignore errors when removing (container might not exist)

    def cleanup_containers(self):
        """
        Stop and clean up all containers
        """
        self.logger.info("Cleaning up Docker containers...")

        with PerformanceTimer("container_cleanup", "docker"):
            for container in self.containers:
                self._stop_container(container)

            # Clear container list
            self.containers.clear()

        self.logger.info("Container cleanup complete")

    def get_all_container_status(self) -> List[Dict[str, Any]]:
        """
        Get status of all containers

        Returns:
            List of container status dictionaries
        """
        return [self.get_container_status(container) for container in self.containers]

    def restart_failed_containers(self) -> int:
        """
        Restart containers that have failed

        Returns:
            Number of containers restarted
        """
        failed_containers = [c for c in self.containers if not c.is_healthy()]
        restarted_count = 0

        for container in failed_containers:
            self.logger.warning(f"Restarting failed container {container.name}")

            # Stop old container
            self._stop_container(container)
            self.containers.remove(container)

            # Start new container
            new_container = self._start_single_container(len(self.containers))
            if new_container:
                self.containers.append(new_container)
                restarted_count += 1

        return restarted_count