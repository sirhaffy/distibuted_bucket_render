"""
Assembly Engine - Handles EXR assembly with proper View Layers
Responsible for creating final production-quality EXR files
"""

import bpy
import time
from pathlib import Path
from typing import Dict, Tuple


class AssemblyEngine:
    """
    Handles assembly of bucket renders into final EXR with all View Layers
    """

    def __init__(self, context):
        self.context = context
        self.scene = context.scene
        self.temp_scene = None
        self.loaded_images = []

    def assemble_to_exr(self, bucket_files: Dict[int, Path],
                       buckets_x: int, buckets_y: int,
                       final_width: int, final_height: int) -> bool:
        """
        Assemble buckets into final EXR with all View Layers

        Args:
            bucket_files: Dictionary of bucket_id -> file_path
            buckets_x, buckets_y: Grid dimensions
            final_width, final_height: Final image dimensions

        Returns:
            True if successful
        """
        try:
            print("=== ASSEMBLING WITH PROPER EXR RENDER LAYERS ===")

            # Create temporary scene for assembly
            if not self._create_temp_scene():
                return False

            # Load and position bucket images
            if not self._load_and_position_buckets(bucket_files, buckets_x, buckets_y):
                self._cleanup()
                return False

            # Setup EXR output settings
            output_path = self._setup_exr_output(final_width, final_height)
            if not output_path:
                self._cleanup()
                return False

            # Render the assembly
            actual_path = self._render_assembly(output_path)
            if not actual_path:
                self._cleanup()
                return False

            # Load result into original scene
            success = self._load_result_into_compositor(actual_path)

            # Cleanup
            self._cleanup()

            return success

        except Exception as e:
            print(f"Assembly engine error: {e}")
            import traceback
            traceback.print_exc()
            self._cleanup()
            return False

    def _create_temp_scene(self) -> bool:
        """Create temporary scene for assembly"""
        try:
            temp_scene_name = "DistributedRender_Assembly_Temp"

            # Remove existing temp scene if it exists
            if temp_scene_name in bpy.data.scenes:
                bpy.data.scenes.remove(bpy.data.scenes[temp_scene_name])

            # Create new scene for assembly
            self.temp_scene = bpy.data.scenes.new(temp_scene_name)
            self.temp_scene.use_nodes = True
            self.temp_scene.node_tree.nodes.clear()

            print("✓ Created temporary scene for assembly")
            return True

        except Exception as e:
            print(f"Error creating temp scene: {e}")
            return False

    def _load_and_position_buckets(self, bucket_files: Dict[int, Path],
                                  buckets_x: int, buckets_y: int) -> bool:
        """Load bucket images and position them in compositor"""
        try:
            nodes = self.temp_scene.node_tree.nodes
            links = self.temp_scene.node_tree.links

            print(f"Processing {len(bucket_files)} bucket files for EXR assembly...")

            # Load bucket images and create compositor nodes
            image_nodes = []
            self.loaded_images = []

            for bucket_id, bucket_file in bucket_files.items():
                try:
                    # Calculate bucket position in grid
                    bucket_x = bucket_id % buckets_x
                    bucket_y = bucket_id // buckets_x

                    # Load image into Blender
                    img_name = f"assembly_bucket_{bucket_id}"

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
                    norm_x = (bucket_x / (buckets_x - 1)) * 2 - 1 if buckets_x > 1 else 0
                    norm_y = -(bucket_y / (buckets_y - 1)) * 2 + 1 if buckets_y > 1 else 0

                    # Scale to bucket size
                    final_width = self.scene.distributed_render_res_x * self.scene.distributed_render_percentage / 100
                    final_height = self.scene.distributed_render_res_y * self.scene.distributed_render_percentage / 100

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

                    print(f"✓ Positioned bucket {bucket_id} at grid position ({bucket_x}, {bucket_y})")

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

            print("✓ Compositor setup complete")
            return True

        except Exception as e:
            print(f"Error setting up buckets: {e}")
            return False

    def _setup_exr_output(self, final_width: int, final_height: int) -> Path:
        """Setup EXR output settings"""
        try:
            # Set render settings for EXR with all View Layers
            self.temp_scene.render.resolution_x = final_width
            self.temp_scene.render.resolution_y = final_height
            self.temp_scene.render.resolution_percentage = 100

            # EXR settings for full data preservation
            self.temp_scene.render.image_settings.file_format = 'OPEN_EXR'
            self.temp_scene.render.image_settings.color_mode = 'RGBA'
            self.temp_scene.render.image_settings.color_depth = '32'  # 32-bit float
            self.temp_scene.render.image_settings.exr_codec = 'DWAA'  # Good compression

            # Setup output path
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            addon_dir = Path(__file__).parent.parent
            workspace_dir = addon_dir / "bucket_resources"
            workspace_dir.mkdir(exist_ok=True)

            output_filename = f"assembled_render_{timestamp}"

            # Use absolute path to force Blender to save where we want
            output_path = workspace_dir / f"{output_filename}.exr"
            absolute_output_path = output_path.resolve()

            # Set filepath WITHOUT extension - Blender will add .exr
            self.temp_scene.render.filepath = str(absolute_output_path.with_suffix(''))

            print(f"EXR output configured: {absolute_output_path}")
            print(f"Blender filepath set to: {self.temp_scene.render.filepath}")

            return absolute_output_path

        except Exception as e:
            print(f"Error setting up EXR output: {e}")
            return None

    def _render_assembly(self, expected_path: Path) -> Path:
        """Render the assembly and find the actual output file"""
        try:
            # Switch to temp scene and render
            original_scene = self.context.scene
            self.context.window.scene = self.temp_scene

            print("Rendering EXR assembly...")
            bpy.ops.render.render(write_still=True)

            # Switch back to original scene
            self.context.window.scene = original_scene

            # Check multiple possible locations where Blender might have saved the file
            workspace_dir = expected_path.parent
            filename_base = expected_path.stem

            possible_paths = [
                expected_path,  # Our intended path
                Path(self.temp_scene.render.filepath + ".exr"),  # What we set + .exr
                Path(self.temp_scene.render.filepath + "0001.exr"),  # With frame number
                workspace_dir / f"{filename_base}0001.exr",  # Frame number in our directory
                Path("C:/tmp/0001.exr"),  # Blender's temp directory
                Path(bpy.path.abspath("//")) / f"{filename_base}.exr",  # Blend file directory
            ]

            actual_output_path = None
            for path in possible_paths:
                print(f"Checking for output file: {path}")
                if path.exists():
                    actual_output_path = path
                    print(f"✓ Found EXR file at: {actual_output_path}")
                    break

            if actual_output_path:
                # Move file to our desired location if it's not already there
                final_output_path = expected_path

                if actual_output_path != final_output_path:
                    print(f"Moving file from {actual_output_path} to {final_output_path}")
                    try:
                        if final_output_path.exists():
                            final_output_path.unlink()  # Remove existing file
                        actual_output_path.rename(final_output_path)
                        actual_output_path = final_output_path
                    except Exception as e:
                        print(f"Could not move file: {e}, using original location")

                print(f"✓ EXR assembly created: {actual_output_path} ({actual_output_path.stat().st_size} bytes)")
                return actual_output_path

            else:
                print(f"✗ EXR assembly file not found in any expected location")
                self._debug_missing_file(possible_paths, workspace_dir)
                return None

        except Exception as e:
            print(f"Error rendering assembly: {e}")
            # Switch back to original scene on error
            try:
                self.context.window.scene = original_scene
            except:
                pass
            return None

    def _debug_missing_file(self, checked_paths: list, workspace_dir: Path):
        """Debug helper to show where we looked for the file"""
        print("Checked paths:")
        for path in checked_paths:
            print(f"  - {path}")

        # List what files actually exist in temp directories
        print("\nFiles in C:/tmp/:")
        try:
            for f in Path("C:/tmp/").glob("*"):
                if f.is_file():
                    print(f"  - {f.name}")
        except:
            print("  (could not access C:/tmp/)")

        print(f"\nFiles in workspace directory {workspace_dir}:")
        try:
            for f in workspace_dir.glob("*"):
                if f.is_file():
                    print(f"  - {f.name}")
        except:
            print("  (could not access workspace directory)")

    def _load_result_into_compositor(self, exr_path: Path) -> bool:
        """Load the EXR result into the original scene's compositor using existing Render Layers"""
        try:
            original_scene = self.context.scene
            timestamp = time.strftime("%Y%m%d_%H%M%S")

            # Load the EXR as the new assembly image
            assembly_img_name = f"DistributedRender_Assembly_{timestamp}"

            # Remove existing assembly image
            if assembly_img_name in bpy.data.images:
                bpy.data.images.remove(bpy.data.images[assembly_img_name])

            # Load the EXR
            assembly_img = bpy.data.images.load(str(exr_path))
            assembly_img.name = assembly_img_name

            print(f"✓ Loaded EXR assembly as: {assembly_img_name}")

            # Enable compositor in original scene if not already enabled
            if not original_scene.use_nodes:
                original_scene.use_nodes = True
                print("✓ Enabled compositor in original scene")

            comp_nodes = original_scene.node_tree.nodes

            # Try to find existing Render Layers node to connect to
            render_layers_node = None
            for node in comp_nodes:
                if node.type == 'R_LAYERS':
                    render_layers_node = node
                    print(f"✓ Found existing Render Layers node: {node.name}")
                    break

            if render_layers_node:
                # Connect to existing Render Layers setup
                self._connect_to_existing_render_layers(comp_nodes, assembly_img, render_layers_node)
            else:
                # No existing Render Layers - create standalone Image node
                self._create_standalone_image_node(comp_nodes, assembly_img)

            # Set the assembled image as the active render result
            self._set_as_active_render_result(assembly_img)

            # Switch to Compositing workspace to show the result
            try:
                self.context.window.workspace = bpy.data.workspaces['Compositing']
                print("✓ Switched to Compositing workspace")
            except:
                try:
                    self.context.window.workspace = bpy.data.workspaces['Shading']
                    print("✓ Switched to Shading workspace")
                except:
                    print("! Could not switch workspace")

            print("✓ Assembly complete!")
            print(f"✓ EXR file saved with all View Layers: {exr_path}")
            print(f"✓ Assembly available as '{assembly_img_name}' in Compositor")
            print("✓ Check Compositing workspace for the result")

            return True

        except Exception as e:
            print(f"Error loading result into compositor: {e}")
            return False

    def _connect_to_existing_render_layers(self, comp_nodes, assembly_img, render_layers_node):
        """Connect assembly to existing Render Layers setup"""
        try:
            # Remove existing assembly node if it exists
            existing_node = comp_nodes.get("DistributedRender_Assembly")
            if existing_node:
                comp_nodes.remove(existing_node)

            # Create Image node with the EXR assembly at the same location as Render Layers
            img_node = comp_nodes.new(type='CompositorNodeImage')
            img_node.image = assembly_img
            img_node.label = "Distributed Render Assembly (EXR)"
            img_node.name = "DistributedRender_Assembly"

            # Position it near the Render Layers node
            img_node.location = (render_layers_node.location.x, render_layers_node.location.y - 300)

            # Try to replace the Image output from Render Layers with our assembly
            links = comp_nodes.id_data.node_tree.links

            # Find all connections from Render Layers Image output
            image_connections = []
            for link in links:
                if (link.from_node == render_layers_node and
                    link.from_socket.name == "Image"):
                    image_connections.append((link.to_node, link.to_socket))

            # If there are existing connections, offer to use our assembly instead
            if image_connections:
                print(f"✓ Found {len(image_connections)} existing Image connections from Render Layers")

                # Create a Switch node to toggle between original render and assembly
                switch_node = comp_nodes.new(type='CompositorNodeMixRGB')
                switch_node.name = "DistributedRender_Switch"
                switch_node.label = "Assembly/Original Switch"
                switch_node.location = (render_layers_node.location.x + 300, render_layers_node.location.y - 150)
                switch_node.blend_type = 'MIX'
                switch_node.inputs['Fac'].default_value = 1.0  # Default to assembly

                # Connect both images to switch
                links.new(render_layers_node.outputs['Image'], switch_node.inputs['Color1'])  # Original
                links.new(img_node.outputs['Image'], switch_node.inputs['Color2'])  # Assembly

                # Reconnect all the original connections to go through the switch
                for to_node, to_socket in image_connections:
                    # Remove old connection
                    for link in list(links):
                        if (link.from_node == render_layers_node and
                            link.from_socket.name == "Image" and
                            link.to_node == to_node and
                            link.to_socket == to_socket):
                            links.remove(link)

                    # Create new connection through switch
                    links.new(switch_node.outputs['Image'], to_socket)

                print("✓ Created Switch node to toggle between original render and assembly")
                print("✓ Set to use assembly by default (Fac=1.0)")
                print("  Change 'Fac' to 0.0 to see original render, 1.0 for assembly")

            else:
                print("✓ No existing Image connections found, assembly available as standalone node")

        except Exception as e:
            print(f"Error connecting to existing Render Layers: {e}")
            # Fallback to standalone
            self._create_standalone_image_node(comp_nodes, assembly_img)

    def _create_standalone_image_node(self, comp_nodes, assembly_img):
        """Create standalone Image node for assembly"""
        try:
            # Remove existing assembly node if it exists
            existing_node = comp_nodes.get("DistributedRender_Assembly")
            if existing_node:
                comp_nodes.remove(existing_node)

            # Add Image node with the EXR assembly
            img_node = comp_nodes.new(type='CompositorNodeImage')
            img_node.image = assembly_img
            img_node.location = (0, 0)
            img_node.label = "Distributed Render Assembly (EXR)"
            img_node.name = "DistributedRender_Assembly"

            print(f"✓ Added EXR assembly as standalone compositor node at (0,0)")

        except Exception as e:
            print(f"Error creating standalone image node: {e}")

    def _set_as_active_render_result(self, assembly_img):
        """Set the assembly as the active render result in Image Editor"""
        try:
            # Set the assembled image as the active image in Image Editor
            for area in self.context.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'IMAGE_EDITOR':
                            space.image = assembly_img
                            space.image_user.use_cyclic = False
                            break
                    break

            print("✓ Set assembly as active image in Image Editor")

        except Exception as e:
            print(f"Error setting active render result: {e}")

    def _cleanup(self):
        """Clean up temporary resources"""
        try:
            # Remove temp scene
            if self.temp_scene and self.temp_scene.name in bpy.data.scenes:
                bpy.data.scenes.remove(self.temp_scene)
                print("✓ Cleaned up temporary scene")

            # Remove temp images
            for img in self.loaded_images:
                if img.name in bpy.data.images:
                    bpy.data.images.remove(img)

            if self.loaded_images:
                print(f"✓ Cleaned up {len(self.loaded_images)} temporary images")

            self.temp_scene = None
            self.loaded_images = []

        except Exception as e:
            print(f"Warning: Error during cleanup: {e}")