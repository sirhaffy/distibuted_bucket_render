"""
Distributed Render Addon for Blender
CLEAN VERSION - Only registration and properties
"""

bl_info = {
    "name": "Distributed Render",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "description": "Distribute rendering across Docker containers",
    "category": "Render",
    "location": "Render Properties > Distributed Render",
    "doc_url": "",
    "tracker_url": "",
}

import bpy
from bpy.props import IntProperty, BoolProperty, StringProperty, EnumProperty, FloatProperty

# Import modules
from . import addon_preferences
from . import panels
from . import operators

# Utility function to get camera items for the EnumProperty
def get_camera_items(self, context):
    """Dynamic enum callback to list all cameras in the scene"""
    items = []
    for obj in context.scene.objects:
        if obj.type == 'CAMERA':
            items.append((obj.name, obj.name, f"Use camera: {obj.name}"))
    if not items:
        items.append(('NONE', 'No cameras', 'No cameras found in scene'))
    return items

def register():
    print("Registering Distributed Render Addon...")

    # Register preferences first
    addon_preferences.register()

    # Register operators
    operators.register()

    # Register panels
    panels.register()

    # Add scene properties
    register_scene_properties()

    print("✓ Distributed Render Addon registered successfully!")

def unregister():
    print("Unregistering Distributed Render Addon...")

    # Remove scene properties first
    unregister_scene_properties()

    # Unregister in reverse order
    panels.unregister()
    operators.unregister()
    addon_preferences.unregister()

    print("✓ Distributed Render Addon unregistered successfully!")

def register_scene_properties():
    """Register all scene properties"""

    # Main toggle
    bpy.types.Scene.distributed_render_enabled = BoolProperty(
        name="Enable Distributed Render",
        description="Enable distributed rendering across Docker containers",
        default=False
    )

    # Bucket settings - total number of buckets, grid auto-calculated for square tiles
    bpy.types.Scene.distributed_render_bucket_count = IntProperty(
        name="Buckets",
        description="Total number of buckets (grid auto-calculated for square tiles based on aspect ratio)",
        default=16,
        min=1,
        max=1024
    )

    # Render start point (normalized 0-1)
    bpy.types.Scene.distributed_render_start_x = FloatProperty(
        name="Start X",
        description="X position to start rendering from (0=left, 1=right)",
        default=0.5,
        min=0.0,
        max=1.0
    )

    bpy.types.Scene.distributed_render_start_y = FloatProperty(
        name="Start Y",
        description="Y position to start rendering from (0=bottom, 1=top)",
        default=0.5,
        min=0.0,
        max=1.0
    )

    # Container settings
    bpy.types.Scene.distributed_render_containers = IntProperty(
        name="Container Count",
        description="Number of render containers to scan (ports 8080 to 8080+N)",
        default=4,
        min=1,
        max=32
    )

    # Status properties
    bpy.types.Scene.distributed_render_status = StringProperty(
        name="Render Status",
        description="Current status of distributed rendering",
        default="Ready"
    )

    bpy.types.Scene.distributed_render_docker_status = StringProperty(
        name="Docker Status",
        description="Status of Docker containers",
        default="Not checked"
    )

    bpy.types.Scene.distributed_render_progress = FloatProperty(
        name="Render Progress",
        description="Current render progress percentage",
        default=0.0,
        min=0.0,
        max=100.0
    )

    # Camera selector
    bpy.types.Scene.distributed_render_camera = EnumProperty(
        name="Render Camera",
        description="Camera to use for distributed rendering",
        items=get_camera_items
    )

    # Abort flag
    bpy.types.Scene.distributed_render_abort = BoolProperty(
        name="Abort Render",
        default=False
    )

def unregister_scene_properties():
    """Remove all scene properties"""

    props_to_remove = [
        'distributed_render_enabled',
        'distributed_render_bucket_count',
        'distributed_render_buckets_x',
        'distributed_render_buckets_y',
        'distributed_render_start_x',
        'distributed_render_start_y',
        'distributed_render_containers',
        'distributed_render_camera',
        'distributed_render_status',
        'distributed_render_docker_status',
        'distributed_render_progress',
        'distributed_render_abort',
    ]

    for prop in props_to_remove:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

if __name__ == "__main__":
    register()