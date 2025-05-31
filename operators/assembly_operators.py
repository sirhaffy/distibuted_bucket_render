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
            buckets_x = scene.distributed_render_buckets_x
            buckets_y = scene.distributed_render_buckets_y
            total_buckets = buckets_x * buckets_y

            # Get render resolution
            width = scene.distributed_render_res_x
            height = scene.distributed_render_res_y
            percentage = scene.distributed_render_percentage

            final_width = int(width * percentage / 100)
            final_height = int(height * percentage / 100)

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
            scene = context.scene
            buckets_x = scene.distributed_render_buckets_x
            buckets_y = scene.distributed_render_buckets_y
            total_buckets = buckets_x * buckets_y

            print("=== CREATING PREVIEW ASSEMBLY ===")

            # Find bucket files
            addon_dir = Path(__file__).parent.parent
            workspace_dir = addon_dir / "bucket_resources"
            output_dir = workspace_dir / "bucket_output"

            if not output_dir.exists():
                self.report({'ERROR'}, f"Output directory not found: {output_dir}")
                return {'CANCELLED'}

            print(f"Looking for buckets in: {output_dir}")

            found_count = 0
            bucket_files = {}

            # Check which buckets exist
            for bucket_id in range(total_buckets):
                bucket_file = output_dir / f"bucket_{bucket_id:04d}.png"
                if bucket_file.exists():
                    bucket_files[bucket_id] = bucket_file
                    found_count += 1
                    print(f"✓ Found bucket {bucket_id}")
                else:
                    print(f"✗ Missing bucket {bucket_id}")

            if not bucket_files:
                self.report({'ERROR'}, "No bucket files found")
                return {'CANCELLED'}

            print(f"Found {found_count}/{total_buckets} bucket files")

            # Use PreviewEngine to create quick preview
            preview_engine = PreviewEngine(context)
            success = preview_engine.create_preview(
                bucket_files, buckets_x, buckets_y
            )

            if success:
                self.report({'INFO'}, f"Preview created: {found_count}/{total_buckets} buckets assembled")
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "Preview assembly failed")
                return {'CANCELLED'}

        except Exception as e:
            print(f"Preview error: {e}")
            import traceback
            traceback.print_exc()
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


# Registration
classes = [
    DISTRIB_OT_assemble_buckets,
    DISTRIB_OT_preview_assembly,
    DISTRIB_OT_view_buckets_in_editor,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)