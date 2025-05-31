"""
Scene packer for distributed rendering
Packs all scene resources into a portable bundle
"""

import bpy
import shutil
import json
from pathlib import Path
from ..utils.file_utils import FileUtils
from ..utils.logging_utils import get_logger


class ScenePacker:
    """
    Handles packing of scene resources for distributed rendering
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.prefs = context.preferences.addons[__package__.split('.')[0]].preferences
        self.logger = get_logger(__name__)

        # Setup paths
        self.temp_dir = Path(bpy.path.abspath(self.prefs.temp_directory))
        self.packed_scene_dir = self.temp_dir / "packed_scene"
        self.resources_dir = self.packed_scene_dir / "resources"

    def pack_scene(self):
        """
        Main method to pack the entire scene
        Returns path to packed scene directory
        """
        self.logger.info("Starting scene packing...")

        # Create directories
        self._create_directories()

        # Pack different types of resources
        packed_info = {
            "blend_file": self._pack_blend_file(),
            "textures": self._pack_textures(),
            "hdris": self._pack_hdris(),
            "external_data": self._pack_external_data(),
            "render_settings": self._extract_render_settings(),
            "scene_info": self._extract_scene_info()
        }

        # Save packing manifest
        manifest_path = self.packed_scene_dir / "manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(packed_info, f, indent=2, default=str)

        self.logger.info(f"Scene packed successfully to: {self.packed_scene_dir}")
        return str(self.packed_scene_dir)

    def _create_directories(self):
        """Create necessary directories"""
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Remove old packed scene if exists
        if self.packed_scene_dir.exists():
            shutil.rmtree(self.packed_scene_dir)

        self.packed_scene_dir.mkdir(parents=True)
        self.resources_dir.mkdir(parents=True)

        self.logger.info(f"Created packing directories at: {self.packed_scene_dir}")

    def _pack_blend_file(self):
        """Save current blend file to packed directory"""
        blend_path = self.packed_scene_dir / "scene.blend"

        # Use Blender's pack_all to embed external resources
        if self.prefs.auto_pack_resources:
            bpy.ops.file.pack_all()
            self.logger.info("Packed all external resources into blend file")

        # Save blend file
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), copy=True)

        self.logger.info(f"Saved blend file to: {blend_path}")
        return str(blend_path.name)

    def _pack_textures(self):
        """Pack all texture files"""
        texture_info = []
        texture_dir = self.resources_dir / "textures"
        texture_dir.mkdir(exist_ok=True)

        # Find all images in the blend file
        for img in bpy.data.images:
            if img.filepath and not img.packed_file:
                original_path = Path(bpy.path.abspath(img.filepath))

                if original_path.exists() and original_path.is_file():
                    # Copy texture to resources directory
                    new_name = FileUtils.get_unique_filename(texture_dir, original_path.name)
                    new_path = texture_dir / new_name

                    shutil.copy2(original_path, new_path)

                    texture_info.append({
                        "name": img.name,
                        "original_path": str(original_path),
                        "packed_path": str(new_path.relative_to(self.packed_scene_dir)),
                        "relative_path": img.filepath
                    })

                    self.logger.debug(f"Packed texture: {img.name}")

        self.logger.info(f"Packed {len(texture_info)} textures")
        return texture_info

    def _pack_hdris(self):
        """Pack HDRI files from world shader nodes"""
        hdri_info = []
        hdri_dir = self.resources_dir / "hdris"
        hdri_dir.mkdir(exist_ok=True)

        # Check world shader nodes for environment textures
        if self.scene.world and self.scene.world.node_tree:
            for node in self.scene.world.node_tree.nodes:
                if node.type == 'TEX_ENVIRONMENT' and node.image:
                    img = node.image
                    if img.filepath and not img.packed_file:
                        original_path = Path(bpy.path.abspath(img.filepath))

                        if original_path.exists() and original_path.is_file():
                            new_name = FileUtils.get_unique_filename(hdri_dir, original_path.name)
                            new_path = hdri_dir / new_name

                            shutil.copy2(original_path, new_path)

                            hdri_info.append({
                                "name": img.name,
                                "original_path": str(original_path),
                                "packed_path": str(new_path.relative_to(self.packed_scene_dir)),
                                "node_name": node.name
                            })

                            self.logger.debug(f"Packed HDRI: {img.name}")

        self.logger.info(f"Packed {len(hdri_info)} HDRIs")
        return hdri_info

    def _pack_external_data(self):
        """Pack other external data like cache files, etc."""
        external_info = []

        # TODO: Add support for:
        # - Particle cache files
        # - Fluid cache files
        # - External mesh files (Alembic, etc.)
        # - External scripts

        self.logger.info(f"Packed {len(external_info)} external data files")
        return external_info

    def _extract_render_settings(self):
        """Extract important render settings"""
        render = self.scene.render

        settings = {
            # Resolution
            "resolution_x": render.resolution_x,
            "resolution_y": render.resolution_y,
            "resolution_percentage": render.resolution_percentage,

            # Frame settings
            "frame_start": self.scene.frame_start,
            "frame_end": self.scene.frame_end,
            "frame_current": self.scene.frame_current,
            "frame_step": self.scene.frame_step,

            # Render engine
            "engine": render.engine,

            # Output settings
            "filepath": render.filepath,
            "file_format": render.image_settings.file_format,
            "color_mode": render.image_settings.color_mode,
            "color_depth": render.image_settings.color_depth,

            # Sampling (Cycles specific)
            "samples": getattr(self.scene.cycles, 'samples', None),

            # Camera
            "camera": self.scene.camera.name if self.scene.camera else None,
        }

        # Add engine-specific settings
        if render.engine == 'CYCLES':
            settings.update(self._extract_cycles_settings())
        elif render.engine == 'BLENDER_EEVEE':
            settings.update(self._extract_eevee_settings())

        self.logger.info("Extracted render settings")
        return settings

    def _extract_cycles_settings(self):
        """Extract Cycles-specific settings"""
        cycles = self.scene.cycles

        return {
            "device": cycles.device,
            "feature_set": cycles.feature_set,
            "adaptive_threshold": cycles.adaptive_threshold,
            "time_limit": cycles.time_limit,
            "use_denoising": cycles.use_denoising,
        }

    def _extract_eevee_settings(self):
        """Extract EEVEE-specific settings"""
        eevee = self.scene.eevee

        return {
            "taa_render_samples": eevee.taa_render_samples,
            "use_bloom": eevee.use_bloom,
            "use_ssr": eevee.use_ssr,
            "use_motion_blur": eevee.use_motion_blur,
        }

    def _extract_scene_info(self):
        """Extract general scene information"""
        info = {
            "name": self.scene.name,
            "objects_count": len(self.scene.objects),
            "materials_count": len(bpy.data.materials),
            "textures_count": len(bpy.data.textures),
            "lights_count": len([obj for obj in self.scene.objects if obj.type == 'LIGHT']),
            "meshes_count": len([obj for obj in self.scene.objects if obj.type == 'MESH']),

            # Complexity indicators
            "total_vertices": sum(len(obj.data.vertices) for obj in self.scene.objects
                                  if obj.type == 'MESH' and obj.data),
            "total_faces": sum(len(obj.data.polygons) for obj in self.scene.objects
                               if obj.type == 'MESH' and obj.data),
        }

        self.logger.info(f"Extracted scene info: {info['objects_count']} objects, "
                         f"{info['total_vertices']} vertices")
        return info

    def get_packed_size(self):
        """Get total size of packed resources"""
        if not self.packed_scene_dir.exists():
            return 0

        total_size = 0
        for file_path in self.packed_scene_dir.rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size

        return total_size

    def cleanup_packed_scene(self):
        """Clean up packed scene directory"""
        if self.packed_scene_dir.exists():
            shutil.rmtree(self.packed_scene_dir)
            self.logger.info(f"Cleaned up packed scene: {self.packed_scene_dir}")

    @staticmethod
    def unpack_scene(packed_scene_path, target_dir):
        """
        Unpack scene resources (used by render nodes)
        """
        packed_path = Path(packed_scene_path)
        target_path = Path(target_dir)

        if not packed_path.exists():
            raise FileNotFoundError(f"Packed scene not found: {packed_path}")

        # Copy packed scene to target directory
        if target_path.exists():
            shutil.rmtree(target_path)

        shutil.copytree(packed_path, target_path)

        # Load manifest
        manifest_path = target_path / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            return manifest

        return None