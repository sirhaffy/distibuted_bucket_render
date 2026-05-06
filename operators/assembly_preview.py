"""
Preview Engine - Handles quick preview assembly
Stitches bucket images directly into a Blender image via pixel data
"""

import bpy
import time
from pathlib import Path
from typing import Dict


class PreviewEngine:
    """
    Handles creation of quick preview assemblies by reading bucket PNGs
    and compositing them into a single Blender image via pixel manipulation.
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene

    def create_preview(self, bucket_files: Dict[int, Path],
                      buckets_x: int, buckets_y: int) -> bool:
        """
        Create a quick preview by stitching bucket images together.

        Args:
            bucket_files: Dictionary of bucket_id -> file_path
            buckets_x, buckets_y: Grid dimensions

        Returns:
            True if successful
        """
        try:
            width = self.scene.distributed_render_res_x
            height = self.scene.distributed_render_res_y
            percentage = self.scene.distributed_render_percentage

            final_width = int(width * percentage / 100)
            final_height = int(height * percentage / 100)

            print(f"Creating preview assembly: {final_width}x{final_height}")

            # Create or reuse preview image
            preview_name = "DistributedRender_Preview"
            if preview_name in bpy.data.images:
                preview_img = bpy.data.images[preview_name]
                if preview_img.size[0] != final_width or preview_img.size[1] != final_height:
                    bpy.data.images.remove(preview_img)
                    preview_img = bpy.data.images.new(preview_name, final_width, final_height, alpha=True)
            else:
                preview_img = bpy.data.images.new(preview_name, final_width, final_height, alpha=True)

            # Initialize all pixels to black/transparent
            pixel_count = final_width * final_height * 4
            pixels = [0.0] * pixel_count

            bucket_width = final_width // buckets_x
            bucket_height = final_height // buckets_y

            # Load each bucket and place its pixels in the correct position
            for bucket_id, bucket_file in bucket_files.items():
                try:
                    bucket_x = bucket_id % buckets_x
                    bucket_y = bucket_id // buckets_x

                    # Load bucket image
                    img_name = f"_temp_bucket_{bucket_id}"
                    if img_name in bpy.data.images:
                        bpy.data.images.remove(bpy.data.images[img_name])

                    bucket_img = bpy.data.images.load(str(bucket_file))
                    bucket_img.name = img_name

                    b_width = bucket_img.size[0]
                    b_height = bucket_img.size[1]
                    bucket_pixels = list(bucket_img.pixels[:])

                    # Calculate placement offset
                    # Blender images are bottom-left origin
                    offset_x = bucket_x * bucket_width
                    offset_y = (buckets_y - 1 - bucket_y) * bucket_height

                    # Copy pixels row by row
                    for row in range(min(b_height, bucket_height)):
                        dst_y = offset_y + row
                        if dst_y >= final_height:
                            break

                        src_start = row * b_width * 4
                        src_end = src_start + min(b_width, bucket_width) * 4

                        dst_start = (dst_y * final_width + offset_x) * 4
                        copy_width = min(b_width, bucket_width) * 4

                        pixels[dst_start:dst_start + copy_width] = bucket_pixels[src_start:src_start + copy_width]

                    # Clean up temp image
                    bpy.data.images.remove(bucket_img)
                    print(f"  Placed bucket {bucket_id} at grid ({bucket_x}, {bucket_y})")

                except Exception as e:
                    print(f"  Error placing bucket {bucket_id}: {e}")
                    continue

            # Write pixels to preview image
            preview_img.pixels = pixels
            preview_img.update()

            # Show in Image Editor if one is open
            for area in self.context.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'IMAGE_EDITOR':
                            space.image = preview_img
                            break
                    break

            print(f"Preview complete: {len(bucket_files)} buckets assembled")
            return True

        except Exception as e:
            print(f"Preview engine error: {e}")
            import traceback
            traceback.print_exc()
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