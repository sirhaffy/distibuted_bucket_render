"""
Assembly operators - Main UI interface
Handles user interaction and delegates to specialized classes
"""

import bpy
from bpy.types import Operator
from pathlib import Path
import time

from .assembly_engine import AssemblyEngine
from .assembly_preview import PreviewEngine


class DISTRIB_OT_assemble_buckets(Operator):
    """Assemble completed bucket renders into final EXR image"""
    bl_idname = "distrib.assemble_buckets"
    bl_label = "Assemble Buckets"
    bl_description = "Assemble all completed bucket renders into final EXR image with all View Layers"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            scene = context.scene

            print("=== ASSEMBLING BUCKETS TO EXR ===")

            # Get bucket settings
            from .render_operator import calc_bucket_grid
            render = scene.render
            final_width = int(render.resolution_x * render.resolution_percentage / 100)
            final_height = int(render.resolution_y * render.resolution_percentage / 100)
            target = scene.distributed_render_bucket_count
            buckets_x, buckets_y = calc_bucket_grid(target, final_width, final_height)
            total_buckets = buckets_x * buckets_y

            print(f"Grid: {buckets_x}x{buckets_y} = {total_buckets} buckets")
            print(f"Final resolution: {final_width}x{final_height}")

            # Find bucket files
            addon_dir = Path(__file__).parent.parent
            workspace_dir = addon_dir / "bucket_resources"
            output_dir = workspace_dir / "bucket_output"

            if not output_dir.exists():
                self.report({'ERROR'}, f"Output directory not found: {output_dir}")
                return {'CANCELLED'}

            print(f"Looking for buckets in: {output_dir}")

            # Find bucket files
            bucket_files = {}
            for bucket_id in range(total_buckets):
                bucket_file = output_dir / f"bucket_{bucket_id:04d}.png"
                if bucket_file.exists():
                    bucket_files[bucket_id] = bucket_file
                    print(f"✓ Found bucket {bucket_id}: {bucket_file.name}")
                else:
                    print(f"✗ Missing bucket {bucket_id}: {bucket_file.name}")

            if not bucket_files:
                self.report({'ERROR'}, "No bucket files found")
                return {'CANCELLED'}

            print(f"Found {len(bucket_files)}/{total_buckets} bucket files")

            # Use AssemblyEngine to create final EXR
            assembly_engine = AssemblyEngine(context)
            success = assembly_engine.assemble_to_exr(
                bucket_files, buckets_x, buckets_y, final_width, final_height
            )

            if success:
                assembled_count = len(bucket_files)
                scene.distributed_render_status = f"Assembled! ({assembled_count}/{total_buckets} buckets)"
                self.report({'INFO'}, f"Assembled {assembled_count} buckets to EXR")
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "Assembly failed")
                return {'CANCELLED'}

        except Exception as e:
            print(f"Assembly error: {e}")
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Assembly failed: {str(e)}")
            return {'CANCELLED'}


class DISTRIB_OT_preview_assembly(Operator):
    """Preview bucket assembly layout"""
    bl_idname = "distrib.preview_assembly"
    bl_label = "Preview Assembly"
    bl_description = "Create a quick preview of the assembled buckets and show in Image Editor"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            # The live preview image IS the assembled result
            live_img_name = "DistributedRender_Live"
            if live_img_name not in bpy.data.images:
                self.report({'ERROR'}, "No rendered image found. Run a distributed render first.")
                return {'CANCELLED'}

            img = bpy.data.images[live_img_name]

            # Show in Image Editor
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

            if not shown:
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.type = 'IMAGE_EDITOR'
                        for space in area.spaces:
                            if space.type == 'IMAGE_EDITOR':
                                space.image = img
                                break
                        shown = True
                        break

            self.report({'INFO'}, f"Showing assembled render: {img.size[0]}x{img.size[1]}")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Preview failed: {str(e)}")
            return {'CANCELLED'}


class DISTRIB_OT_view_buckets_in_editor(Operator):
    """View bucket images in Blender's Image Editor"""
    bl_idname = "distrib.view_buckets_in_editor"
    bl_label = "View Buckets"
    bl_description = "Load and view bucket images in Blender's Image Editor"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            # Find bucket files
            addon_dir = Path(__file__).parent.parent
            output_dir = addon_dir / "bucket_resources" / "bucket_output"

            if not output_dir.exists():
                self.report({'ERROR'}, "No bucket output directory found")
                return {'CANCELLED'}

            bucket_files = list(output_dir.glob("bucket_*.png"))

            if not bucket_files:
                self.report({'ERROR'}, "No bucket files found")
                return {'CANCELLED'}

            # Load first bucket in Image Editor
            first_bucket = bucket_files[0]

            # Load image
            if first_bucket.name in bpy.data.images:
                img = bpy.data.images[first_bucket.name]
                img.reload()
            else:
                img = bpy.data.images.load(str(first_bucket))

            # Show in Image Editor
            for area in context.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'IMAGE_EDITOR':
                            space.image = img
                            break
                    break

            self.report({'INFO'}, f"Loaded {len(bucket_files)} bucket files - showing first in Image Editor")

            return {'FINISHED'}

        except Exception as e:
            print(f"View buckets error: {e}")
            self.report({'ERROR'}, f"Failed to view buckets: {str(e)}")
            return {'CANCELLED'}


class DISTRIB_OT_download_raw(Operator):
    """Download individual pass EXR files from containers, stitch each pass, load into Compositor"""
    bl_idname = "distrib.download_raw"
    bl_label = "Download RAW to Compositor"
    bl_description = "Download and stitch all render passes into full-res images for Compositor"
    bl_options = {'REGISTER'}

    def execute(self, context):
        import requests
        import tempfile
        import numpy as np

        from .render_operator import LAST_RENDER_JOBS

        if not LAST_RENDER_JOBS:
            self.report({'ERROR'}, "No completed render jobs found. Run a distributed render first.")
            return {'CANCELLED'}

        scene = context.scene
        render = scene.render
        res_x = int(render.resolution_x * render.resolution_percentage / 100)
        res_y = int(render.resolution_y * render.resolution_percentage / 100)

        temp_dir = Path(tempfile.gettempdir()) / "distributed_render" / "passes"
        temp_dir.mkdir(parents=True, exist_ok=True)

        print(f"=== DOWNLOADING AND STITCHING RENDER PASSES ===")
        print(f"Final resolution: {res_x}x{res_y}")
        print(f"Jobs: {len(LAST_RENDER_JOBS)}")

        # Step 1: Query first container to find available passes
        first_job = LAST_RENDER_JOBS[0]
        available_passes = []
        try:
            resp = requests.get(
                f"http://localhost:{first_job['port']}/render/pass/{first_job['job_id']}",
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                available_passes = [p['name'] for p in data.get('passes', [])]
        except Exception as e:
            print(f"  Could not query passes: {e}")

        # Fallback: try combined at minimum
        if not available_passes:
            available_passes = ['combined']
        print(f"Available passes: {available_passes}")

        # Step 2: Download and stitch each pass
        stitched_images = {}

        for pass_name in available_passes:
            print(f"\n--- Stitching pass: {pass_name} ---")

            # Determine channels (depth is 1 channel, rest is 3 or 4)
            is_depth = (pass_name == 'depth')
            channels = 1 if is_depth else 4

            full_pixels = np.zeros((res_y, res_x, channels), dtype=np.float32)
            buckets_placed = 0

            for job_info in LAST_RENDER_JOBS:
                port = job_info['port']
                job_id = job_info['job_id']
                bucket = job_info['bucket']

                try:
                    response = requests.get(
                        f"http://localhost:{port}/render/pass/{job_id}/{pass_name}",
                        timeout=60
                    )
                    if response.status_code != 200:
                        continue

                    # Save to temp file
                    pass_file = temp_dir / f"{pass_name}_bucket_{bucket['id']:04d}.exr"
                    pass_file.write_bytes(response.content)

                    # Load into Blender and read pixels
                    temp_img_name = f"_pass_temp_{pass_name}_{bucket['id']}"
                    if temp_img_name in bpy.data.images:
                        bpy.data.images.remove(bpy.data.images[temp_img_name])

                    bucket_img = bpy.data.images.load(str(pass_file))
                    bucket_img.name = temp_img_name

                    b_width = bucket_img.size[0]
                    b_height = bucket_img.size[1]

                    if b_width == 0 or b_height == 0:
                        bpy.data.images.remove(bucket_img)
                        continue

                    # Read pixels - Blender always gives RGBA (4 channels)
                    raw_pixels = np.array(bucket_img.pixels[:], dtype=np.float32)
                    raw_pixels = raw_pixels.reshape(b_height, b_width, 4)

                    if is_depth:
                        # Depth: take R channel only
                        bucket_data = raw_pixels[:, :, 0:1]
                    else:
                        bucket_data = raw_pixels

                    # Pixel-exact placement
                    offset_x = bucket.get('px_start', round(bucket['x_start'] * res_x))
                    offset_y = bucket.get('py_start', round(bucket['y_start'] * res_y))

                    copy_w = min(b_width, res_x - offset_x)
                    copy_h = min(b_height, res_y - offset_y)

                    if copy_w > 0 and copy_h > 0:
                        full_pixels[offset_y:offset_y + copy_h, offset_x:offset_x + copy_w] = \
                            bucket_data[:copy_h, :copy_w]
                        buckets_placed += 1

                    bpy.data.images.remove(bucket_img)

                except Exception as e:
                    print(f"    Bucket {bucket['id']} failed: {e}")

            print(f"  Placed {buckets_placed}/{len(LAST_RENDER_JOBS)} buckets")

            if buckets_placed == 0:
                continue

            # Create Blender image from stitched data
            img_name = f"DR_{pass_name}"
            if img_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[img_name])

            img = bpy.data.images.new(img_name, res_x, res_y, alpha=(not is_depth), float_buffer=True)

            if is_depth:
                # Expand single channel to RGBA for Blender's pixel buffer
                rgba = np.zeros((res_y, res_x, 4), dtype=np.float32)
                rgba[:, :, 0] = full_pixels[:, :, 0]
                rgba[:, :, 1] = full_pixels[:, :, 0]
                rgba[:, :, 2] = full_pixels[:, :, 0]
                rgba[:, :, 3] = 1.0
                img.pixels[:] = rgba.flatten().tolist()
            else:
                img.pixels[:] = full_pixels.flatten().tolist()

            img.update()

            # Save to disk as EXR
            exr_path = temp_dir / f"stitched_{pass_name}.exr"
            img.filepath_raw = str(exr_path)
            img.file_format = 'OPEN_EXR'
            img.save()

            # Reload from file for proper tracking
            bpy.data.images.remove(img)
            img = bpy.data.images.load(str(exr_path))
            img.name = img_name
            img.colorspace_settings.name = 'Non-Color' if pass_name != 'combined' else 'Linear Rec.709'

            stitched_images[pass_name] = img
            print(f"  Created image: {img_name}")

        if not stitched_images:
            self.report({'ERROR'}, "Failed to stitch any passes")
            return {'CANCELLED'}

        # Step 3: Create compositor nodes
        scene.use_nodes = True
        tree = scene.node_tree

        # Find Render Layers node for positioning
        render_layers_node = None
        for node in tree.nodes:
            if node.type == 'R_LAYERS':
                render_layers_node = node
                break

        if render_layers_node:
            base_x = render_layers_node.location.x
            base_y = render_layers_node.location.y - 400
        else:
            base_x = -300
            base_y = 0

        # Remove old DR nodes if they exist
        old_nodes = [n for n in tree.nodes if n.name.startswith('DR_')]
        for n in old_nodes:
            tree.nodes.remove(n)

        # Create a frame to group our nodes
        frame = tree.nodes.new('NodeFrame')
        frame.name = "DR_Frame"
        frame.label = "Distributed Render"
        frame.use_custom_color = True
        frame.color = (0.15, 0.3, 0.15)

        # Map pass names to Render Layers output equivalents
        pass_output_names = {
            'combined': 'Image',
            'normal': 'Normal',
            'denoising_normal': 'Denoising Normal',
            'denoising_albedo': 'Denoising Albedo',
            'depth': 'Depth',
            'diffuse_color': 'DiffCol',
            'glossy_color': 'GlossCol',
        }

        created_nodes = {}
        node_y_offset = 0

        for pass_name, img in stitched_images.items():
            output_label = pass_output_names.get(pass_name, pass_name.title())

            img_node = tree.nodes.new('CompositorNodeImage')
            img_node.name = f"DR_{pass_name}"
            img_node.image = img
            img_node.label = f"DR: {output_label}"
            img_node.location = (base_x, base_y - node_y_offset)
            img_node.parent = frame
            img_node.use_custom_color = True
            img_node.color = (0.2, 0.4, 0.2)

            created_nodes[pass_name] = img_node
            node_y_offset += 200

        # Auto-connect to Denoise node if found and we have the right passes
        denoise_node = None
        for node in tree.nodes:
            if node.type == 'DENOISE':
                denoise_node = node
                break

        if denoise_node:
            if 'combined' in created_nodes:
                tree.links.new(created_nodes['combined'].outputs['Image'], denoise_node.inputs['Image'])
            if 'normal' in created_nodes:
                tree.links.new(created_nodes['normal'].outputs['Image'], denoise_node.inputs['Normal'])
            elif 'denoising_normal' in created_nodes:
                tree.links.new(created_nodes['denoising_normal'].outputs['Image'], denoise_node.inputs['Normal'])
            if 'denoising_albedo' in created_nodes:
                tree.links.new(created_nodes['denoising_albedo'].outputs['Image'], denoise_node.inputs['Albedo'])
            print("Auto-connected to Denoise node!")

        # Cleanup containers
        self._cleanup_containers(LAST_RENDER_JOBS)

        pass_list = ', '.join(stitched_images.keys())
        self.report({'INFO'}, f"Stitched passes [{pass_list}] added to Compositor")
        return {'FINISHED'}

    def _cleanup_containers(self, jobs):
        """Call cleanup on all containers that had jobs"""
        import requests
        ports_cleaned = set()
        for job_info in jobs:
            port = job_info['port']
            if port not in ports_cleaned:
                try:
                    requests.delete(f"http://localhost:{port}/cleanup/all", timeout=5)
                    ports_cleaned.add(port)
                except Exception:
                    pass


# Registration
classes = [
    DISTRIB_OT_assemble_buckets,
    DISTRIB_OT_preview_assembly,
    DISTRIB_OT_view_buckets_in_editor,
    DISTRIB_OT_download_raw,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)