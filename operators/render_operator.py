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


# Live preview image name
LIVE_PREVIEW_NAME = "DistributedRender_Live"

# Module-level storage for completed job info (accessible by Download RAW operator)
LAST_RENDER_JOBS = []


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

        print("=== START DISTRIBUTED RENDER ===")

        # Validation
        if not scene.distributed_render_enabled:
            self.report({'ERROR'}, "Distributed render not enabled - check the checkbox in panel header")
            print("ERROR: distributed_render_enabled is False")
            return {'CANCELLED'}

        if not scene.camera:
            self.report({'ERROR'}, "No active camera in scene")
            print("ERROR: No camera")
            return {'CANCELLED'}

        print(f"Camera: {scene.camera.name}")
        print(f"Resolution: {scene.render.resolution_x}x{scene.render.resolution_y} @ {scene.render.resolution_percentage}%")
        print(f"Engine: {scene.render.engine}")
        print(f"Buckets: {scene.distributed_render_bucket_count}x{scene.distributed_render_bucket_count}")
        # Initialize render process
        scene.distributed_render_status = "Initializing..."
        scene.distributed_render_progress = 0.0
        scene.distributed_render_abort = False

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
            'live_image': None,
            'completed_jobs_info': [],  # port + job_id for EXR download later
        }

        # Create live preview image and open render view
        self._setup_live_preview(context)

        # Start modal operation
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)

        self.report({'INFO'}, "Started distributed rendering")
        return {'RUNNING_MODAL'}

    def _setup_live_preview(self, context):
        """Create the live preview image and show it in an Image Editor"""
        scene = context.scene
        render = scene.render
        final_width = int(render.resolution_x * render.resolution_percentage / 100)
        final_height = int(render.resolution_y * render.resolution_percentage / 100)

        print(f"Setting up live preview: {final_width}x{final_height}")

        # Always create a fresh live image
        if LIVE_PREVIEW_NAME in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[LIVE_PREVIEW_NAME])
        img = bpy.data.images.new(LIVE_PREVIEW_NAME, final_width, final_height, alpha=True)

        # Fill with dark gray so the user sees something
        pixel_count = final_width * final_height * 4
        pixels = [0.0] * pixel_count
        for i in range(0, pixel_count, 4):
            pixels[i] = 0.05      # R
            pixels[i + 1] = 0.05  # G
            pixels[i + 2] = 0.05  # B
            pixels[i + 3] = 1.0   # A
        img.pixels[:] = pixels
        img.update()

        self._render_data['live_image'] = img

        # Try to show in an existing Image Editor
        shown = False
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                for space in area.spaces:
                    if space.type == 'IMAGE_EDITOR':
                        space.image = img
                        shown = True
                        break
                if shown:
                    break

        # If no Image Editor open, change a 3D viewport to Image Editor
        if not shown:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.type = 'IMAGE_EDITOR'
                    for space in area.spaces:
                        if space.type == 'IMAGE_EDITOR':
                            space.image = img
                            break
                    shown = True
                    print("Converted a 3D viewport to Image Editor for live preview")
                    break

        if shown:
            print(f"Live preview ready: {LIVE_PREVIEW_NAME}")
        else:
            print("WARNING: Could not find area to show live preview. Open an Image Editor manually.")

    def modal(self, context, event):
        """Modal operator - handles the render process step by step"""

        if event.type in {'RIGHTMOUSE', 'ESC'} or context.scene.distributed_render_abort:
            return self.cancel(context)

        if event.type == 'TIMER':
            try:
                # Run all setup stages in one tick until we reach monitor/complete
                while True:
                    result = self._process_render_stage(context)
                    if result == 'FINISHED':
                        return self.finish(context)
                    elif result == 'CANCELLED':
                        return self.cancel(context)
                    # If we're now in monitor stage, break and let timer handle polling
                    if self._render_data['stage'] == 'monitor':
                        break
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

        # Delete local temp blend file (keep container files for EXR download later)
        if self._render_data:
            blend_path = self._render_data.get('blend_path')
            if blend_path:
                try:
                    Path(blend_path).unlink()
                except:
                    pass

        self._render_data = None
        return {'FINISHED'}

    # This function is called when a bucket render is completed to download the rendered image and place it in the live preview
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

    # === RENDER STAGE FUNCTIONS ===
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

    # Each stage function returns 'RUNNING' to continue, 'CANCELLED' to stop with error, or 'FINISHED' if done (only for monitor stage)
    def _stage_pack_scene(self, context):
        """Stage 1: Pack and save scene"""
        context.scene.distributed_render_status = "Packing scene..."

        try:
            blend_path, blend_filename = pack_current_scene()
            self._render_data['blend_path'] = blend_path
            self._render_data['blend_filename'] = blend_filename
            self._render_data['stage'] = 'check_containers'
            print(f"Scene packed: {blend_filename}")
            return 'RUNNING'
        except Exception as e:
            context.scene.distributed_render_status = f"Pack error: {str(e)}"
            return 'CANCELLED'

    # This stage checks which containers are available and uploads the .blend file to them. It also initializes the render queue based on the number of working containers.
    def _stage_check_containers(self, context):
        """Stage 2: Check available containers and upload .blend to each"""
        context.scene.distributed_render_status = "Checking containers..."

        working_containers = check_available_containers(context.scene)

        if not working_containers:
            context.scene.distributed_render_status = "Error: No containers available"
            return 'CANCELLED'

        # Upload .blend to all containers
        blend_path = self._render_data['blend_path']
        blend_filename = self._render_data['blend_filename']

        context.scene.distributed_render_status = "Uploading scene to containers..."
        uploaded_containers = []

        for port in working_containers:
            success = upload_blend_to_container(port, blend_path, blend_filename)
            if success:
                uploaded_containers.append(port)
                print(f"Uploaded to container on port {port}")
            else:
                print(f"Failed to upload to container on port {port}")

        if not uploaded_containers:
            context.scene.distributed_render_status = "Error: Upload failed to all containers"
            return 'CANCELLED'

        self._render_data['working_containers'] = uploaded_containers
        self._render_data['stage'] = 'create_buckets'
        print(f"Found {len(uploaded_containers)} working containers, scene uploaded")
        return 'RUNNING'

    # This stage creates the bucket definitions based on the scene settings and prepares the queue for rendering
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

    # This is the main loop that monitors progress, handles completed buckets, and assigns new buckets to containers as they finish
    def _stage_monitor_progress(self, context):
        """Stage 5: Monitor progress and handle queue"""
        context.scene.distributed_render_status = "Rendering..."

        data = self._render_data
        completed_jobs = []

        # Check progress of active jobs
        for container_port, job_info in list(data['active_jobs'].items()):
            try:
                progress_data = check_render_progress(container_port, job_info['job_id'])

                if progress_data['status'] == 'complete':
                    print(f"Bucket {job_info['bucket']['id']} completed")
                    data['completed_buckets'].append(job_info['bucket'])
                    data['completed_jobs_info'].append({
                        'port': container_port,
                        'job_id': job_info['job_id'],
                        'bucket': job_info['bucket'],
                    })
                    completed_jobs.append(container_port)

                    # Download bucket image from container and place in live preview
                    try:
                        self._download_and_place_bucket(context, container_port, job_info)
                    except Exception as e:
                        print(f"  Warning: Failed to place bucket {job_info['bucket']['id']} in live view: {e}")
                        import traceback
                        traceback.print_exc()

                elif progress_data['status'] == 'failed':
                    print(f"Bucket {job_info['bucket']['id']} failed: {progress_data.get('error_message', 'unknown')}")
                    data['failed_buckets'].append(job_info['bucket'])
                    completed_jobs.append(container_port)

                elif progress_data['status'] == 'running':
                    job_info['progress'] = progress_data.get('progress', 0)

            except Exception as e:
                print(f"Error checking progress on port {container_port}: {e}")
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
                    print(f"Started next bucket {next_bucket['id']}")
                else:
                    data['failed_buckets'].append(next_bucket)

        # Update progress
        total_buckets = len(data['buckets'])
        completed_count = len(data['completed_buckets'])
        progress = (completed_count / total_buckets) * 100 if total_buckets > 0 else 0
        context.scene.distributed_render_progress = progress
        context.scene.distributed_render_status = f"Rendering... {completed_count}/{total_buckets} buckets"

        # Check if complete
        if not data['active_jobs'] and not data['bucket_queue']:
            if data['failed_buckets']:
                context.scene.distributed_render_status = f"Done ({len(data['failed_buckets'])} failed)"
            else:
                elapsed = time.time() - data['start_time']
                context.scene.distributed_render_status = f"All {total_buckets} buckets done in {elapsed:.1f}s"

            # Store job info for later EXR download
            global LAST_RENDER_JOBS
            LAST_RENDER_JOBS = list(data['completed_jobs_info'])

            data['stage'] = 'complete'

        return 'RUNNING'

    # End of modal operator definition - utility functions below
    def _download_and_place_bucket(self, context, container_port, job_info):
        """Download rendered bucket from container and place it in live preview"""
        try:
            import tempfile

            data = self._render_data
            live_img = data.get('live_image')
            if not live_img:
                print(f"  WARNING: live_image is None, skipping bucket placement")
                return

            bucket = job_info['bucket']
            job_id = job_info['job_id']

            print(f"  Downloading bucket {bucket['id']} from port {container_port}...")

            # Download PNG preview from container (files stay on container for later EXR download)
            response = requests.get(
                f"http://localhost:{container_port}/render/result/{job_id}",
                timeout=30
            )

            if response.status_code != 200:
                print(f"  Failed to download bucket {bucket['id']}: {response.status_code}")
                return

            # Save PNG to temp file so Blender can load it
            temp_dir = Path(tempfile.gettempdir()) / "distributed_render" / "buckets"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / f"bucket_{bucket['id']:04d}.png"
            temp_file.write_bytes(response.content)

            # Place in live preview
            scene = context.scene

            final_width = live_img.size[0]
            final_height = live_img.size[1]

            # Load bucket image temporarily into Blender
            temp_name = f"_live_bucket_{bucket['id']}"
            if temp_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[temp_name])

            bucket_img = bpy.data.images.load(str(temp_file))
            bucket_img.name = temp_name

            b_width = bucket_img.size[0]
            b_height = bucket_img.size[1]
            bucket_pixels = list(bucket_img.pixels[:])

            # Use pixel-exact position from bucket (no rounding needed)
            offset_x = bucket['px_start']
            offset_y = bucket['py_start']

            # Use the actual downloaded image dimensions (avoids rounding mismatches)
            copy_w = min(b_width, final_width - offset_x)
            copy_h = min(b_height, final_height - offset_y)

            # Read current live image pixels
            pixels = list(live_img.pixels[:])
            total_pixels = len(pixels)

            # Copy bucket pixels into the correct position
            for row in range(copy_h):
                dst_y = offset_y + row
                if dst_y >= final_height:
                    break

                src_start = row * b_width * 4
                copy_width = copy_w * 4
                dst_start = (dst_y * final_width + offset_x) * 4

                if dst_start + copy_width > total_pixels:
                    copy_width = total_pixels - dst_start
                if copy_width <= 0:
                    break

                pixels[dst_start:dst_start + copy_width] = bucket_pixels[src_start:src_start + copy_width]

            # Write back and update
            live_img.pixels[:] = pixels
            live_img.update()

            # Remove temp Blender image (keep EXR file for final assembly)
            bpy.data.images.remove(bucket_img)

            # Force redraw of Image Editor areas
            for area in context.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    area.tag_redraw()

            print(f"  Placed bucket {bucket['id']} in live view ({temp_file.stat().st_size} bytes)")

        except Exception as e:
            print(f"  Error downloading/placing bucket {job_info['bucket']['id']}: {e}")

# Other operators like stopping render and packing scene are defined below
class DISTRIB_OT_stop_render(Operator):
    """Stop distributed rendering"""
    bl_idname = "distrib.stop_render"
    bl_label = "Stop Distributed Render"
    bl_description = "Stop the current distributed render"
    bl_options = {'REGISTER'}

    def execute(self, context):
        context.scene.distributed_render_abort = True
        context.scene.distributed_render_status = "Aborting..."
        self.report({'INFO'}, "Aborting distributed render")
        return {'FINISHED'}

# Other operators like packing and previewing buckets are defined below
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

# The preview buckets operator is defined in assembly_preview.py since it shares code with the assembly operator
class DISTRIB_OT_preview_buckets(Operator):
    """Preview bucket layout"""
    bl_idname = "distrib.preview_buckets"
    bl_label = "Preview Buckets"
    bl_description = "Preview the current bucket layout"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        render = scene.render
        res_x = int(render.resolution_x * render.resolution_percentage / 100)
        res_y = int(render.resolution_y * render.resolution_percentage / 100)
        target = scene.distributed_render_bucket_count
        cols, rows = calc_bucket_grid(target, res_x, res_y)
        total = cols * rows

        print(f"=== Bucket Preview ===")
        print(f"Grid: {cols} x {rows} = {total} buckets (target: {target})")
        print(f"Tile size: ~{res_x // cols}x{res_y // rows}px")

        available = check_available_containers(context.scene)
        print(f"Available containers: {len(available)} on ports {available}")

        if len(available) > total:
            print("WARNING: More containers than buckets!")

        if scene.render.use_border:
            print(f"Render Region active: ({scene.render.border_min_x:.2f},{scene.render.border_min_y:.2f}) to ({scene.render.border_max_x:.2f},{scene.render.border_max_y:.2f})")

        self.report({'INFO'}, f"Preview: {cols}x{rows} = {total} buckets - check console")
        return {'FINISHED'}


class DISTRIB_OT_save_final(Operator):
    """Save the final assembled render to disk"""
    bl_idname = "distrib.save_final"
    bl_label = "Save Final Image"
    bl_description = "Save the assembled render result to disk (EXR or PNG)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        import tempfile

        live_img_name = "DistributedRender_Live"
        if live_img_name not in bpy.data.images:
            self.report({'ERROR'}, "No rendered image found. Run a distributed render first.")
            return {'CANCELLED'}

        img = bpy.data.images[live_img_name]

        # Determine output path
        render = context.scene.render
        output_dir = bpy.path.abspath(render.filepath)
        if not output_dir or output_dir == "":
            output_dir = bpy.path.abspath("//")
        if not output_dir:
            output_dir = str(Path(tempfile.gettempdir()) / "distributed_render")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save as EXR (32-bit) for quality
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_file = output_path / f"distributed_render_{timestamp}.exr"

        # Set image settings and save
        img.filepath_raw = str(final_file)
        img.file_format = 'OPEN_EXR'
        img.save()

        print(f"Saved final render: {final_file}")
        self.report({'INFO'}, f"Saved: {final_file.name}")
        return {'FINISHED'}


# === UTILITY FUNCTIONS ===

def pack_current_scene():
    """Pack and save current scene to a temp file, return the path"""
    import tempfile

    # Pack resources
    try:
        bpy.ops.file.pack_all()
        print("Packed external resources")
    except Exception as e:
        print(f"Warning: Pack failed: {e}")

    # Save to temp file
    temp_dir = Path(tempfile.gettempdir()) / "distributed_render"
    temp_dir.mkdir(exist_ok=True)
    blend_filename = "current_scene.blend"
    blend_path = temp_dir / blend_filename

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), copy=True)

    if not blend_path.exists():
        raise RuntimeError(f"Failed to save: {blend_path}")

    print(f"Saved: {blend_path} ({blend_path.stat().st_size} bytes)")
    return str(blend_path), blend_filename

# Check available Docker containers by pinging their health endpoints
def check_available_containers(scene=None):
    """Check which Docker containers are available"""
    count = 4
    if scene and hasattr(scene, 'distributed_render_containers'):
        count = scene.distributed_render_containers
    ports = list(range(8080, 8080 + count))
    working_containers = []

    for port in ports:
        try:
            response = requests.get(f"http://localhost:{port}/health", timeout=2)
            if response.status_code == 200:
                working_containers.append(port)
        except:
            pass

    return working_containers

# Upload .blend file to container via HTTP
def upload_blend_to_container(port, blend_path, blend_filename):
    """Upload .blend file to a container via HTTP"""
    try:
        with open(blend_path, 'rb') as f:
            files = {'file': (blend_filename, f, 'application/octet-stream')}
            response = requests.post(
                f"http://localhost:{port}/upload",
                files=files,
                timeout=60
            )
        return response.status_code == 200
    except Exception as e:
        print(f"Upload to port {port} failed: {e}")
        return False

# Cleanup function to tell container to delete all files in workspace
def cleanup_container(port):
    """Tell container to delete all workspace files"""
    try:
        requests.delete(f"http://localhost:{port}/cleanup/all", timeout=5)
    except:
        pass

# Create render buckets based on scene settings, sorted by distance from start point
def calc_bucket_grid(target_buckets, res_x, res_y):
    """Calculate optimal cols x rows for near-square tiles based on resolution aspect ratio"""
    import math
    aspect = res_x / res_y if res_y > 0 else 1.0

    # cols/rows such that cols*rows ~ target and (res_x/cols) ~ (res_y/rows)
    # cols = sqrt(target * aspect), rows = target / cols
    cols = max(1, round(math.sqrt(target_buckets * aspect)))
    rows = max(1, round(target_buckets / cols))

    # Ensure we have at least target_buckets (round up if needed)
    if cols * rows < target_buckets:
        if cols <= rows:
            cols += 1
        else:
            rows += 1

    return cols, rows


def create_render_buckets(context):
    """Create render buckets with near-square tiles, sorted center-out from start point"""
    scene = context.scene
    target_buckets = scene.distributed_render_bucket_count
    start_x = scene.distributed_render_start_x
    start_y = scene.distributed_render_start_y

    # Get resolution for aspect ratio calculation
    render = scene.render
    res_x = int(render.resolution_x * render.resolution_percentage / 100)
    res_y = int(render.resolution_y * render.resolution_percentage / 100)

    cols, rows = calc_bucket_grid(target_buckets, res_x, res_y)
    print(f"Bucket grid: {cols}x{rows} = {cols*rows} buckets (target: {target_buckets}, res: {res_x}x{res_y})")

    # Respect Blender's render region if active
    region_min_x = 0.0
    region_min_y = 0.0
    region_max_x = 1.0
    region_max_y = 1.0

    if render.use_border:
        region_min_x = render.border_min_x
        region_min_y = render.border_min_y
        region_max_x = render.border_max_x
        region_max_y = render.border_max_y

    buckets = []
    bucket_id = 0

    for y in range(rows):
        for x in range(cols):
            # Pixel-exact boundaries using integer division (no gaps, no overlap)
            px_start = (x * res_x) // cols
            px_end = ((x + 1) * res_x) // cols
            py_start = (y * res_y) // rows
            py_end = ((y + 1) * res_y) // rows

            # Convert to normalized floats for Blender border settings
            x_start_full = px_start / res_x
            y_start_full = py_start / res_y
            x_end_full = px_end / res_x
            y_end_full = py_end / res_y

            # Skip buckets outside render region
            if (x_end_full <= region_min_x or x_start_full >= region_max_x or
                y_end_full <= region_min_y or y_start_full >= region_max_y):
                continue

            # Clamp to render region
            bx_start = max(x_start_full, region_min_x)
            by_start = max(y_start_full, region_min_y)
            bx_end = min(x_end_full, region_max_x)
            by_end = min(y_end_full, region_max_y)

            bucket = {
                'id': bucket_id,
                'x': x,
                'y': y,
                'x_start': bx_start,
                'y_start': by_start,
                'x_end': bx_end,
                'y_end': by_end,
                'px_start': px_start,
                'py_start': py_start,
                'px_end': px_end,
                'py_end': py_end,
            }
            buckets.append(bucket)
            bucket_id += 1

    # Sort by distance from start point (center-out by default)
    def distance_from_start(bucket):
        cx = (bucket['x_start'] + bucket['x_end']) / 2
        cy = (bucket['y_start'] + bucket['y_end']) / 2
        return (cx - start_x) ** 2 + (cy - start_y) ** 2

    buckets.sort(key=distance_from_start)

    # Re-assign IDs after sorting
    for i, bucket in enumerate(buckets):
        bucket['id'] = i

    return buckets

# Enhanced versions of render functions with better error handling and debug output
def start_bucket_render(container_port, bucket, blend_filename, scene, active_jobs):
    """Start rendering a bucket on a container"""
    try:
        render = scene.render
        engine = render.engine

        # Get samples from Cycles settings if using Cycles
        samples = 128 # Default fallback
        if engine == 'CYCLES' and hasattr(scene, 'cycles'):
            samples = scene.cycles.samples

        # Get device from Cycles preferences
        device = 'CPU'
        if engine == 'CYCLES' and hasattr(scene, 'cycles'):
            device = scene.cycles.device

        # Get camera name, default to scene camera if not set
        camera_name = scene.distributed_render_camera
        if not camera_name or camera_name == 'NONE':
            camera_name = scene.camera.name if scene.camera else None

        render_data = {
            'bucket_id': bucket['id'],
            'blend_file': blend_filename,
            'frame': scene.frame_current,
            'output_path': f'bucket_{bucket["id"]:04d}.png',
            'camera_name': camera_name,
            'render_settings': {
                'engine': engine,
                'resolution_x': render.resolution_x,
                'resolution_y': render.resolution_y,
                'resolution_percentage': render.resolution_percentage,
                'samples': samples,
                'device': device,
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
    DISTRIB_OT_save_final,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)