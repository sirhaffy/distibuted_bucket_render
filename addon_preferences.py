"""
Addon preferences for Distributed Render
Handles user settings and configuration
"""

import bpy
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty
from bpy.types import AddonPreferences
import os


class DistributedRenderPreferences(AddonPreferences):
    """
    Preferences panel for the Distributed Render addon
    """
    bl_idname = __package__

    # Docker settings
    docker_executable: StringProperty(
        name="Docker Executable",
        description="Path to Docker executable",
        default="docker",
        subtype='FILE_PATH'
    )

    docker_image: StringProperty(
        name="Docker Image",
        description="Docker image to use for render nodes",
        default="blender-render:latest"
    )

    max_containers: IntProperty(
        name="Max Containers",
        description="Maximum number of Docker containers to run simultaneously",
        default=8,
        min=1,
        max=64
    )

    container_memory: StringProperty(
        name="Container Memory",
        description="Memory limit per container (e.g., '2g', '512m')",
        default="2g"
    )

    # Network settings
    base_port: IntProperty(
        name="Base Port",
        description="Base port for container communication",
        default=8080,
        min=1024,
        max=65535
    )

    # File paths
    temp_directory: StringProperty(
        name="Temp Directory",
        description="Directory for temporary render files",
        default="//bucket_resources/",
        subtype='DIR_PATH'
    )

    output_directory: StringProperty(
        name="Output Directory",
        description="Directory for final render output",
        default="//renders/",
        subtype='DIR_PATH'
    )

    # Rendering settings
    progressive_update_interval: IntProperty(
        name="Update Interval",
        description="Seconds between progressive render updates",
        default=5,
        min=1,
        max=60
    )

    # Debug settings
    debug_mode: BoolProperty(
        name="Debug Mode",
        description="Enable verbose logging and debug output",
        default=False
    )

    keep_temp_files: BoolProperty(
        name="Keep Temp Files",
        description="Keep temporary files after rendering (for debugging)",
        default=False
    )

    # Auto settings
    auto_pack_resources: BoolProperty(
        name="Auto Pack Resources",
        description="Automatically pack external resources before rendering",
        default=True
    )

    auto_optimize_buckets: BoolProperty(
        name="Auto Optimize Buckets",
        description="Automatically optimize bucket layout based on scene complexity",
        default=True
    )

    def draw(self, context):
        """
        Draw the preferences UI
        """
        layout = self.layout

        # Docker Settings
        box = layout.box()
        box.label(text="Docker Settings", icon='SETTINGS')
        box.prop(self, "docker_executable")
        box.prop(self, "docker_image")
        box.prop(self, "max_containers")
        box.prop(self, "container_memory")

        # Network Settings
        box = layout.box()
        box.label(text="Network Settings", icon='NETWORK_DRIVE')
        box.prop(self, "base_port")

        # File Paths
        box = layout.box()
        box.label(text="File Paths", icon='FILE_FOLDER')
        box.prop(self, "temp_directory")
        box.prop(self, "output_directory")

        # Rendering Settings
        box = layout.box()
        box.label(text="Rendering Settings", icon='RENDER_STILL')
        box.prop(self, "progressive_update_interval")
        box.prop(self, "auto_pack_resources")
        box.prop(self, "auto_optimize_buckets")

        # Debug Settings
        box = layout.box()
        box.label(text="Debug Settings", icon='CONSOLE')
        box.prop(self, "debug_mode")
        box.prop(self, "keep_temp_files")

        # Action buttons
        row = layout.row()
        row.operator("render.test_docker_connection", text="Test Docker Connection", icon='PLAY')
        row.operator("render.build_docker_image", text="Build Docker Image", icon='MOD_BUILD')


class RENDER_OT_test_docker_connection(bpy.types.Operator):
    """Test Docker connection and image availability"""
    bl_idname = "render.test_docker_connection"
    bl_label = "Test Docker Connection"
    bl_description = "Test if Docker is available and image exists"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        import subprocess
        try:
            # Test docker command
            result = subprocess.run([prefs.docker_executable, "--version"],
                                    capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                self.report({'INFO'}, f"Docker found: {result.stdout.strip()}")

                # Test if image exists
                result = subprocess.run([prefs.docker_executable, "images", prefs.docker_image],
                                        capture_output=True, text=True, timeout=10)

                if prefs.docker_image in result.stdout:
                    self.report({'INFO'}, f"Docker image '{prefs.docker_image}' found")
                else:
                    self.report({'WARNING'}, f"Docker image '{prefs.docker_image}' not found. Build it first.")

            else:
                self.report({'ERROR'}, f"Docker not found or not working: {result.stderr}")

        except subprocess.TimeoutExpired:
            self.report({'ERROR'}, "Docker command timed out")
        except FileNotFoundError:
            self.report({'ERROR'}, f"Docker executable not found: {prefs.docker_executable}")
        except Exception as e:
            self.report({'ERROR'}, f"Error testing Docker: {str(e)}")

        return {'FINISHED'}


class RENDER_OT_build_docker_image(bpy.types.Operator):
    """Build the Docker image for render nodes"""
    bl_idname = "render.build_docker_image"
    bl_label = "Build Docker Image"
    bl_description = "Build the Docker image for render nodes"

    def execute(self, context):
        self.report({'INFO'}, "Docker image build not implemented yet")
        # TODO: Implement Docker image building
        return {'FINISHED'}


# Registration
classes = [
    DistributedRenderPreferences,
    RENDER_OT_test_docker_connection,
    RENDER_OT_build_docker_image,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)