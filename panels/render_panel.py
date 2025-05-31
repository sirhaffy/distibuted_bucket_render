"""
UI Panel for Distributed Render addon - UPDATED VERSION with Assembly
"""

import bpy
from bpy.types import Panel

class DISTRIB_PT_main_panel(Panel):
    """Main panel for distributed rendering"""
    bl_label = "Distributed Render"
    bl_idname = "DISTRIB_PT_main_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw_header(self, context):
        # Check if property exists before using it
        if hasattr(context.scene, "distributed_render_enabled"):
            self.layout.prop(context.scene, "distributed_render_enabled", text="")

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Check if properties exist before using them
        if not hasattr(scene, "distributed_render_enabled"):
            layout.label(text="ERROR: Scene properties not loaded!", icon='ERROR')
            layout.label(text="Try reloading the addon")
            return

        layout.enabled = scene.distributed_render_enabled

        # Render Settings
        box = layout.box()
        box.label(text="Render Settings", icon='SETTINGS')
        col = box.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "distributed_render_res_x", text="X")
        row.prop(scene, "distributed_render_res_y", text="Y")
        col.prop(scene, "distributed_render_percentage", text="Scale %")
        box.prop(scene, "distributed_render_engine", text="Engine")
        if scene.distributed_render_engine == 'CYCLES':
            box.prop(scene, "distributed_render_device", text="Device")
            box.prop(scene, "distributed_render_samples", text="Samples")

        # Bucket Configuration
        box = layout.box()
        box.label(text="Bucket Configuration", icon='GRID')
        col = box.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "distributed_render_buckets_x", text="X")
        row.prop(scene, "distributed_render_buckets_y", text="Y")
        total_buckets = scene.distributed_render_buckets_x * scene.distributed_render_buckets_y
        col.label(text=f"Total Buckets: {total_buckets}")

        # Container Configuration
        box = layout.box()
        box.label(text="Container Configuration", icon='NETWORK_DRIVE')
        box.prop(scene, "distributed_render_containers", text="Containers")
        if scene.distributed_render_containers > total_buckets:
            box.label(text="⚠ More containers than buckets", icon='ERROR')

        # Status
        box = layout.box()
        box.label(text="Status", icon='SEQUENCE')
        box.label(text=scene.distributed_render_status)

        # Show progress bar if rendering
        if "%" in scene.distributed_render_status or scene.distributed_render_progress > 0:
            progress_row = box.row()
            progress_row.prop(scene, "distributed_render_progress", text="Progress", slider=True)

        # Action Buttons
        col = layout.column(align=True)
        start_row = col.row(align=True)
        start_row.scale_y = 1.5

        if scene.distributed_render_status in ['Rendering', 'Initializing', 'Packing']:
            start_row.operator("distrib.stop_render", text="Stop Render", icon='CANCEL')
        else:
            start_row.operator("distrib.start_render", text="Start Distributed Render", icon='RENDER_STILL')

        # Secondary buttons
        row = col.row(align=True)
        row.operator("distrib.pack_scene", text="Pack Resources", icon='PACKAGE')
        row.operator("distrib.preview_buckets", text="Preview Buckets", icon='VIEWZOOM')
        row.operator("distrib.debug_containers", text="Debug", icon='CONSOLE')

        # Assembly Section
        box = layout.box()
        box.label(text="Assembly", icon='IMAGE_DATA')

        assembly_col = box.column(align=True)

        # Preview assembly button
        preview_row = assembly_col.row(align=True)
        preview_row.operator("distrib.preview_assembly", text="Preview Assembly", icon='VIEWZOOM')

        # Assemble final image button
        assemble_row = assembly_col.row(align=True)
        assemble_row.scale_y = 1.3
        assemble_row.operator("distrib.assemble_buckets", text="Assemble Final Image", icon='IMAGE_DATA')

        # Quick info about bucket files
        try:
            from pathlib import Path
            addon_dir = Path(__file__).parent.parent
            output_dir = addon_dir / "bucket_resources" / "bucket_output"

            if output_dir.exists():
                bucket_files = list(output_dir.glob("bucket_*.png"))
                info_text = f"{len(bucket_files)}/{total_buckets} buckets available"
                box.label(text=info_text, icon='INFO')
            else:
                box.label(text="No bucket output directory", icon='ERROR')
        except Exception:
            pass  # Ignore errors in info display


# Registration
classes = [
    DISTRIB_PT_main_panel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)