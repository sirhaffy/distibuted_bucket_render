"""
Bucket splitter for distributed rendering
Divides render view into buckets using Blender's border render functionality
"""

import bpy
import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from ..utils.logging_utils import get_logger


@dataclass
class RenderBucket:
    """
    Represents a single render bucket
    """
    id: int
    x_start: float  # Normalized coordinates (0.0 to 1.0)
    y_start: float
    x_end: float
    y_end: float
    width_pixels: int  # Actual pixel dimensions
    height_pixels: int
    priority: int = 0  # Higher number = higher priority
    complexity_score: float = 1.0  # Estimated complexity (1.0 = normal)
    status: str = "pending"  # pending, assigned, rendering, complete, failed
    assigned_container: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def get_pixel_bounds(self, render_width: int, render_height: int) -> Tuple[int, int, int, int]:
        """
        Get pixel bounds for this bucket

        Returns:
            Tuple of (x_start, y_start, x_end, y_end) in pixels
        """
        x_start_px = int(self.x_start * render_width)
        y_start_px = int(self.y_start * render_height)
        x_end_px = int(self.x_end * render_width)
        y_end_px = int(self.y_end * render_height)

        return (x_start_px, y_start_px, x_end_px, y_end_px)

    def get_border_settings(self) -> Dict[str, float]:
        """
        Get Blender border render settings for this bucket

        Returns:
            Dictionary with border settings
        """
        return {
            'border_min_x': self.x_start,
            'border_min_y': self.y_start,
            'border_max_x': self.x_end,
            'border_max_y': self.y_end
        }


class BucketSplitter:
    """
    Handles splitting render view into buckets for distributed rendering
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.render = self.scene.render
        self.logger = get_logger(__name__)

        # Get render dimensions
        self.render_width = int(self.render.resolution_x * self.render.resolution_percentage / 100)
        self.render_height = int(self.render.resolution_y * self.render.resolution_percentage / 100)

        self.logger.info(f"Render resolution: {self.render_width}x{self.render_height}")

    def create_buckets(self) -> List[RenderBucket]:
        """
        Create buckets based on scene settings

        Returns:
            List of RenderBucket objects
        """
        n = self.scene.distributed_render_bucket_count
        buckets_x = n
        buckets_y = n

        self.logger.info(f"Creating {buckets_x}x{buckets_y} bucket grid ({buckets_x * buckets_y} total buckets)")

        buckets = []
        bucket_id = 0

        for y in range(buckets_y):
            for x in range(buckets_x):
                bucket = self._create_single_bucket(bucket_id, x, y, buckets_x, buckets_y)
                buckets.append(bucket)
                bucket_id += 1

        # Optimize bucket order and priorities
        if hasattr(self.scene, 'distributed_render_auto_optimize') and self.scene.distributed_render_auto_optimize:
            buckets = self._optimize_bucket_order(buckets)

        self.logger.info(f"Created {len(buckets)} buckets successfully")
        return buckets

    def _create_single_bucket(self, bucket_id: int, x: int, y: int,
                              total_x: int, total_y: int) -> RenderBucket:
        """
        Create a single bucket

        Args:
            bucket_id: Unique bucket identifier
            x, y: Grid position
            total_x, total_y: Total grid dimensions

        Returns:
            RenderBucket object
        """
        # Calculate normalized coordinates
        x_start = x / total_x
        y_start = y / total_y
        x_end = (x + 1) / total_x
        y_end = (y + 1) / total_y

        # Calculate pixel dimensions
        width_pixels = int((x_end - x_start) * self.render_width)
        height_pixels = int((y_end - y_start) * self.render_height)

        # Estimate complexity (basic implementation)
        complexity_score = self._estimate_bucket_complexity(x_start, y_start, x_end, y_end)

        # Assign priority (center buckets get higher priority)
        priority = self._calculate_bucket_priority(x, y, total_x, total_y)

        bucket = RenderBucket(
            id=bucket_id,
            x_start=x_start,
            y_start=y_start,
            x_end=x_end,
            y_end=y_end,
            width_pixels=width_pixels,
            height_pixels=height_pixels,
            priority=priority,
            complexity_score=complexity_score
        )

        self.logger.debug(f"Created bucket {bucket_id}: "
                          f"({x_start:.3f},{y_start:.3f}) to ({x_end:.3f},{y_end:.3f}) "
                          f"- {width_pixels}x{height_pixels}px, "
                          f"priority={priority}, complexity={complexity_score:.2f}")

        return bucket

    def _estimate_bucket_complexity(self, x_start: float, y_start: float,
                                    x_end: float, y_end: float) -> float:
        """
        Estimate rendering complexity for a bucket region

        This is a basic implementation - could be enhanced with:
        - Object density analysis
        - Material complexity
        - Light distribution
        - Geometry detail

        Args:
            x_start, y_start, x_end, y_end: Normalized bucket bounds

        Returns:
            Complexity score (1.0 = normal complexity)
        """
        complexity = 1.0

        try:
            # Basic complexity based on scene elements
            # This could be much more sophisticated

            # Count visible objects in bucket region (simplified)
            object_count = len([obj for obj in self.scene.objects
                                if obj.visible_get() and obj.type == 'MESH'])

            # Adjust complexity based on object density
            if object_count > 50:
                complexity *= 1.5
            elif object_count > 100:
                complexity *= 2.0

            # Check for lights in scene
            light_count = len([obj for obj in self.scene.objects
                               if obj.type == 'LIGHT' and obj.visible_get()])

            if light_count > 5:
                complexity *= 1.2

            # Check render engine specific complexity
            if self.render.engine == 'CYCLES':
                # Cycles complexity factors
                if hasattr(self.scene, 'cycles'):
                    if self.scene.cycles.samples > 1000:
                        complexity *= 1.3

                    # Check for subsurface scattering, volumetrics, etc.
                    # This would require more detailed material analysis

            elif self.render.engine == 'BLENDER_EEVEE':
                # EEVEE complexity factors
                if hasattr(self.scene, 'eevee'):
                    if self.scene.eevee.use_ssr:
                        complexity *= 1.1
                    if self.scene.eevee.use_bloom:
                        complexity *= 1.05

        except Exception as e:
            self.logger.warning(f"Error estimating bucket complexity: {e}")
            complexity = 1.0

        return max(0.1, min(5.0, complexity))  # Clamp between 0.1 and 5.0

    def _calculate_bucket_priority(self, x: int, y: int, total_x: int, total_y: int) -> int:
        """
        Calculate bucket priority based on position
        Center buckets typically get rendered first for preview purposes

        Args:
            x, y: Bucket grid position
            total_x, total_y: Total grid dimensions

        Returns:
            Priority value (higher = more important)
        """
        # Calculate distance from center
        center_x = (total_x - 1) / 2
        center_y = (total_y - 1) / 2

        distance = math.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
        max_distance = math.sqrt(center_x ** 2 + center_y ** 2)

        # Invert distance so center gets higher priority
        normalized_distance = distance / max_distance if max_distance > 0 else 0
        priority = int((1.0 - normalized_distance) * 100)

        return priority

    def _optimize_bucket_order(self, buckets: List[RenderBucket]) -> List[RenderBucket]:
        """
        Optimize bucket rendering order

        Args:
            buckets: List of buckets to optimize

        Returns:
            Optimized list of buckets
        """
        self.logger.info("Optimizing bucket order...")

        # Sort by priority first, then by complexity (simpler buckets first for quick preview)
        optimized_buckets = sorted(buckets,
                                   key=lambda b: (-b.priority, b.complexity_score))

        self.logger.info(f"Optimized bucket order - first bucket: {optimized_buckets[0].id}, "
                         f"last bucket: {optimized_buckets[-1].id}")

        return optimized_buckets

    def create_adaptive_buckets(self, target_bucket_count: Optional[int] = None) -> List[RenderBucket]:
        """
        Create adaptive buckets based on scene complexity

        This is an advanced feature that could analyze the scene and create
        variable-sized buckets based on complexity distribution

        Args:
            target_bucket_count: Target number of buckets (optional)

        Returns:
            List of adaptive buckets
        """
        # TODO: Implement adaptive bucket creation
        # For now, fall back to regular grid
        self.logger.info("Adaptive buckets not yet implemented, using regular grid")
        return self.create_buckets()

    def validate_buckets(self, buckets: List[RenderBucket]) -> bool:
        """
        Validate that buckets cover the entire render area without gaps or overlaps

        Args:
            buckets: List of buckets to validate

        Returns:
            True if buckets are valid
        """
        self.logger.info("Validating bucket coverage...")

        try:
            # Check that buckets cover entire area
            total_coverage = 0.0

            for bucket in buckets:
                # Calculate bucket area
                area = (bucket.x_end - bucket.x_start) * (bucket.y_end - bucket.y_start)
                total_coverage += area

                # Validate coordinates are within bounds
                if not (0.0 <= bucket.x_start < bucket.x_end <= 1.0):
                    self.logger.error(f"Bucket {bucket.id} has invalid X coordinates")
                    return False

                if not (0.0 <= bucket.y_start < bucket.y_end <= 1.0):
                    self.logger.error(f"Bucket {bucket.id} has invalid Y coordinates")
                    return False

            # Check total coverage (should be approximately 1.0)
            if abs(total_coverage - 1.0) > 0.001:
                self.logger.error(f"Bucket coverage error: {total_coverage:.6f} (should be 1.0)")
                return False

            self.logger.info(
                f"Bucket validation passed - {len(buckets)} buckets cover {total_coverage:.6f} of render area")
            return True

        except Exception as e:
            self.logger.error(f"Error validating buckets: {e}")
            return False

    def get_bucket_render_settings(self, bucket: RenderBucket) -> Dict[str, any]:
        """
        Get Blender render settings for a specific bucket

        Args:
            bucket: Bucket to get settings for

        Returns:
            Dictionary of render settings
        """
        border_settings = bucket.get_border_settings()

        settings = {
            # Border render settings
            'use_border': True,
            'border_min_x': border_settings['border_min_x'],
            'border_min_y': border_settings['border_min_y'],
            'border_max_x': border_settings['border_max_x'],
            'border_max_y': border_settings['border_max_y'],
            'use_crop_to_border': False,  # Keep full resolution for compositing

            # Output settings for bucket
            'filepath': f"//bucket_output/bucket_{bucket.id:04d}_",

            # Ensure consistent settings
            'resolution_x': self.render_width,
            'resolution_y': self.render_height,
            'resolution_percentage': 100,  # Already calculated in width/height
        }

        return settings

    def preview_buckets_in_viewport(self, buckets: List[RenderBucket]):
        """
        Create viewport overlay showing bucket divisions

        This would create visual guides in the viewport to show bucket boundaries

        Args:
            buckets: List of buckets to preview
        """
        # TODO: Implement viewport preview
        # This could use Blender's GPU drawing capabilities to show bucket outlines
        self.logger.info(f"Bucket preview not yet implemented (would show {len(buckets)} buckets)")
        pass