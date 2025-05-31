"""
Main render operators for distributed rendering - CLEAN VERSION
No threading, no duplicates, just clean modal operators
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty
import requests
import time
from pathlib import Path


class DISTRIB_OT_start_render(Operator):
    """Start distributed rendering across Docker containers"""
    bl_idname = "distrib.start_render"
    bl_label = "Start Distributed Render"
    bl_description = "Start distributed rendering across Docker containers"
    bl_options = {'REGISTER'}

    # Modal operator properties
    _timer = None
    _render_data = None

    def execute(self, context):
        scene = context.scene

        # Validation
        if not scene.distributed_render_enabled:
            self.report({'ERROR'}, "Distributed render not enabled")
            return {'CANCELLED'}

        if not scene.camera:
            self.report({'ERROR'}, "No active camera in scene")
            return {'CANCELLED'}

        # Initialize render process
        scene.distributed_render_status = "Initializing..."
        scene.distributed_render_progress = 0.0

        # Setup modal operator data
        self._render_data = {
            'stage': 'pack_scene',
            'working_containers': [],
            'buckets': [],
            'active_jobs': {},
            'completed_buckets': [],
            'failed_buckets': [],
            'bucket_queue': [],
            'blend_filename': None,
            'start_time': time.time(),
        }

        # Start modal operation
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)  # Check every second
        wm.modal_handler_add(self)

        self.report({'INFO'}, "Started distributed rendering")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        """Modal operator - handles the render process step by step"""

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            return self.cancel(context)

        if event.type == 'TIMER':
            try:
                result = self._process_render_stage(context)
                if result == 'FINISHED':
                    return self.finish(context)
                elif result == 'CANCELLED':
                    return self.cancel(context)
                # Continue if 'RUNNING'
            except Exception as e:
                context.scene.distributed_render_status = f"Error: {str(e)}"
                print(f"Render error: {e}")
                import traceback
                traceback.print_exc()
                return self.cancel(context)

        return {'PASS_THROUGH'}

    def finish(self, context):
        """Clean up and finish"""
        if self._timer:
            wm = context.window_manager
            wm.event_timer_remove(self._timer)
            self._timer = None
        self._render_data = None
        return {'FINISHED'}

    def cancel(self, context):
        """Cancel and clean up"""
        context.scene.distributed_render_status = "Cancelled"
        context.scene.distributed_render_progress = 0.0

        if self._timer:
            wm = context.window_manager
            wm.event_timer_remove(self._timer)
            self._timer = None

        self._render_data = None
        return {'CANCELLED'}

    def _process_render_stage(self, context):
        """Process the current stage of rendering"""
        stage = self._render_data['stage']

        if stage == 'pack_scene':
            return self._stage_pack_scene(context)
        elif stage == 'check_containers':
            return self._stage_check_containers(context)
        elif stage == 'create_buckets':
            return self._stage_create_buckets(context)
        elif stage == 'start_buckets':
            return self._stage_start_buckets(context)
        elif stage == 'monitor':
            return self._stage_monitor_progress(context)
        elif stage == 'complete':
            return 'FINISHED'
        else:
            return 'CANCELLED'

    def _stage_pack_scene(self, context):
        """Stage 1: Pack and save scene"""
        context.scene.distributed_render_status = "Packing scene..."

        try:
            blend_filename = pack_current_scene()
            self._render_data['blend_filename'] = blend_filename
            self._render_data['stage'] = 'check_containers'
            print(f"✓ Scene packed: {blend_filename}")
            return 'RUNNING'
        except Exception as e:
            context.scene.distributed_render_status = f"Pack error: {str(e)}"
            return 'CANCELLED'

    def _stage_check_containers(self, context):
        """Stage 2: Check available containers"""
        context.scene.distributed_render_status = "Checking containers..."

        working_containers = check_available_containers()

        if not working_containers:
            context.scene.distributed_render_status = "Error: No containers available"
            return 'CANCELLED'

        self._render_data['working_containers'] = working_containers
        self._render_data['stage'] = 'create_buckets'
        print(f"✓ Found {len(working_containers)} working containers")
        return 'RUNNING'

    def _stage_create_buckets(self, context):
        """Stage 3: Create render buckets"""
        context.scene.distributed_render_status = "Creating buckets..."

        buckets = create_render_buckets(context)
        self._render_data['buckets'] = buckets

        # Prepare queue of buckets to render
        working_containers = self._render_data['working_containers']
        self._render_data['bucket_queue'] = buckets[len(working_containers):]
        self._render_data['stage'] = 'start_buckets'

        print(f"✓ Created {len(buckets)} buckets")
        return 'RUNNING'

    def _stage_start_buckets(self, context):
        """Stage 4: Start initial bucket renders"""
        context.scene.distributed_render_status = "Starting renders..."

        data = self._render_data
        buckets = data['buckets']
        working_containers = data['working_containers']
        blend_filename = data['blend_filename']

        # Start initial buckets (one per container)
        for i, bucket in enumerate(buckets):
            if i < len(working_containers):
                container_port = working_containers[i]
                success = start_bucket_render(
                    container_port, bucket, blend_filename, context.scene, data['active_jobs']
                )
                if success:
                    print(f"✓ Started bucket {bucket['id']} on port {container_port}")
                else:
                    data['failed_buckets'].append(bucket)
                    print(f"✗ Failed to start bucket {bucket['id']} on port {container_port}")

        data['stage'] = 'monitor'
        return 'RUNNING'

    def _stage_monitor_progress(self, context):
        """Stage 5: Monitor progress and handle queue"""
        context.scene.distributed_render_status = "Rendering..."

        data = self._render_data
        completed_jobs = []

        # Check progress of active jobs
        for container_port, job_info in data['active_jobs'].items():
            try:
                progress_data = check_render_progress(container_port, job_info['job_id'])

                if progress_data['status'] == 'complete':
                    print(f"✓ Bucket {job_info['bucket']['id']} completed")
                    data['completed_buckets'].append(job_info['bucket'])
                    completed_jobs.append(container_port)

                elif progress_data['status'] == 'failed':
                    print(f"✗ Bucket {job_info['bucket']['id']} failed")
                    data['failed_buckets'].append(job_info['bucket'])
                    completed_jobs.append(container_port)

                elif progress_data['status'] == 'running':
                    job_info['progress'] = progress_data.get('progress', 0)

            except Exception as e:
                print(f"Error checking progress: {e}")
                data['failed_buckets'].append(job_info['bucket'])
                completed_jobs.append(container_port)

        # Assign new buckets to freed containers
        for container_port in completed_jobs:
            del data['active_jobs'][container_port]

            if data['bucket_queue']:
                next_bucket = data['bucket_queue'].pop(0)
                success = start_bucket_render(
                    container_port, next_bucket, data['blend_filename'],
                    context.scene, data['active_jobs']
                )
                if success:
                    print(f"✓ Started next bucket {next_bucket['id']}")
                else:
                    data['failed_buckets'].append(next_bucket)

        # Update progress
        total_buckets = len(data['buckets'])
        completed_count = len(data['completed_buckets'])
        progress = (completed_count / total_buckets) * 100 if total_buckets > 0 else 0
        context.scene.distributed_render_progress = progress

        # Check if complete
        if not data['active_jobs'] and not data['bucket_queue']:
            if data['failed_buckets']:
                context.scene.distributed_render_status = f"Completed with {len(data['failed_buckets'])} failed buckets"
            else:
                context.scene.distributed_render_status = "All buckets completed!"

            data['stage'] = 'complete'

        return 'RUNNING'


class DISTRIB_OT_stop_render(Operator):
    """Stop distributed rendering"""
    bl_idname = "distrib.stop_render"
    bl_label = "Stop Distributed Render"
    bl_description = "Stop the current distributed render"
    bl_options = {'REGISTER'}

    def execute(self, context):
        context.scene.distributed_render_status = "Cancelled"
        context.scene.distributed_render_progress = 0.0
        self.report({'INFO'}, "Distributed render stopped")
        return {'FINISHED'}


class DISTRIB_OT_pack_scene(Operator):
    """Pack scene resources"""
    bl_idname = "distrib.pack_scene"
    bl_label = "Pack Scene Resources"
    bl_description = "Pack all scene resources for distributed rendering"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            blend_filename = pack_current_scene()
            self.report({'INFO'}, f"Scene packed: {blend_filename}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to pack scene: {str(e)}")
            return {'CANCELLED'}


class DISTRIB_OT_preview_buckets(Operator):
    """Preview bucket layout"""
    bl_idname = "distrib.preview_buckets"
    bl_label = "Preview Buckets"
    bl_description = "Preview the current bucket layout"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        buckets_x = scene.distributed_render_buckets_x
        buckets_y = scene.distributed_render_buckets_y
        total = buckets_x * buckets_y

        print(f"=== Bucket Preview ===")
        print(f"Grid: {buckets_x} x {buckets_y} = {total} buckets")
        print(f"Containers: {scene.distributed_render_containers}")

        if scene.distributed_render_containers > total:
            print("WARNING: More containers than buckets!")

        self.report({'INFO'}, f"Preview: {total} buckets - check console")
        return {'FINISHED'}


# === UTILITY FUNCTIONS ===

def pack_current_scene():
    """Pack and save current scene to workspace"""
    # Get addon directory
    addon_dir = Path(__file__).parent.parent
    workspace_dir = addon_dir / "bucket_resources"
    workspace_dir.mkdir(exist_ok=True)

    # Pack resources
    try:
        bpy.ops.file.pack_all()
        print("✓ Packed external resources")
    except Exception as e:
        print(f"Warning: Pack failed: {e}")

    # Save scene
    blend_filename = "current_scene.blend"
    blend_path = workspace_dir / blend_filename

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), copy=True)

    if not blend_path.exists():
        raise RuntimeError(f"Failed to save: {blend_path}")

    print(f"✓ Saved: {blend_path} ({blend_path.stat().st_size} bytes)")
    return blend_filename


def check_available_containers():
    """Check which Docker containers are available"""
    ports = [8080, 8081, 8082, 8083]
    working_containers = []

    for port in ports:
        try:
            response = requests.get(f"http://localhost:{port}/health", timeout=2)
            if response.status_code == 200:
                working_containers.append(port)
        except:
            pass

    return working_containers


def create_render_buckets(context):
    """Create render buckets based on scene settings"""
    scene = context.scene
    buckets_x = scene.distributed_render_buckets_x
    buckets_y = scene.distributed_render_buckets_y

    buckets = []
    bucket_id = 0

    for y in range(buckets_y):
        for x in range(buckets_x):
            x_start = x / buckets_x
            y_start = y / buckets_y
            x_end = (x + 1) / buckets_x
            y_end = (y + 1) / buckets_y

            bucket = {
                'id': bucket_id,
                'x': x,
                'y': y,
                'x_start': x_start,
                'y_start': y_start,
                'x_end': x_end,
                'y_end': y_end
            }
            buckets.append(bucket)
            bucket_id += 1

    return buckets


def start_bucket_render(container_port, bucket, blend_filename, scene, active_jobs):
    """Start rendering a bucket on a container"""
    try:
        render_data = {
            'bucket_id': bucket['id'],
            'blend_file': blend_filename,
            'frame': scene.frame_current,
            'output_path': f'bucket_{bucket["id"]:04d}.png',
            'render_settings': {
                'engine': scene.distributed_render_engine,
                'resolution_x': scene.distributed_render_res_x,
                'resolution_y': scene.distributed_render_res_y,
                'resolution_percentage': scene.distributed_render_percentage,
                'samples': scene.distributed_render_samples if scene.distributed_render_engine == 'CYCLES' else 64,
                'device': scene.distributed_render_device if scene.distributed_render_engine == 'CYCLES' else 'CPU',
                'border_settings': {
                    'border_min_x': bucket['x_start'],
                    'border_min_y': bucket['y_start'],
                    'border_max_x': bucket['x_end'],
                    'border_max_y': bucket['y_end']
                }
            }
        }

        print(f"DEBUG: Starting bucket {bucket['id']} on port {container_port}")
        print(f"  Border: ({bucket['x_start']:.2f}, {bucket['y_start']:.2f}) -> ({bucket['x_end']:.2f}, {bucket['y_end']:.2f})")

        response = requests.post(
            f"http://localhost:{container_port}/render/start",
            json=render_data,
            timeout=10
        )

        # print(f"DEBUG: Response {response.status_code}: {response.text}")

        if response.status_code == 200:
            job_data = response.json()
            job_id = job_data.get('job_id')

            active_jobs[container_port] = {
                'job_id': job_id,
                'bucket': bucket,
                'start_time': time.time(),
                'progress': 0
            }
            return True
        else:
            print(f"ERROR: Failed to start bucket: {response.text}")
            return False

    except Exception as e:
        print(f"ERROR: Exception starting bucket: {e}")
        return False


def check_render_progress(container_port, job_id):
    """Check progress of a render job - ENHANCED DEBUG VERSION"""
    try:
        progress_url = f"http://localhost:{container_port}/render/progress/{job_id}"
        # print(f"DEBUG: Checking progress: {progress_url}")

        response = requests.get(progress_url, timeout=5)

        # print(f"DEBUG: Progress response {container_port}: Status {response.status_code}")
        # print(f"DEBUG: Progress response text: {response.text}")

        if response.status_code == 200:
            data = response.json()
            # print(f"DEBUG: Progress data: {data}")
            return data
        else:
            print(f"ERROR: Progress check failed: {response.status_code} - {response.text}")
            return {'status': 'failed', 'error': f'HTTP {response.status_code}: {response.text}'}

    except Exception as e:
        print(f"ERROR: Exception checking progress: {e}")
        return {'status': 'failed', 'error': str(e)}


# Registration
classes = [
    DISTRIB_OT_start_render,
    DISTRIB_OT_stop_render,
    DISTRIB_OT_pack_scene,
    DISTRIB_OT_preview_buckets,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)