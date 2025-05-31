"""
Bucket manager operators for distributed rendering
Additional operators for bucket management and optimization
"""

import bpy
from bpy.types import Operator
from bpy.props import IntProperty, FloatProperty, BoolProperty, StringProperty
import bmesh
import mathutils
from typing import List, Tuple
import numpy as np

from ..core.bucket_splitter import BucketSplitter, RenderBucket
from ..utils.logging_utils import get_logger


class RENDER_OT_optimize_bucket_layout(Operator):
    """Optimize bucket layout based on scene complexity"""
    bl_idname = "render.optimize_bucket_layout"
    bl_label = "Optimize Bucket Layout"
    bl_description = "Automatically optimize bucket layout based on scene complexity"
    bl_options = {'REGISTER', 'UNDO'}

    # Operator properties
    target_bucket_count: IntProperty(
        name="Target Bucket Count",
        description="Target number of buckets to create",
        default=0,
        min=0,
        max=256
    )

    min_bucket_size: IntProperty(
        name="Min Bucket Size",
        description="Minimum bucket size in pixels",
        default=64,
        min=32,
        max=512
    )

    complexity_threshold: FloatProperty(
        name="Complexity Threshold",
        description="Threshold for splitting high-complexity areas",
        default=1.5,
        min=0.1,
        max=5.0
    )

    def execute(self, context):
        """Execute bucket optimization"""
        scene = context.scene
        logger = get_logger(__name__)

        try:
            logger.info("Starting bucket layout optimization...")

            # Create bucket splitter
            splitter = BucketSplitter(context)

            # Analyze scene complexity
            complexity_map = self._analyze_scene_complexity(context, splitter)

            # Generate optimized bucket layout
            optimized_buckets = self._generate_adaptive_buckets(
                splitter, complexity_map, self.target_bucket_count
            )

            # Update scene settings based on optimization
            if optimized_buckets:
                # Calculate equivalent grid size
                bucket_count = len(optimized_buckets)
                grid_size = int(np.sqrt(bucket_count))

                scene.distributed_render_buckets_x = grid_size
                scene.distributed_render_buckets_y = grid_size

                self.report({'INFO'}, f"Optimized layout: {bucket_count} buckets in {grid_size}x{grid_size} grid")
            else:
                self.report({'WARNING'}, "Could not generate optimized layout, keeping current settings")

            return {'FINISHED'}

        except Exception as e:
            logger.error(f"Error optimizing bucket layout: {e}")
            self.report({'ERROR'}, f"Optimization failed: {str(e)}")
            return {'CANCELLED'}

    def _analyze_scene_complexity(self, context, splitter: BucketSplitter) -> np.ndarray:
        """
        Analyze scene complexity to create a complexity map

        Args:
            context: Blender context
            splitter: Bucket splitter instance

        Returns:
            2D numpy array representing complexity across the render
        """
        logger = get_logger(__name__)
        logger.info("Analyzing scene complexity...")

        # Create complexity map
        map_width = 32  # Lower resolution for analysis
        map_height = int(map_width * (splitter.render_height / splitter.render_width))
        complexity_map = np.ones((map_height, map_width), dtype=np.float32)

        try:
            # Get camera and render settings
            scene = context.scene
            camera = scene.camera

            if not camera:
                logger.warning("No active camera found, using uniform complexity")
                return complexity_map

            # Get camera view matrix
            render = scene.render
            cam_matrix = camera.matrix_world

            # Analyze visible objects
            self._analyze_object_density(context, complexity_map, camera)
            self._analyze_material_complexity(context, complexity_map, camera)
            self._analyze_lighting_complexity(context, complexity_map)

        except Exception as e:
            logger.warning(f"Error in complexity analysis: {e}")

        return complexity_map

    def _analyze_object_density(self, context, complexity_map: np.ndarray, camera):
        """Analyze object density in camera view"""
        try:
            # Get visible mesh objects
            visible_objects = [obj for obj in context.scene.objects
                               if obj.visible_get() and obj.type == 'MESH' and obj.data]

            for obj in visible_objects:
                # Project object bounds to screen space
                bbox_2d = self._project_object_to_screen(obj, camera, context)
                if bbox_2d:
                    self._add_complexity_to_region(complexity_map, bbox_2d, 0.5)

        except Exception as e:
            get_logger(__name__).warning(f"Error analyzing object density: {e}")

    def _analyze_material_complexity(self, context, complexity_map: np.ndarray, camera):
        """Analyze material complexity"""
        try:
            for obj in context.scene.objects:
                if obj.visible_get() and obj.type == 'MESH' and obj.data and obj.material_slots:
                    material_complexity = 0.0

                    for slot in obj.material_slots:
                        if slot.material and slot.material.node_tree:
                            # Count nodes as complexity indicator
                            node_count = len(slot.material.node_tree.nodes)
                            material_complexity += node_count * 0.01

                    if material_complexity > 0:
                        bbox_2d = self._project_object_to_screen(obj, camera, context)
                        if bbox_2d:
                            self._add_complexity_to_region(complexity_map, bbox_2d, material_complexity)

        except Exception as e:
            get_logger(__name__).warning(f"Error analyzing material complexity: {e}")

    def _analyze_lighting_complexity(self, context, complexity_map: np.ndarray):
        """Analyze lighting complexity"""
        try:
            lights = [obj for obj in context.scene.objects if obj.type == 'LIGHT']

            # Add complexity for each light
            for light in lights:
                if light.visible_get():
                    # Simple: add complexity around light influence
                    # In a more sophisticated version, this would calculate actual light falloff
                    light_complexity = 0.3

                    # Add complexity to entire map (simplified)
                    complexity_map += light_complexity / len(lights)

        except Exception as e:
            get_logger(__name__).warning(f"Error analyzing lighting complexity: {e}")

    def _project_object_to_screen(self, obj, camera, context) -> Tuple[float, float, float, float]:
        """
        Project object bounding box to screen coordinates

        Returns:
            Tuple of (x_min, y_min, x_max, y_max) in normalized coordinates
        """
        try:
            # Get object bounding box in world space
            bbox_corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]

            # Project to camera space
            scene = context.scene
            render = scene.render

            # Use Blender's projection
            projected_points = []
            for corner in bbox_corners:
                # Convert to camera space
                co_2d = bpy_extras.object_utils.world_to_camera_view(scene, camera, corner)
                projected_points.append((co_2d.x, co_2d.y))

            if projected_points:
                x_coords = [p[0] for p in projected_points]
                y_coords = [p[1] for p in projected_points]

                return (min(x_coords), min(y_coords), max(x_coords), max(y_coords))

        except Exception as e:
            get_logger(__name__).debug(f"Error projecting object {obj.name}: {e}")

        return None

    def _add_complexity_to_region(self, complexity_map: np.ndarray,
                                  bbox_2d: Tuple[float, float, float, float],
                                  complexity_value: float):
        """Add complexity value to a screen region"""
        try:
            x_min, y_min, x_max, y_max = bbox_2d

            # Convert to map coordinates
            map_height, map_width = complexity_map.shape

            x_min_px = max(0, int(x_min * map_width))
            y_min_px = max(0, int(y_min * map_height))
            x_max_px = min(map_width, int(x_max * map_width))
            y_max_px = min(map_height, int(y_max * map_height))

            # Add complexity to region
            complexity_map[y_min_px:y_max_px, x_min_px:x_max_px] += complexity_value

        except Exception as e:
            get_logger(__name__).debug(f"Error adding complexity to region: {e}")

    def _generate_adaptive_buckets(self, splitter: BucketSplitter,
                                   complexity_map: np.ndarray,
                                   target_count: int) -> List[RenderBucket]:
        """
        Generate adaptive buckets based on complexity map

        Args:
            splitter: Bucket splitter instance
            complexity_map: Scene complexity map
            target_count: Target number of buckets

        Returns:
            List of adaptive buckets
        """
        logger = get_logger(__name__)

        # For now, return regular grid buckets
        # A full adaptive implementation would use quadtree subdivision
        # based on the complexity map

        logger.info("Adaptive bucket generation not fully implemented, using optimized grid")

        # Use target count to determine grid size
        if target_count <= 0:
            target_count = splitter.scene.distributed_render_containers * 2

        grid_size = int(np.sqrt(target_count))
        splitter.scene.distributed_render_buckets_x = grid_size
        splitter.scene.distributed_render_buckets_y = grid_size

        return splitter.create_buckets()


class RENDER_OT_analyze_bucket_complexity(Operator):
    """Analyze and display bucket complexity information"""
    bl_idname = "render.analyze_bucket_complexity"
    bl_label = "Analyze Bucket Complexity"
    bl_description = "Analyze complexity of current bucket layout"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """Execute complexity analysis"""
        try:
            logger = get_logger(__name__)
            logger.info("Analyzing bucket complexity...")

            # Create bucket splitter and analyze
            splitter = BucketSplitter(context)
            buckets = splitter.create_buckets()

            # Analyze each bucket
            complexity_stats = self._analyze_bucket_complexities(context, buckets)

            # Display results
            self._display_complexity_results(complexity_stats)

            self.report({'INFO'}, f"Analyzed {len(buckets)} buckets - see console for details")
            return {'FINISHED'}

        except Exception as e:
            get_logger

# Registration
classes = [
    RENDER_OT_optimize_bucket_layout,
    RENDER_OT_analyze_bucket_complexity,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)