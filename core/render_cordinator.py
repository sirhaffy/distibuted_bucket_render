"""
Render coordinator for distributed rendering
Coordinates bucket distribution and progressive assembly across containers
"""

import threading
import time
import queue
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass
from pathlib import Path

from .bucket_splitter import RenderBucket
from .docker_manager import RenderContainer
from ..utils.logging_utils import get_logger, PerformanceTimer
from ..utils.network_utils import ContainerClient, ProgressMonitor


@dataclass
class RenderJob:
    """
    Represents a render job for a specific bucket
    """
    bucket: RenderBucket
    container: RenderContainer
    client: ContainerClient
    job_id: Optional[str] = None
    start_time: Optional[float] = None
    progress: float = 0.0
    status: str = "queued"  # queued, starting, rendering, complete, failed
    error_message: Optional[str] = None
    output_path: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class RenderStats:
    """
    Statistics for the rendering process
    """
    total_buckets: int = 0
    completed_buckets: int = 0
    failed_buckets: int = 0
    active_jobs: int = 0
    total_render_time: float = 0.0
    average_bucket_time: float = 0.0
    estimated_completion: Optional[float] = None
    throughput: float = 0.0  # buckets per minute


class RenderCoordinator:
    """
    Coordinates distributed rendering across multiple containers
    """

    def __init__(self, context, containers: List[RenderContainer], buckets: List[RenderBucket]):
        self.context = context
        self.scene = context.scene
        self.prefs = context.preferences.addons[__package__.split('.')[0]].preferences
        self.logger = get_logger(__name__)

        self.containers = containers
        self.buckets = buckets
        self.bucket_queue = queue.Queue()
        self.completed_buckets: List[RenderBucket] = []
        self.failed_buckets: List[RenderBucket] = []
        self.active_jobs: Dict[str, RenderJob] = {}  # container_id -> job

        # Progress monitoring
        self.progress_monitor = ProgressMonitor()
        self.stats = RenderStats(total_buckets=len(buckets))

        # Control flags
        self.should_stop = threading.Event()
        self.coordinator_thread: Optional[threading.Thread] = None
        self.assembly_thread: Optional[threading.Thread] = None

        # Callbacks
        self.progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.bucket_complete_callback: Optional[Callable[[RenderBucket], None]] = None

        # Paths
        self.output_dir = Path(self.prefs.temp_directory) / "bucket_output"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"RenderCoordinator initialized - {len(containers)} containers, {len(buckets)} buckets")

    def start_rendering(self) -> List[RenderBucket]:
        """
        Start the distributed rendering process

        Returns:
            List of completed buckets when rendering is done
        """
        self.logger.info("Starting distributed rendering coordination...")

        with PerformanceTimer("distributed_render", "coordinator"):
            # Initialize progress monitoring
            self._setup_progress_monitoring()

            # Populate bucket queue
            self._populate_bucket_queue()

            # Start coordinator thread
            self.coordinator_thread = threading.Thread(
                target=self._coordination_loop,
                daemon=True,
                name="RenderCoordinator"
            )
            self.coordinator_thread.start()

            # Start progressive assembly if enabled
            if self.scene.distributed_render_progressive:
                self.assembly_thread = threading.Thread(
                    target=self._progressive_assembly_loop,
                    daemon=True,
                    name="ProgressiveAssembly"
                )
                self.assembly_thread.start()

            # Wait for completion
            self._wait_for_completion()

            # Cleanup
            self._cleanup()

        self.logger.info(f"Distributed rendering complete - {len(self.completed_buckets)} buckets rendered")
        return self.completed_buckets

    def stop_rendering(self):
        """Stop the rendering process"""
        self.logger.info("Stopping distributed rendering...")
        self.should_stop.set()

        # Stop all active jobs
        for job in self.active_jobs.values():
            if job.client and job.job_id:
                job.client.stop_render(job.job_id)

        # Update scene status
        self.scene.distributed_render_status = "Cancelled"

    def _setup_progress_monitoring(self):
        """Setup progress monitoring for all containers"""
        for container in self.containers:
            self.progress_monitor.add_container(
                container.id,
                'localhost',
                container.port
            )

        self.progress_monitor.start_monitoring(
            update_interval=self.prefs.progressive_update_interval
        )

    def _populate_bucket_queue(self):
        """Populate the bucket queue with buckets to render"""
        for bucket in self.buckets:
            self.bucket_queue.put(bucket)

        self.logger.info(f"Populated bucket queue with {self.bucket_queue.qsize()} buckets")

    def _coordination_loop(self):
        """Main coordination loop - assigns buckets to available containers"""
        self.logger.info("Starting coordination loop...")

        start_time = time.time()

        while not self.should_stop.is_set():
            try:
                # Update statistics
                self._update_statistics()

                # Check for completed jobs
                self._check_completed_jobs()

                # Assign new work to available containers
                self._assign_work_to_containers()

                # Check if we're done
                if self._is_rendering_complete():
                    self.logger.info("All buckets completed, stopping coordination")
                    break

                # Brief pause before next iteration
                time.sleep(1.0)

            except Exception as e:
                self.logger.error(f"Error in coordination loop: {e}")
                time.sleep(2.0)

        total_time = time.time() - start_time
        self.stats.total_render_time = total_time
        self.logger.info(f"Coordination loop finished - total time: {total_time:.1f}s")

    def _assign_work_to_containers(self):
        """Assign buckets to available containers"""
        for container in self.containers:
            # Skip if container already has work or isn't healthy
            if container.id in self.active_jobs or not container.is_healthy():
                continue

            # Get next bucket from queue
            try:
                bucket = self.bucket_queue.get_nowait()
            except queue.Empty:
                continue  # No more buckets to assign

            # Create render job
            success = self._start_bucket_render(container, bucket)
            if not success:
                # Put bucket back in queue for retry
                self.bucket_queue.put(bucket)
                self.logger.warning(f"Failed to start bucket {bucket.id}, will retry")

    def _start_bucket_render(self, container: RenderContainer, bucket: RenderBucket) -> bool:
        """
        Start rendering a bucket on a container

        Args:
            container: Container to use for rendering
            bucket: Bucket to render

        Returns:
            True if successfully started
        """
        try:
            # Create client for this container
            client = ContainerClient('localhost', container.port)

            # Prepare render data
            render_data = self._prepare_render_data(bucket)

            # Start render job
            job_id = client.start_render(render_data)
            if not job_id:
                return False

            # Create job tracking
            job = RenderJob(
                bucket=bucket,
                container=container,
                client=client,
                job_id=job_id,
                start_time=time.time(),
                status="starting"
            )

            # Track job
            self.active_jobs[container.id] = job
            bucket.status = "rendering"
            bucket.assigned_container = container.id
            bucket.start_time = time.time()

            # Update progress monitor
            self.progress_monitor.assign_job(container.id, job_id)

            self.logger.info(f"Started bucket {bucket.id} on container {container.name}")
            return True

        except Exception as e:
            self.logger.error(f"Error starting bucket {bucket.id} on container {container.name}: {e}")
            return False

    def _prepare_render_data(self, bucket: RenderBucket) -> Dict[str, Any]:
        """
        Prepare render data for a bucket

        Args:
            bucket: Bucket to prepare data for

        Returns:
            Dictionary with render job data
        """
        border_settings = bucket.get_border_settings()

        render_data = {
            'bucket_id': bucket.id,
            'blend_file': 'packed_scene/scene.blend',
            'frame': self.scene.frame_current,
            'render_settings': {
                'engine': self.scene.render.engine,
                'resolution_x': self.scene.render.resolution_x,
                'resolution_y': self.scene.render.resolution_y,
                'resolution_percentage': self.scene.render.resolution_percentage,
                'use_border': True,
                'border_min_x': border_settings['border_min_x'],
                'border_min_y': border_settings['border_min_y'],
                'border_max_x': border_settings['border_max_x'],
                'border_max_y': border_settings['border_max_y'],
                'use_crop_to_border': False,
                'file_format': self.scene.render.image_settings.file_format,
                'color_mode': self.scene.render.image_settings.color_mode,
            },
            'output_path': f'bucket_output/bucket_{bucket.id:04d}.png',
            'priority': bucket.priority
        }

        # Add engine-specific settings
        if self.scene.render.engine == 'CYCLES':
            render_data['render_settings'].update({
                'samples': getattr(self.scene.cycles, 'samples', 128),
                'use_denoising': getattr(self.scene.cycles, 'use_denoising', True),
            })

        return render_data

    def _check_completed_jobs(self):
        """Check for completed render jobs"""
        completed_container_ids = []

        for container_id, job in self.active_jobs.items():
            try:
                # Get progress from progress monitor
                progress_data = self.progress_monitor.get_progress(container_id)

                if progress_data:
                    job.progress = progress_data.get('progress', 0.0)
                    status = progress_data.get('status', 'unknown')

                    if status == 'complete':
                        # Job completed successfully
                        self._handle_job_completion(job, True)
                        completed_container_ids.append(container_id)

                    elif status == 'error':
                        # Job failed
                        error_msg = progress_data.get('error', 'Unknown error')
                        self._handle_job_completion(job, False, error_msg)
                        completed_container_ids.append(container_id)

                    elif status == 'rendering':
                        # Update progress
                        job.bucket.status = "rendering"

                        # Call progress callback if set
                        if self.progress_callback:
                            self.progress_callback({
                                'bucket_id': job.bucket.id,
                                'progress': job.progress,
                                'container': job.container.name
                            })

            except Exception as e:
                self.logger.error(f"Error checking job progress for container {container_id}: {e}")
                # Assume job failed
                self._handle_job_completion(job, False, str(e))
                completed_container_ids.append(container_id)

        # Remove completed jobs
        for container_id in completed_container_ids:
            if container_id in self.active_jobs:
                del self.active_jobs[container_id]
            self.progress_monitor.complete_job(container_id)

    def _handle_job_completion(self, job: RenderJob, success: bool, error_message: Optional[str] = None):
        """
        Handle completion of a render job

        Args:
            job: Completed job
            success: Whether job completed successfully
            error_message: Error message if job failed
        """
        bucket = job.bucket
        bucket.end_time = time.time()

        if success:
            # Download result
            output_path = self.output_dir / f"bucket_{bucket.id:04d}.png"
            download_success = job.client.download_result(job.job_id, str(output_path))

            if download_success:
                bucket.status = "complete"
                bucket.output_path = str(output_path)
                self.completed_buckets.append(bucket)
                self.stats.completed_buckets += 1

                self.logger.info(f"Bucket {bucket.id} completed successfully")

                # Call completion callback
                if self.bucket_complete_callback:
                    self.bucket_complete_callback(bucket)
            else:
                success = False
                error_message = "Failed to download result"

        if not success:
            # Handle failure
            job.retry_count += 1
            job.error_message = error_message

            if job.retry_count < job.max_retries:
                # Retry bucket
                bucket.status = "pending"
                bucket.assigned_container = None
                self.bucket_queue.put(bucket)
                self.logger.warning(
                    f"Bucket {bucket.id} failed, retrying ({job.retry_count}/{job.max_retries}): {error_message}")
            else:
                # Give up on this bucket
                bucket.status = "failed"
                self.failed_buckets.append(bucket)
                self.stats.failed_buckets += 1
                self.logger.error(
                    f"Bucket {bucket.id} failed permanently after {job.retry_count} retries: {error_message}")

        # Cleanup client
        job.client.cleanup()

    def _progressive_assembly_loop(self):
        """Progressive assembly loop - assembles buckets as they complete"""
        self.logger.info("Starting progressive assembly loop...")

        assembled_buckets = set()

        while not self.should_stop.is_set():
            try:
                # Check for newly completed buckets
                for bucket in self.completed_buckets:
                    if bucket.id not in assembled_buckets and bucket.output_path:
                        # Assemble this bucket into the main image
                        self._assemble_bucket(bucket)
                        assembled_buckets.add(bucket.id)

                        self.logger.info(f"Assembled bucket {bucket.id} progressively")

                time.sleep(2.0)  # Check every 2 seconds

            except Exception as e:
                self.logger.error(f"Error in progressive assembly: {e}")
                time.sleep(5.0)

        self.logger.info("Progressive assembly loop finished")

    def _assemble_bucket(self, bucket: RenderBucket):
        """
        Assemble a single bucket into the main render

        Args:
            bucket: Bucket to assemble
        """
        try:
            # This would integrate with the image compositor
            # For now, just log that we would assemble
            from .image_compositor import ImageCompositor

            compositor = ImageCompositor(self.context)
            compositor.add_bucket_to_composition(bucket)

        except Exception as e:
            self.logger.error(f"Error assembling bucket {bucket.id}: {e}")

    def _update_statistics(self):
        """Update rendering statistics"""
        self.stats.active_jobs = len(self.active_jobs)

        # Calculate average bucket time
        completed_times = []
        for bucket in self.completed_buckets:
            if bucket.start_time and bucket.end_time:
                completed_times.append(bucket.end_time - bucket.start_time)

        if completed_times:
            self.stats.average_bucket_time = sum(completed_times) / len(completed_times)

            # Estimate completion time
            remaining_buckets = self.stats.total_buckets - self.stats.completed_buckets
            if remaining_buckets > 0 and self.stats.average_bucket_time > 0:
                # Account for parallel processing
                parallel_factor = min(len(self.containers), remaining_buckets)
                estimated_seconds = (remaining_buckets * self.stats.average_bucket_time) / parallel_factor
                self.stats.estimated_completion = time.time() + estimated_seconds

            # Calculate throughput
            if self.stats.total_render_time > 0:
                self.stats.throughput = (self.stats.completed_buckets / self.stats.total_render_time) * 60  # per minute

    def _is_rendering_complete(self) -> bool:
        """Check if rendering is complete"""
        total_processed = len(self.completed_buckets) + len(self.failed_buckets)
        queue_empty = self.bucket_queue.empty()
        no_active_jobs = len(self.active_jobs) == 0

        return queue_empty and no_active_jobs and total_processed >= self.stats.total_buckets

    def _wait_for_completion(self):
        """Wait for rendering to complete"""
        self.logger.info("Waiting for rendering completion...")

        # Update scene status
        self.scene.distributed_render_status = "Rendering"

        if self.coordinator_thread:
            self.coordinator_thread.join()

        # Final status update
        if len(self.failed_buckets) == 0:
            self.scene.distributed_render_status = "Complete"
        elif len(self.completed_buckets) > 0:
            self.scene.distributed_render_status = "Partial"
        else:
            self.scene.distributed_render_status = "Failed"

    def _cleanup(self):
        """Cleanup resources"""
        self.logger.info("Cleaning up render coordinator...")

        # Stop progress monitoring
        self.progress_monitor.stop_monitoring()

        # Cleanup any remaining clients
        for job in self.active_jobs.values():
            if job.client:
                job.client.cleanup()

        self.logger.info("Render coordinator cleanup complete")

    def get_stats(self) -> RenderStats:
        """Get current rendering statistics"""
        return self.stats

    def set_progress_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for progress updates"""
        self.progress_callback = callback

    def set_bucket_complete_callback(self, callback: Callable[[RenderBucket], None]):
        """Set callback for bucket completion"""
        self.bucket_complete_callback = callback