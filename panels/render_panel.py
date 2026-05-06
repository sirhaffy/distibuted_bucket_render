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

        # Show current Blender render settings (read-only info)
        render = scene.render
        box = layout.box()
        box.label(text="Scene Render Settings", icon='SETTINGS')
        final_w = int(render.resolution_x * render.resolution_percentage / 100)
        final_h = int(render.resolution_y * render.resolution_percentage / 100)
        box.label(text=f"{final_w} x {final_h} ({render.engine})")
        box.prop(scene, "distributed_render_camera", text="Camera", icon='CAMERA_DATA')

        # Bucket Configuration
        box = layout.box()
        box.label(text="Bucket Configuration", icon='GRID')
        from .render_panel_utils import calc_bucket_grid
        render = scene.render
        res_x = int(render.resolution_x * render.resolution_percentage / 100)
        res_y = int(render.resolution_y * render.resolution_percentage / 100)
        cols, rows = calc_bucket_grid(scene.distributed_render_bucket_count, res_x, res_y)
        total_buckets = cols * rows
        tile_w = res_x // cols
        tile_h = res_y // rows
        box.prop(scene, "distributed_render_bucket_count", text=f"Buckets ({cols}x{rows} = {total_buckets}, ~{tile_w}x{tile_h}px)")

        # Start point
        col = box.column(align=True)
        col.label(text="Render Start Point:")
        row = col.row(align=True)
        row.prop(scene, "distributed_render_start_x", text="X")
        row.prop(scene, "distributed_render_start_y", text="Y")

        # Render Nodes (not working yet)
        box = layout.box()
        box.label(text="Render Nodes", icon='NETWORK_DRIVE')
        box.prop(scene, "distributed_render_containers", text="Count")
        box.label(text=f"Scans ports 8080-{8079 + scene.distributed_render_containers}")
        box.operator("distrib.debug_containers", text="Check Render Nodes", icon='FILE_REFRESH')

        # Status
        box = layout.box()
        box.label(text="Status", icon='SEQUENCE')
        box.label(text=scene.distributed_render_status)

        # Show progress bar if rendering
        if scene.distributed_render_progress > 0:
            progress_row = box.row()
            progress_row.prop(scene, "distributed_render_progress", text="Progress", slider=True)

        # Action Buttons
        col = layout.column(align=True)
        start_row = col.row(align=True)
        start_row.scale_y = 1.5

        is_rendering = "Rendering" in scene.distributed_render_status or "Initializing" in scene.distributed_render_status or "Uploading" in scene.distributed_render_status or "Packing" in scene.distributed_render_status
        if is_rendering:
            start_row.operator("distrib.stop_render", text="Stop Render", icon='CANCEL')
        else:
            start_row.operator("distrib.start_render", text="Start Distributed Render", icon='RENDER_STILL')

        # Secondary buttons
        box = layout.box()
        box.label(text="Tools", icon='TOOL_SETTINGS')
        tool_col = box.column(align=True)

        tool_col.operator("distrib.pack_scene", text="Pack Resources", icon='PACKAGE')
        tool_col.label(text="Saves .blend + assets to bucket_resources/")

        tool_col.separator()
        tool_col.operator("distrib.preview_buckets", text="Preview Buckets", icon='VIEWZOOM')
        tool_col.label(text="Prints bucket grid layout to console")

        tool_col.separator()
        tool_col.operator("distrib.debug_containers", text="Debug", icon='CONSOLE')
        tool_col.label(text="Checks container health on ports 8080-8083")

        # Output Section
        box = layout.box()
        box.label(text="Output", icon='IMAGE_DATA')
        output_col = box.column(align=True)

        save_row = output_col.row(align=True)
        save_row.scale_y = 1.3
        save_row.operator("distrib.save_final", text="Save Final Image", icon='FILE_IMAGE')
        output_col.label(text="Saves assembled render to disk (EXR)")

        output_col.separator()
        output_col.operator("distrib.preview_assembly", text="Show Live Preview", icon='VIEWZOOM')

        output_col.separator()
        raw_row = output_col.row(align=True)
        raw_row.scale_y = 1.3
        raw_row.operator("distrib.download_raw", text="Download RAW to Compositor", icon='NODE_COMPOSITING')
        output_col.label(text="Downloads EXR passes into Compositor nodes")


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