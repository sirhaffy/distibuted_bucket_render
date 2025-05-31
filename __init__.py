"""
Distributed Render Addon for Blender
CLEAN VERSION - Only registration and properties
"""

bl_info = {
    "name": "Distributed Render",
    "author": "Your Name",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "description": "Distribute rendering across Docker containers",
    "category": "Render",
    "location": "3D Viewport > N-panel > Render",
    "doc_url": "",
    "tracker_url": "",
}

import bpy
from bpy.props import IntProperty, BoolProperty, StringProperty, EnumProperty, FloatProperty

# Import modules
from . import addon_preferences
from . import panels
from . import operators

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

    # Custom render settings (separate from Blender's)
    bpy.types.Scene.distributed_render_res_x = IntProperty(
        name="Resolution X",
        description="Render resolution X (separate from Blender's settings)",
        default=1920,
        min=64,
        max=8192
    )

    bpy.types.Scene.distributed_render_res_y = IntProperty(
        name="Resolution Y",
        description="Render resolution Y (separate from Blender's settings)",
        default=1080,
        min=64,
        max=8192
    )

    bpy.types.Scene.distributed_render_percentage = IntProperty(
        name="Resolution Scale",
        description="Resolution percentage",
        default=100,
        min=1,
        max=1000
    )

    bpy.types.Scene.distributed_render_engine = EnumProperty(
        name="Render Engine",
        description="Rendering engine to use",
        items=[
            ('CYCLES', 'Cycles', 'Cycles rendering engine'),
            ('BLENDER_EEVEE', 'Eevee', 'Eevee rendering engine'),
        ],
        default='CYCLES'
    )

    bpy.types.Scene.distributed_render_device = EnumProperty(
        name="Device",
        description="Rendering device",
        items=[
            ('CPU', 'CPU', 'Use CPU for rendering'),
            ('GPU', 'GPU', 'Use GPU for rendering (if available)'),
        ],
        default='CPU'
    )

    bpy.types.Scene.distributed_render_samples = IntProperty(
        name="Samples",
        description="Number of samples for Cycles rendering",
        default=128,
        min=1,
        max=10000
    )

    # Bucket settings
    bpy.types.Scene.distributed_render_buckets_x = IntProperty(
        name="Buckets X",
        description="Number of horizontal buckets",
        default=2,
        min=1,
        max=16
    )

    bpy.types.Scene.distributed_render_buckets_y = IntProperty(
        name="Buckets Y",
        description="Number of vertical buckets",
        default=2,
        min=1,
        max=16
    )

    bpy.types.Scene.distributed_render_containers = IntProperty(
        name="Container Count",
        description="Number of Docker containers to use",
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

def unregister_scene_properties():
    """Remove all scene properties"""

    props_to_remove = [
        'distributed_render_enabled',
        'distributed_render_res_x',
        'distributed_render_res_y',
        'distributed_render_percentage',
        'distributed_render_engine',
        'distributed_render_device',
        'distributed_render_samples',
        'distributed_render_buckets_x',
        'distributed_render_buckets_y',
        'distributed_render_containers',
        'distributed_render_status',
        'distributed_render_docker_status',
        'distributed_render_progress',
    ]

    for prop in props_to_remove:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

if __name__ == "__main__":
    register()