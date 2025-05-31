"""
Preview Engine - Handles quick preview assembly
Responsible for creating fast preview composites for user feedback
"""

import bpy
import time
from pathlib import Path
from typing import Dict


class PreviewEngine:
    """
    Handles creation of quick preview assemblies using Blender native functions
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.temp_scene = None
        self.loaded_images = []

    def create_preview(self, bucket_files: Dict[int, Path],
                      buckets_x: int, buckets_y: int) -> bool:
        """
        Create a quick preview assembly

        Args:
            bucket_files: Dictionary of bucket_id -> file_path
            buckets_x, buckets_y: Grid dimensions

        Returns:
            True if successful
        """
        try:
            # Get render resolution
            width = self.scene.distributed_render_res_x
            height = self.scene.distributed_render_res_y
            percentage = self.scene.distributed_render_percentage

            final_width = int(width * percentage / 100)
            final_height = int(height * percentage / 100)

            print(f"Creating preview assembly using Blender native: {final_width}x{final_height}")

            # Create temporary scene for preview
            if not self._create_temp_scene():
                return False

            # Load and position bucket images
            if not self._setup_preview_compositor(bucket_files, buckets_x, buckets_y, final_width, final_height):
                self._cleanup()
                return False

            # Render the preview
            preview_img = self._render_preview(final_width, final_height)
            if not preview_img:
                self._cleanup()
                return False

            # Show the preview in UI
            success = self._show_preview_in_ui(preview_img)

            # Cleanup
            self._cleanup()

            return success

        except Exception as e:
            print(f"Preview engine error: {e}")
            import traceback
            traceback.print_exc()
            self._cleanup()
            return False

    def _create_temp_scene(self) -> bool:
        """Create temporary scene for preview"""
        try:
            temp_scene_name = "DistributedRender_Preview_Temp"

            # Remove existing temp scene if it exists
            if temp_scene_name in bpy.data.scenes:
                bpy.data.scenes.remove(bpy.data.scenes[temp_scene_name])

            # Create new scene for preview assembly
            self.temp_scene = bpy.data.scenes.new(temp_scene_name)
            self.temp_scene.use_nodes = True
            self.temp_scene.node_tree.nodes.clear()

            print("✓ Created temporary scene for preview")
            return True

        except Exception as e:
            print(f"Error creating temp scene: {e}")
            return False

    def _setup_preview_compositor(self, bucket_files: Dict[int, Path],
                                 buckets_x: int, buckets_y: int,
                                 final_width: int, final_height: int) -> bool:
        """Setup compositor nodes for preview"""
        try:
            nodes = self.temp_scene.node_tree.nodes
            links = self.temp_scene.node_tree.links

            print(f"Processing {len(bucket_files)} bucket files for preview...")

            # Load bucket images as Blender images
            self.loaded_images = []
            image_nodes = []

            for bucket_id, bucket_file in bucket_files.items():
                try:
                    # Calculate bucket position in grid
                    bucket_x = bucket_id % buckets_x
                    bucket_y = bucket_id // buckets_x

                    # Load image into Blender
                    img_name = f"preview_bucket_{bucket_id}"

                    # Remove existing if present
                    if img_name in bpy.data.images:
                        bpy.data.images.remove(bpy.data.images[img_name])

                    # Load the bucket image
                    bucket_img = bpy.data.images.load(str(bucket_file))
                    bucket_img.name = img_name
                    self.loaded_images.append(bucket_img)

                    # Create image node in compositor
                    img_node = nodes.new(type='CompositorNodeImage')
                    img_node.image = bucket_img
                    img_node.label = f"Bucket {bucket_id}"
                    img_node.location = (bucket_id * 300, bucket_id * -150)

                    # Create translate node to position the bucket
                    translate_node = nodes.new(type='CompositorNodeTranslate')
                    translate_node.location = (bucket_id * 300 + 200, bucket_id * -150)

                    # Calculate translation - position buckets in correct grid locations
                    # Convert grid position to normalized coordinates (-1 to 1)
                    norm_x = (bucket_x / (buckets_x - 1)) * 2 - 1 if buckets_x > 1 else 0
                    norm_y = -(bucket_y / (buckets_y - 1)) * 2 + 1 if buckets_y > 1 else 0

                    # Scale to bucket size
                    translate_x = norm_x * (final_width / buckets_x / 2)
                    translate_y = norm_y * (final_height / buckets_y / 2)

                    translate_node.inputs['X'].default_value = translate_x
                    translate_node.inputs['Y'].default_value = translate_y

                    # Create scale node to resize buckets
                    scale_node = nodes.new(type='CompositorNodeScale')
                    scale_node.location = (bucket_id * 300 + 400, bucket_id * -150)
                    scale_node.space = 'RELATIVE'

                    # Scale buckets to fit grid
                    scale_factor = 1.0 / max(buckets_x, buckets_y)
                    scale_node.inputs['X'].default_value = scale_factor
                    scale_node.inputs['Y'].default_value = scale_factor

                    # Connect nodes
                    links.new(img_node.outputs['Image'], scale_node.inputs['Image'])
                    links.new(scale_node.outputs['Image'], translate_node.inputs['Image'])

                    image_nodes.append(translate_node)

                    print(f"✓ Added bucket {bucket_id} at grid position ({bucket_x}, {bucket_y})")

                except Exception as e:
                    print(f"✗ Error processing bucket {bucket_id}: {e}")
                    continue

            if not image_nodes:
                print("✗ No bucket images could be loaded")
                return False

            # Combine all buckets using Alpha Over nodes
            print(f"Combining {len(image_nodes)} bucket images...")

            if len(image_nodes) == 1:
                final_node = image_nodes[0]
            else:
                # Start with first image
                final_node = image_nodes[0]

                # Add each subsequent image
                for i in range(1, len(image_nodes)):
                    alpha_over = nodes.new(type='CompositorNodeAlphaOver')
                    alpha_over.location = (1000 + i * 200, 0)

                    # Connect: background (accumulated) and foreground (new bucket)
                    links.new(final_node.outputs['Image'], alpha_over.inputs[1])  # Background
                    links.new(image_nodes[i].outputs['Image'], alpha_over.inputs[2])  # Foreground

                    final_node = alpha_over

            # Create output node
            output_node = nodes.new(type='CompositorNodeComposite')
            output_node.location = (1500, 0)
            links.new(final_node.outputs['Image'], output_node.inputs['Image'])

            print("✓ Preview compositor setup complete")
            return True

        except Exception as e:
            print(f"Error setting up preview compositor: {e}")
            return False

    def _render_preview(self, final_width: int, final_height: int):
        """Render the preview and return the result image"""
        try:
            # Set render settings for the temp scene
            self.temp_scene.render.resolution_x = final_width
            self.temp_scene.render.resolution_y = final_height
            self.temp_scene.render.resolution_percentage = 100
            self.temp_scene.render.image_settings.file_format = 'PNG'
            self.temp_scene.render.image_settings.color_mode = 'RGBA'

            # Switch to temp scene and render
            original_scene = self.context.scene
            self.context.window.scene = self.temp_scene

            print(f"Rendering preview assembly...")
            bpy.ops.render.render()

            # Get the render result
            render_result = bpy.data.images.get('Render Result')
            if render_result:
                # Create a copy of the render result
                preview_name = f"DistributedRender_Preview_{int(time.time())}"

                # Remove existing preview
                if preview_name in bpy.data.images:
                    bpy.data.images.remove(bpy.data.images[preview_name])

                # Create new image and copy pixels
                preview_img = bpy.data.images.new(preview_name, final_width, final_height, alpha=True)

                # Copy pixel data from render result
                if len(render_result.pixels) > 0:
                    preview_img.pixels = render_result.pixels[:]
                    preview_img.update()

                # Switch back to original scene
                self.context.window.scene = original_scene

                print(f"✓ Preview render completed: {preview_name}")
                return preview_img
            else:
                print("✗ No render result found")
                self.context.window.scene = original_scene
                return None

        except Exception as e:
            print(f"Error rendering preview: {e}")
            # Switch back to original scene on error
            try:
                self.context.window.scene = original_scene
            except:
                pass
            return None

    def _show_preview_in_ui(self, preview_img) -> bool:
        """Show the preview in Blender's UI"""
        try:
            # Set the preview as the active image in Image Editor
            for area in self.context.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'IMAGE_EDITOR':
                            space.image = preview_img
                            break
                    break

            # Try to switch to Rendering workspace
            try:
                self.context.window.workspace = bpy.data.workspaces['Rendering']
                print("✓ Switched to Rendering workspace")
            except:
                try:
                    self.context.window.workspace = bpy.data.workspaces['Shading']
                    print("✓ Switched to Shading workspace")
                except:
                    print("! Could not switch workspace")

            print(f"✓ Preview assembly completed using pure Blender!")
            print(f"✓ Preview shows {len(self.loaded_images)} buckets assembled")
            print(f"✓ Result available as '{preview_img.name}' in Image Editor")

            return True

        except Exception as e:
            print(f"Error showing preview in UI: {e}")
            return False

    def _cleanup(self):
        """Clean up temporary resources"""
        try:
            # Remove temp scene
            if self.temp_scene and self.temp_scene.name in bpy.data.scenes:
                bpy.data.scenes.remove(self.temp_scene)
                print("✓ Cleaned up temporary preview scene")

            # Remove temp images
            for img in self.loaded_images:
                if img.name in bpy.data.images:
                    bpy.data.images.remove(img)

            if self.loaded_images:
                print(f"✓ Cleaned up {len(self.loaded_images)} temporary preview images")

            self.temp_scene = None
            self.loaded_images = []

        except Exception as e:
            print(f"Warning: Error during preview cleanup: {e}")


class PreviewUtils:
    """
    Utility functions for preview operations
    """

    @staticmethod
    def calculate_preview_scale(original_width: int, original_height: int,
                               max_preview_size: int = 1024) -> float:
        """
        Calculate scale factor for preview to fit within max size

        Args:
            original_width, original_height: Original image dimensions
            max_preview_size: Maximum size for preview

        Returns:
            Scale factor (1.0 = no scaling)
        """
        max_dimension = max(original_width, original_height)
        if max_dimension <= max_preview_size:
            return 1.0
        return max_preview_size / max_dimension

    @staticmethod
    def get_bucket_grid_info(buckets_x: int, buckets_y: int) -> dict:
        """
        Get information about bucket grid layout

        Args:
            buckets_x, buckets_y: Grid dimensions

        Returns:
            Dictionary with grid information
        """
        return {
            'total_buckets': buckets_x * buckets_y,
            'aspect_ratio': buckets_x / buckets_y if buckets_y > 0 else 1.0,
            'is_square_grid': buckets_x == buckets_y,
            'grid_complexity': 'simple' if buckets_x * buckets_y <= 4 else 'complex'
        }

    @staticmethod
    def estimate_preview_time(bucket_count: int, image_resolution: int) -> float:
        """
        Estimate time required for preview generation

        Args:
            bucket_count: Number of buckets to process
            image_resolution: Total pixel count

        Returns:
            Estimated time in seconds
        """
        # Basic estimation based on bucket count and resolution
        base_time = 2.0  # Base overhead
        bucket_time = bucket_count * 0.5  # Time per bucket
        resolution_factor = image_resolution / (1920 * 1080)  # Factor based on HD resolution

        return base_time + bucket_time * resolution_factor