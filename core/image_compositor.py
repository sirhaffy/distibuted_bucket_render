"""
Image compositor for distributed rendering
Assembles rendered buckets into final image progressively
"""

import bpy
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import threading

from .bucket_splitter import RenderBucket
from ..utils.logging_utils import get_logger, PerformanceTimer
from ..utils.file_utils import FileUtils


class ImageCompositor:
    """
    Handles progressive assembly of rendered buckets into final image
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.render = self.scene.render
        self.prefs = context.preferences.addons[__package__.split('.')[0]].preferences
        self.logger = get_logger(__name__)

        # Calculate final image dimensions
        self.final_width = int(self.render.resolution_x * self.render.resolution_percentage / 100)
        self.final_height = int(self.render.resolution_y * self.render.resolution_percentage / 100)

        # Initialize final image
        self.final_image: Optional[Image.Image] = None
        self.composition_mask: Optional[np.ndarray] = None  # Track which pixels have been rendered
        self.assembled_buckets: set = set()

        # Threading for safe updates
        self.composition_lock = threading.Lock()

        # Paths
        self.output_dir = Path(bpy.path.abspath(self.prefs.output_directory))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Preview settings
        self.preview_scale = 0.25  # Scale for preview updates
        self.show_bucket_borders = True
        self.show_progress_overlay = True

        self.logger.info(f"ImageCompositor initialized - final size: {self.final_width}x{self.final_height}")
        self._initialize_composition()

    def _initialize_composition(self):
        """Initialize the final composition canvas"""
        with self.composition_lock:
            # Create blank final image
            self.final_image = Image.new('RGBA', (self.final_width, self.final_height), (0, 0, 0, 0))

            # Create composition mask (0 = not rendered, 1 = rendered)
            self.composition_mask = np.zeros((self.final_height, self.final_width), dtype=np.uint8)

            self.logger.info("Initialized composition canvas")

    def add_bucket_to_composition(self, bucket: RenderBucket) -> bool:
        """
        Add a rendered bucket to the final composition

        Args:
            bucket: Completed bucket to add

        Returns:
            True if bucket was successfully added
        """
        if bucket.id in self.assembled_buckets:
            self.logger.warning(f"Bucket {bucket.id} already assembled, skipping")
            return False

        if not bucket.output_path or not Path(bucket.output_path).exists():
            self.logger.error(f"Bucket {bucket.id} output file not found: {bucket.output_path}")
            return False

        try:
            with PerformanceTimer(f"assemble_bucket_{bucket.id}", "compositor"):
                success = self._composite_bucket(bucket)

                if success:
                    self.assembled_buckets.add(bucket.id)
                    self._update_progress_display()

                    # Save progressive preview if enabled
                    if self.scene.distributed_render_progressive:
                        self._save_progressive_preview()

                    self.logger.info(f"Successfully assembled bucket {bucket.id}")
                    return True

        except Exception as e:
            self.logger.error(f"Error assembling bucket {bucket.id}: {e}")

        return False

    def _composite_bucket(self, bucket: RenderBucket) -> bool:
        """
        Composite a single bucket into the final image

        Args:
            bucket: Bucket to composite

        Returns:
            True if successful
        """
        try:
            # Load bucket image
            bucket_image = Image.open(bucket.output_path)

            # Get pixel bounds for this bucket
            x_start, y_start, x_end, y_end = bucket.get_pixel_bounds(self.final_width, self.final_height)

            # Validate bounds
            if x_start < 0 or y_start < 0 or x_end > self.final_width or y_end > self.final_height:
                self.logger.error(f"Bucket {bucket.id} bounds out of range: ({x_start},{y_start}) to ({x_end},{y_end})")
                return False

            # Calculate bucket dimensions
            bucket_width = x_end - x_start
            bucket_height = y_end - y_start

            # Resize bucket image if necessary (in case of border rendering without crop)
            if bucket_image.size != (bucket_width, bucket_height):
                # Extract the bucket region from the full-size render
                if bucket_image.size == (self.final_width, self.final_height):
                    # Bucket was rendered at full resolution, extract the region
                    bucket_image = bucket_image.crop((x_start, y_start, x_end, y_end))
                else:
                    # Resize to fit bucket dimensions
                    bucket_image = bucket_image.resize((bucket_width, bucket_height), Image.LANCZOS)

            # Convert to RGBA if needed
            if bucket_image.mode != 'RGBA':
                bucket_image = bucket_image.convert('RGBA')

            with self.composition_lock:
                # Paste bucket into final image
                self.final_image.paste(bucket_image, (x_start, y_start), bucket_image)

                # Update composition mask
                self.composition_mask[y_start:y_end, x_start:x_end] = 1

            return True

        except Exception as e:
            self.logger.error(f"Error compositing bucket {bucket.id}: {e}")
            return False

    def _update_progress_display(self):
        """Update progress display in Blender"""
        try:
            # Calculate completion percentage
            total_pixels = self.final_width * self.final_height
            rendered_pixels = np.sum(self.composition_mask)
            completion_percentage = (rendered_pixels / total_pixels) * 100 if total_pixels > 0 else 0

            # Update scene status
            self.scene.distributed_render_status = f"Assembling ({completion_percentage:.1f}%)"

            self.logger.debug(f"Progress: {completion_percentage:.1f}% ({rendered_pixels}/{total_pixels} pixels)")

        except Exception as e:
            self.logger.error(f"Error updating progress display: {e}")

    def _save_progressive_preview(self):
        """Save a progressive preview of the current composition"""
        try:
            with self.composition_lock:
                if not self.final_image:
                    return

                # Create preview image with progress overlay
                preview_image = self.final_image.copy()

                if self.show_progress_overlay:
                    preview_image = self._add_progress_overlay(preview_image)

                # Save preview
                preview_path = self.output_dir / "progressive_preview.png"
                preview_image.save(preview_path)

                # Also create a smaller preview for quick viewing
                small_preview = preview_image.copy()
                small_preview.thumbnail((512, 512), Image.LANCZOS)
                small_preview_path = self.output_dir / "progressive_preview_small.png"
                small_preview.save(small_preview_path)

        except Exception as e:
            self.logger.error(f"Error saving progressive preview: {e}")

    def _add_progress_overlay(self, image: Image.Image) -> Image.Image:
        """
        Add progress overlay to image showing bucket completion

        Args:
            image: Base image to add overlay to

        Returns:
            Image with progress overlay
        """
        try:
            # Create overlay
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Show bucket borders if enabled
            if self.show_bucket_borders:
                self._draw_bucket_borders(draw)

            # Show completion statistics
            self._draw_progress_stats(draw, image.size)

            # Composite overlay onto image
            result = Image.alpha_composite(image.convert('RGBA'), overlay)
            return result

        except Exception as e:
            self.logger.error(f"Error adding progress overlay: {e}")
            return image

    def _draw_bucket_borders(self, draw: ImageDraw.Draw):
        """Draw bucket borders on overlay"""
        try:
            buckets_x = self.scene.distributed_render_buckets_x
            buckets_y = self.scene.distributed_render_buckets_y

            # Draw vertical lines
            for x in range(1, buckets_x):
                x_pos = int((x / buckets_x) * self.final_width)
                draw.line([(x_pos, 0), (x_pos, self.final_height)], fill=(255, 255, 255, 128), width=1)

            # Draw horizontal lines
            for y in range(1, buckets_y):
                y_pos = int((y / buckets_y) * self.final_height)
                draw.line([(0, y_pos), (self.final_width, y_pos)], fill=(255, 255, 255, 128), width=1)

        except Exception as e:
            self.logger.error(f"Error drawing bucket borders: {e}")

    def _draw_progress_stats(self, draw: ImageDraw.Draw, image_size: Tuple[int, int]):
        """Draw progress statistics on overlay"""
        try:
            # Calculate stats
            total_pixels = self.final_width * self.final_height
            rendered_pixels = np.sum(self.composition_mask)
            completion_percentage = (rendered_pixels / total_pixels) * 100 if total_pixels > 0 else 0

            # Prepare text
            stats_text = [
                f"Progress: {completion_percentage:.1f}%",
                f"Buckets: {len(self.assembled_buckets)}/{self.scene.distributed_render_buckets_x * self.scene.distributed_render_buckets_y}",
                f"Resolution: {self.final_width}x{self.final_height}"
            ]

            # Draw semi-transparent background
            text_height = 60
            draw.rectangle([(10, 10), (300, 10 + text_height)], fill=(0, 0, 0, 128))

            # Draw text
            try:
                # Try to use a nice font
                font = ImageFont.truetype("arial.ttf", 14)
            except:
                # Fall back to default font
                font = ImageFont.load_default()

            y_offset = 15
            for line in stats_text:
                draw.text((15, y_offset), line, fill=(255, 255, 255, 255), font=font)
                y_offset += 18

        except Exception as e:
            self.logger.error(f"Error drawing progress stats: {e}")

    def compose_final_image(self, completed_buckets: List[RenderBucket]) -> str:
        """
        Compose the final image from all completed buckets

        Args:
            completed_buckets: List of all completed buckets

        Returns:
            Path to final composed image
        """
        self.logger.info("Composing final image...")

        with PerformanceTimer("compose_final_image", "compositor"):
            # Ensure all buckets are assembled
            for bucket in completed_buckets:
                if bucket.id not in self.assembled_buckets:
                    self.add_bucket_to_composition(bucket)

            # Generate final output path
            final_path = self._get_final_output_path()

            # Save final image
            with self.composition_lock:
                if self.final_image:
                    # Remove any progress overlays for final save
                    clean_image = self.final_image.copy()

                    # Convert to desired output format
                    output_format = self.scene.render.image_settings.file_format
                    clean_image = self._convert_to_output_format(clean_image, output_format)

                    clean_image.save(final_path)
                    self.logger.info(f"Final image saved to: {final_path}")
                else:
                    raise RuntimeError("No final image to save")

        return str(final_path)

    def _get_final_output_path(self) -> Path:
        """Get path for final output image"""
        # Use Blender's render filepath if set
        if self.scene.render.filepath:
            base_path = Path(bpy.path.abspath(self.scene.render.filepath))
        else:
            base_path = self.output_dir / "distributed_render"

        # Add appropriate extension based on file format
        file_format = self.scene.render.image_settings.file_format
        extension_map = {
            'PNG': '.png',
            'JPEG': '.jpg',
            'TIFF': '.tif',
            'OPEN_EXR': '.exr',
            'HDR': '.hdr'
        }

        extension = extension_map.get(file_format, '.png')

        # Ensure unique filename
        final_path = base_path.with_suffix(extension)
        if final_path.exists():
            final_path = FileUtils.get_unique_filename(final_path.parent, final_path.name)
            final_path = final_path.parent / final_path

        return final_path

    def _convert_to_output_format(self, image: Image.Image, file_format: str) -> Image.Image:
        """
        Convert image to desired output format

        Args:
            image: Source image
            file_format: Target file format

        Returns:
            Converted image
        """
        try:
            color_mode = self.scene.render.image_settings.color_mode

            if file_format == 'JPEG':
                # JPEG doesn't support alpha, convert to RGB
                if image.mode == 'RGBA':
                    # Create white background
                    background = Image.new('RGB', image.size, (255, 255, 255))
                    background.paste(image, mask=image.split()[3])  # Use alpha as mask
                    return background
                else:
                    return image.convert('RGB')

            elif file_format == 'PNG':
                if color_mode == 'RGB':
                    return image.convert('RGB')
                else:
                    return image.convert('RGBA')

            elif file_format in ['TIFF', 'OPEN_EXR']:
                # High bit depth formats
                if color_mode == 'RGB':
                    return image.convert('RGB')
                else:
                    return image.convert('RGBA')

            else:
                # Default to RGBA
                return image.convert('RGBA')

        except Exception as e:
            self.logger.error(f"Error converting to format {file_format}: {e}")
            return image

    def create_bucket_contact_sheet(self, buckets: List[RenderBucket]) -> str:
        """
        Create a contact sheet showing all individual buckets

        Args:
            buckets: List of buckets to include

        Returns:
            Path to contact sheet image
        """
        self.logger.info("Creating bucket contact sheet...")

        try:
            # Calculate grid layout
            total_buckets = len(buckets)
            grid_cols = int(np.ceil(np.sqrt(total_buckets)))
            grid_rows = int(np.ceil(total_buckets / grid_cols))

            # Calculate thumbnail size
            thumb_width = 200
            thumb_height = int(thumb_width * (self.final_height / self.final_width))

            # Create contact sheet
            sheet_width = grid_cols * thumb_width + (grid_cols + 1) * 10  # 10px margin
            sheet_height = grid_rows * thumb_height + (grid_rows + 1) * 10
            contact_sheet = Image.new('RGB', (sheet_width, sheet_height), (64, 64, 64))

            # Add buckets to contact sheet
            for i, bucket in enumerate(buckets):
                if not bucket.output_path or not Path(bucket.output_path).exists():
                    continue

                # Calculate position
                col = i % grid_cols
                row = i // grid_cols
                x = 10 + col * (thumb_width + 10)
                y = 10 + row * (thumb_height + 10)

                try:
                    # Load and resize bucket image
                    bucket_img = Image.open(bucket.output_path)
                    bucket_img.thumbnail((thumb_width, thumb_height), Image.LANCZOS)

                    # Paste into contact sheet
                    contact_sheet.paste(bucket_img, (x, y))

                    # Add bucket ID label
                    draw = ImageDraw.Draw(contact_sheet)
                    try:
                        font = ImageFont.truetype("arial.ttf", 12)
                    except:
                        font = ImageFont.load_default()

                    label = f"Bucket {bucket.id}"
                    draw.text((x + 5, y + 5), label, fill=(255, 255, 255), font=font)

                except Exception as e:
                    self.logger.warning(f"Error adding bucket {bucket.id} to contact sheet: {e}")

            # Save contact sheet
            contact_sheet_path = self.output_dir / "bucket_contact_sheet.png"
            contact_sheet.save(contact_sheet_path)

            self.logger.info(f"Contact sheet saved to: {contact_sheet_path}")
            return str(contact_sheet_path)

        except Exception as e:
            self.logger.error(f"Error creating contact sheet: {e}")
            raise

    def create_progress_animation(self, bucket_sequence: List[RenderBucket]) -> str:
        """
        Create an animation showing the progressive assembly

        Args:
            bucket_sequence: Buckets in completion order

        Returns:
            Path to animation file
        """
        self.logger.info("Creating progress animation...")

        try:
            # Reset composition to create animation frames
            self._initialize_composition()

            frames = []
            frame_duration = 500  # milliseconds per frame

            # Create frames showing progressive assembly
            for i, bucket in enumerate(bucket_sequence):
                self.add_bucket_to_composition(bucket)

                # Create frame with progress overlay
                with self.composition_lock:
                    frame = self.final_image.copy()
                    frame = self._add_progress_overlay(frame)

                    # Scale down for reasonable file size
                    frame.thumbnail((512, 512), Image.LANCZOS)
                    frames.append(frame)

            # Save as animated GIF
            animation_path = self.output_dir / "render_progress.gif"

            if frames:
                frames[0].save(
                    animation_path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=frame_duration,
                    loop=0
                )

                self.logger.info(f"Progress animation saved to: {animation_path}")
                return str(animation_path)
            else:
                raise RuntimeError("No frames created for animation")

        except Exception as e:
            self.logger.error(f"Error creating progress animation: {e}")
            raise

    def get_composition_stats(self) -> Dict[str, any]:
        """
        Get statistics about the current composition

        Returns:
            Dictionary with composition statistics
        """
        with self.composition_lock:
            total_pixels = self.final_width * self.final_height
            rendered_pixels = np.sum(self.composition_mask) if self.composition_mask is not None else 0
            completion_percentage = (rendered_pixels / total_pixels) * 100 if total_pixels > 0 else 0

            return {
                'total_pixels': total_pixels,
                'rendered_pixels': int(rendered_pixels),
                'completion_percentage': completion_percentage,
                'assembled_buckets': len(self.assembled_buckets),
                'final_width': self.final_width,
                'final_height': self.final_height,
                'has_final_image': self.final_image is not None
            }

    def cleanup(self):
        """Clean up compositor resources"""
        self.logger.info("Cleaning up image compositor...")

        with self.composition_lock:
            if self.final_image:
                self.final_image.close()
                self.final_image = None

            self.composition_mask = None
            self.assembled_buckets.clear()

        self.logger.info("Image compositor cleanup complete")

    def preview_bucket_layout(self, buckets: List[RenderBucket]) -> str:
        """
        Create a preview image showing bucket layout

        Args:
            buckets: List of buckets to preview

        Returns:
            Path to preview image
        """
        try:
            # Create preview image
            preview_size = (512, int(512 * (self.final_height / self.final_width)))
            preview = Image.new('RGB', preview_size, (64, 64, 64))
            draw = ImageDraw.Draw(preview)

            # Draw bucket boundaries
            scale_x = preview_size[0] / self.final_width
            scale_y = preview_size[1] / self.final_height

            for bucket in buckets:
                # Scale bucket bounds to preview size
                x1 = int(bucket.x_start * preview_size[0])
                y1 = int(bucket.y_start * preview_size[1])
                x2 = int(bucket.x_end * preview_size[0])
                y2 = int(bucket.y_end * preview_size[1])

                # Draw bucket border
                draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 255), width=1)

                # Draw bucket ID
                try:
                    font = ImageFont.truetype("arial.ttf", 10)
                except:
                    font = ImageFont.load_default()

                bucket_center_x = (x1 + x2) // 2
                bucket_center_y = (y1 + y2) // 2
                draw.text((bucket_center_x - 10, bucket_center_y - 5),
                          str(bucket.id), fill=(255, 255, 255), font=font)

            # Save preview
            preview_path = self.output_dir / "bucket_layout_preview.png"
            preview.save(preview_path)

            self.logger.info(f"Bucket layout preview saved to: {preview_path}")
            return str(preview_path)

        except Exception as e:
            self.logger.error(f"Error creating bucket layout preview: {e}")
            raise