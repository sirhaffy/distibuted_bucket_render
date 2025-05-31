#!/usr/bin/env python3
"""
Render node HTTP server for distributed Blender rendering
FIXED VERSION - Consistent file naming and better output handling
"""

import os
import sys
import json
import subprocess
import threading
import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from flask import Flask, request, jsonify, send_file
import psutil
import logging
from logging.handlers import RotatingFileHandler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('render_node')


class RenderJobManager:
    """
    Manages render jobs on this node
    """

    def __init__(self):
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.completed_jobs: Dict[str, Dict[str, Any]] = {}
        self.workspace_dir = Path("/workspace")
        self.output_dir = self.workspace_dir / "bucket_output"
        self.output_dir.mkdir(exist_ok=True)

        # Blender executable path
        self.blender_exe = self._find_blender()

        # Node status
        self.node_status = "idle"  # idle, busy, error
        self.node_id = os.environ.get('HOSTNAME', str(uuid.uuid4())[:8])

        logger.info(f"RenderJobManager initialized - Node ID: {self.node_id}")
        logger.info(f"Workspace directory: {self.workspace_dir}")
        logger.info(f"Output directory: {self.output_dir}")
        logger.info(f"Blender executable: {self.blender_exe}")
        logger.info(f"Blender available: {self.blender_exe is not None}")

        # List files in workspace for debugging
        if self.workspace_dir.exists():
            logger.info("Workspace contents:")
            for item in self.workspace_dir.iterdir():
                if item.is_file():
                    logger.info(f"  FILE: {item.name} ({item.stat().st_size} bytes)")
                elif item.is_dir():
                    logger.info(f"  DIR:  {item.name}/")

    def _find_blender(self):
        """Find Blender executable"""
        possible_paths = [
            "/usr/local/bin/blender",
            "/opt/blender/blender",
            "/usr/bin/blender",
            "blender"
        ]

        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"Found Blender at: {path}")
                return path
            elif shutil.which(path):
                found_path = shutil.which(path)
                logger.info(f"Found Blender via which: {found_path}")
                return found_path

        logger.warning("Blender executable not found!")
        return None

    def start_render_job(self, job_data: Dict[str, Any]) -> str:
        """Start a new render job with consistent naming"""
        job_id = str(uuid.uuid4())

        try:
            bucket_id = job_data.get('bucket_id', 0)

            # Create consistent filename: bucket_XXXX.png (4-digit zero-padded)
            output_filename = f"bucket_{bucket_id:04d}.png"

            job_info = {
                'id': job_id,
                'bucket_id': bucket_id,
                'status': 'starting',
                'progress': 0.0,
                'start_time': time.time(),
                'blend_file': job_data.get('blend_file'),
                'frame': job_data.get('frame', 1),
                'render_settings': job_data.get('render_settings', {}),
                'output_filename': output_filename,
                'output_path': str(self.output_dir / output_filename),
                'error_message': None,
                'blender_process': None
            }

            self.active_jobs[job_id] = job_info
            self.node_status = "busy"

            # Log job details
            logger.info(f"Starting render job {job_id}:")
            logger.info(f"  Bucket ID: {bucket_id}")
            logger.info(f"  Output filename: {output_filename}")
            logger.info(f"  Blend file: {job_data.get('blend_file')}")
            logger.info(f"  Frame: {job_data.get('frame', 1)}")

            # Start render in separate thread
            render_thread = threading.Thread(
                target=self._execute_render_job,
                args=(job_id,),
                daemon=True,
                name=f"RenderJob-{job_id[:8]}"
            )
            render_thread.start()

            logger.info(f"Started render job {job_id} for bucket {bucket_id}")
            return job_id

        except Exception as e:
            logger.error(f"Error starting render job: {e}")
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]
            raise

    def _execute_render_job(self, job_id: str):
        """Execute a render job with consistent output naming"""
        job_info = self.active_jobs[job_id]

        try:
            job_info['status'] = 'rendering'
            logger.info(f"Executing render job {job_id}")

            output_path = Path(job_info['output_path'])
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Find the user's blend file
            blend_file = self._find_blend_file(job_info)

            if blend_file and self.blender_exe:
                logger.info(f"Found blend file: {blend_file}")
                logger.info(f"Will render with Blender: {self.blender_exe}")
                self._render_user_scene(job_id, job_info, blend_file, output_path)
            else:
                if not blend_file:
                    logger.warning("No blend file found - creating fallback image")
                if not self.blender_exe:
                    logger.warning("Blender not available - creating fallback image")
                self._render_fallback_image(job_id, job_info, output_path)

        except Exception as e:
            job_info['status'] = 'failed'
            job_info['error_message'] = str(e)
            job_info['end_time'] = time.time()
            logger.error(f"Job {job_id} failed: {e}")

        finally:
            # Move to completed jobs
            if job_id in self.active_jobs:
                self.completed_jobs[job_id] = self.active_jobs.pop(job_id)

            # Update node status
            if not self.active_jobs:
                self.node_status = "idle"

    def _find_blend_file(self, job_info: Dict[str, Any]) -> Optional[Path]:
        """Find the user's blend file"""
        logger.info("Searching for blend file...")

        # Try the specific blend file mentioned in job
        blend_file_name = job_info.get('blend_file', '')
        if blend_file_name:
            logger.info(f"Looking for specific blend file: {blend_file_name}")

            # Try different possible locations
            possible_locations = [
                self.workspace_dir / blend_file_name,
                self.workspace_dir / Path(blend_file_name).name,
            ]

            for location in possible_locations:
                logger.info(f"Checking: {location}")
                if location.exists() and location.suffix == '.blend':
                    logger.info(f"Found specific blend file: {location}")
                    return location

        # Search for common blend file names
        common_names = [
            "current_scene.blend",
            "scene.blend",
            "packed_scene.blend"
        ]

        for name in common_names:
            blend_path = self.workspace_dir / name
            logger.info(f"Checking common name: {blend_path}")
            if blend_path.exists():
                logger.info(f"Found blend file: {blend_path}")
                return blend_path

        # Search recursively for any .blend file
        logger.info("Searching recursively for .blend files...")
        for blend_file in self.workspace_dir.rglob("*.blend"):
            if blend_file.is_file():
                logger.info(f"Found blend file: {blend_file}")
                return blend_file

        logger.warning("No blend file found in workspace")
        return None

    def _render_user_scene(self, job_id: str, job_info: Dict[str, Any], blend_file: Path, output_path: Path):
        """Render with consistent file naming - FIXED VERSION"""
        logger.info(f"Rendering user scene: {blend_file}")

        render_settings = job_info.get('render_settings', {})
        frame = job_info.get('frame', 1)
        bucket_id = job_info.get('bucket_id', 0)

        # Generate render script with absolute output path control
        python_script = self._generate_render_script(render_settings, output_path, frame, bucket_id)
        script_path = self._write_temp_script(python_script)

        blender_cmd = [
            self.blender_exe,
            str(blend_file),
            "--background",
            "--factory-startup",
            "--enable-autoexec",
            "--python-exit-code", "1",
            "--python", str(script_path)
        ]

        logger.info(f"Executing Blender command:")
        logger.info(f"  {' '.join(blender_cmd)}")

        # Set environment to disable any GUI attempts
        env = os.environ.copy()
        env['DISPLAY'] = ''
        env['BLENDER_SYSTEM_SCRIPTS'] = '/opt/blender/4.0/scripts'
        env['BLENDER_SYSTEM_DATAFILES'] = '/opt/blender/4.0/datafiles'

        # Execute Blender
        job_info['blender_process'] = subprocess.Popen(
            blender_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.workspace_dir),
            env=env
        )

        self._monitor_blender_progress(job_id, job_info['blender_process'])

        stdout, stderr = job_info['blender_process'].communicate()

        logger.info(f"Blender finished with return code: {job_info['blender_process'].returncode}")
        logger.info(f"Blender stdout:\n{stdout}")
        if stderr:
            logger.warning(f"Blender stderr:\n{stderr}")

        if job_info['blender_process'].returncode == 0:
            # Check if our expected output file exists
            if output_path.exists():
                job_info['status'] = 'complete'
                job_info['progress'] = 100.0
                job_info['end_time'] = time.time()
                job_info['final_output_path'] = str(output_path)
                logger.info(f"Job {job_id} completed successfully - output: {output_path}")
            else:
                raise RuntimeError(f"Blender completed but expected output file not found: {output_path}")
        else:
            raise RuntimeError(f"Blender render failed with code {job_info['blender_process'].returncode}: {stderr}")

        # Cleanup
        try:
            script_path.unlink()
        except:
            pass

    def _generate_render_script(self, render_settings: Dict[str, Any], output_path: Path, frame: int,
                                bucket_id: int) -> str:
        """Generate render script with absolute output path control"""

        # Use absolute path without extension - Blender will add .png
        output_base = str(output_path.with_suffix(''))

        script_lines = [
            "import bpy",
            "import os",
            "from pathlib import Path",
            "",
            "print('=== RENDER SCRIPT START ===')",
            "scene = bpy.context.scene",
            "render = scene.render",
            "",
            f"print(f'Bucket ID: {bucket_id}')",
            f"print(f'Frame: {frame}')",
            f"print(f'Target output: {output_path}')",
            ""
        ]

        # Set frame
        script_lines.extend([
            f"scene.frame_set({frame})",
            ""
        ])

        # Apply resolution settings
        if 'resolution_x' in render_settings:
            script_lines.append(f"render.resolution_x = {render_settings['resolution_x']}")
            script_lines.append(f"print(f'Set resolution X: {render_settings['resolution_x']}')")

        if 'resolution_y' in render_settings:
            script_lines.append(f"render.resolution_y = {render_settings['resolution_y']}")
            script_lines.append(f"print(f'Set resolution Y: {render_settings['resolution_y']}')")

        if 'resolution_percentage' in render_settings:
            script_lines.append(f"render.resolution_percentage = {render_settings['resolution_percentage']}")
            script_lines.append(f"print(f'Set resolution %: {render_settings['resolution_percentage']}')")

        # Set render engine
        engine = render_settings.get('engine', 'CYCLES')
        script_lines.extend([
            f"render.engine = '{engine}'",
            f"print(f'Set engine: {engine}')",
            ""
        ])

        # Engine-specific settings
        if engine == 'CYCLES':
            script_lines.append("# Cycles settings")

            if 'samples' in render_settings:
                script_lines.extend([
                    f"scene.cycles.samples = {render_settings['samples']}",
                    f"print(f'Set samples: {render_settings['samples']}')"
                ])

            device = render_settings.get('device', 'CPU')
            script_lines.extend([
                f"scene.cycles.device = '{device}'",
                f"print(f'Set device: {device}')"
            ])

        # Border rendering for buckets
        border_settings = render_settings.get('border_settings')
        if border_settings:
            script_lines.extend([
                "",
                "# Border rendering (bucket)",
                "render.use_border = True",
                f"render.border_min_x = {border_settings.get('border_min_x', 0.0)}",
                f"render.border_min_y = {border_settings.get('border_min_y', 0.0)}",
                f"render.border_max_x = {border_settings.get('border_max_x', 1.0)}",
                f"render.border_max_y = {border_settings.get('border_max_y', 1.0)}",
                "render.use_crop_to_border = False",
                f"print(f'Border: ({border_settings.get('border_min_x', 0.0):.3f},{border_settings.get('border_min_y', 0.0):.3f}) to ({border_settings.get('border_max_x', 1.0):.3f},{border_settings.get('border_max_y', 1.0):.3f})')",
                ""
            ])

        # Set output path and format - FIXED VERSION
        script_lines.extend([
            "",
            "# Output settings - ABSOLUTE PATH CONTROL",
            f"output_path = r'{output_base}'",
            "render.filepath = output_path",
            "render.image_settings.file_format = 'PNG'",
            "render.image_settings.color_mode = 'RGBA'",
            "render.use_file_extension = True",
            "render.use_render_cache = False",
            "print(f'Output path set to: {output_path}')",
            ""
        ])

        # Verify camera
        script_lines.extend([
            "# Verify camera",
            "if not scene.camera:",
            "    print('ERROR: No active camera in scene!')",
            "    cameras = [obj for obj in scene.objects if obj.type == 'CAMERA']",
            "    if cameras:",
            "        scene.camera = cameras[0]",
            "        print(f'Set camera to: {cameras[0].name}')",
            "    else:",
            "        print('ERROR: No cameras found in scene!')",
            "        exit(1)",
            ""
        ])

        # Render with absolute control
        script_lines.extend([
            "# Render with absolute output path control",
            "print('Starting render...')",
            "bpy.ops.render.render(write_still=True)",
            "",
            "# Verify output was created",
            f"expected_output = Path(r'{output_path}')",
            "if expected_output.exists():",
            "    print(f'SUCCESS: Output created at {expected_output}')",
            "    print(f'File size: {expected_output.stat().st_size} bytes')",
            "else:",
            "    print(f'ERROR: Expected output not found at {expected_output}')",
            "    # List files in output directory to debug",
            f"    output_dir = Path(r'{output_path.parent}')",
            "    if output_dir.exists():",
            "        print('Files in output directory:')",
            "        for f in output_dir.iterdir():",
            "            if f.is_file():",
            "                print(f'  {f.name} ({f.stat().st_size} bytes)')",
            "    exit(1)",
            "",
            "print('=== RENDER SCRIPT COMPLETE ===')",
            ""
        ])

        return "\n".join(script_lines)

    def _render_fallback_image(self, job_id: str, job_info: Dict[str, Any], output_path: Path):
        """Create a fallback image when Blender/scene is not available"""
        logger.info(f"Creating fallback image for job {job_id}")

        try:
            from PIL import Image, ImageDraw, ImageFont

            # Get render settings
            render_settings = job_info.get('render_settings', {})
            width = render_settings.get('resolution_x', 512)
            height = render_settings.get('resolution_y', 512)

            # Create fallback image
            image = Image.new('RGB', (width, height), color=(120, 50, 50))  # Dark red
            draw = ImageDraw.Draw(image)

            # Draw border
            draw.rectangle([10, 10, width - 10, height - 10],
                           outline=(255, 255, 255), width=3)

            # Add text
            try:
                font = ImageFont.truetype("arial.ttf", min(24, width // 20))
            except:
                font = ImageFont.load_default()

            text_lines = [
                "FALLBACK RENDER",
                f"Job: {job_id[:8]}",
                f"Bucket: {job_info.get('bucket_id', 'N/A')}",
                f"Node: {self.node_id}",
                "",
                "Blend file not found",
                "or Blender not available"
            ]

            y_offset = height // 2 - len(text_lines) * 15
            for line in text_lines:
                if line:  # Skip empty lines
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_width = bbox[2] - bbox[0]
                    x_pos = (width - text_width) // 2
                    draw.text((x_pos, y_offset), line, fill=(255, 255, 255), font=font)
                y_offset += 30

            # Save image
            image.save(output_path)

            job_info['status'] = 'complete'
            job_info['progress'] = 100.0
            job_info['end_time'] = time.time()
            job_info['final_output_path'] = str(output_path)

            logger.info(f"Fallback image created: {output_path}")

        except Exception as e:
            raise RuntimeError(f"Failed to create fallback image: {e}")

    def _write_temp_script(self, script_content: str) -> Path:
        """Write temporary Python script"""
        script_path = self.workspace_dir / f"render_script_{uuid.uuid4().hex[:8]}.py"
        with open(script_path, 'w') as f:
            f.write(script_content)
        logger.info(f"Wrote render script: {script_path}")
        return script_path

    def _monitor_blender_progress(self, job_id: str, process: subprocess.Popen):
        """Monitor Blender rendering progress"""
        job_info = self.active_jobs.get(job_id)
        if not job_info:
            return

        start_time = time.time()

        while process.poll() is None and job_id in self.active_jobs:
            elapsed = time.time() - start_time

            # Simple time-based progress estimation
            estimated_duration = 60  # Assume 60 seconds for render
            progress = min(90.0, (elapsed / estimated_duration) * 100)

            job_info['progress'] = progress

            if elapsed % 10 == 0:  # Log every 10 seconds
                logger.info(f"Job {job_id} progress: {progress:.1f}%")

            time.sleep(2)

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific job"""
        if job_id in self.active_jobs:
            job_data = self.active_jobs[job_id].copy()
        elif job_id in self.completed_jobs:
            job_data = self.completed_jobs[job_id].copy()
        else:
            return None

        # Remove process object from response
        if 'blender_process' in job_data:
            del job_data['blender_process']

        return job_data

    def stop_job(self, job_id: str) -> bool:
        """Stop a running job"""
        if job_id not in self.active_jobs:
            return False

        job_info = self.active_jobs[job_id]

        try:
            if 'blender_process' in job_info and job_info['blender_process']:
                process = job_info['blender_process']
                process.terminate()

                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

            job_info['status'] = 'cancelled'
            job_info['end_time'] = time.time()

            self.completed_jobs[job_id] = self.active_jobs.pop(job_id)

            if not self.active_jobs:
                self.node_status = "idle"

            logger.info(f"Stopped job {job_id}")
            return True

        except Exception as e:
            logger.error(f"Error stopping job {job_id}: {e}")
            return False

    def get_node_status(self) -> Dict[str, Any]:
        """Get overall node status"""
        return {
            'node_id': self.node_id,
            'status': self.node_status,
            'active_jobs': len(self.active_jobs),
            'completed_jobs': len(self.completed_jobs),
            'system_info': {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage('/').percent
            },
            'blender_available': self.blender_exe is not None,
            'blender_path': self.blender_exe,
            'workspace_exists': self.workspace_dir.exists()
        }


# Initialize job manager
job_manager = RenderJobManager()

# Flask app setup
app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'node_id': job_manager.node_id,
        'blender_available': job_manager.blender_exe is not None,
        'workspace_exists': job_manager.workspace_dir.exists(),
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/status', methods=['GET'])
def get_status():
    return jsonify(job_manager.get_node_status())


@app.route('/render/start', methods=['POST'])
def start_render():
    try:
        job_data = request.json
        if not job_data:
            return jsonify({'error': 'No job data provided'}), 400

        logger.info(f"Received render request: {job_data}")

        job_id = job_manager.start_render_job(job_data)
        return jsonify({
            'job_id': job_id,
            'status': 'started',
            'output_filename': job_manager.active_jobs[job_id]['output_filename']
        })

    except Exception as e:
        logger.error(f"Error starting render: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/render/progress/<job_id>', methods=['GET'])
def get_render_progress(job_id):
    job_status = job_manager.get_job_status(job_id)

    if not job_status:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify({
        'job_id': job_id,
        'status': job_status['status'],
        'progress': job_status['progress'],
        'bucket_id': job_status.get('bucket_id'),
        'output_filename': job_status.get('output_filename'),
        'error_message': job_status.get('error_message')
    })


@app.route('/render/stop/<job_id>', methods=['POST'])
def stop_render(job_id):
    success = job_manager.stop_job(job_id)

    if success:
        return jsonify({'status': 'stopped'})
    else:
        return jsonify({'error': 'Job not found or could not be stopped'}), 404


@app.route('/render/result/<job_id>', methods=['GET'])
def get_render_result(job_id):
    job_status = job_manager.get_job_status(job_id)

    if not job_status:
        return jsonify({'error': 'Job not found'}), 404

    if job_status['status'] != 'complete':
        return jsonify({'error': 'Job not completed'}), 400

    output_path = job_status.get('final_output_path')
    if not output_path or not os.path.exists(output_path):
        return jsonify({'error': 'Output file not found'}), 404

    return send_file(output_path, as_attachment=True)


@app.route('/workspace/files', methods=['GET'])
def list_workspace_files():
    """Debug endpoint to list workspace files"""
    files = []
    if job_manager.workspace_dir.exists():
        for item in job_manager.workspace_dir.rglob("*"):
            if item.is_file():
                files.append({
                    'path': str(item.relative_to(job_manager.workspace_dir)),
                    'size': item.stat().st_size,
                    'modified': item.stat().st_mtime
                })
    return jsonify({'workspace_files': files})


if __name__ == '__main__':
    logger.info(f"Starting render node server - Node ID: {job_manager.node_id}")
    logger.info(f"Blender available: {job_manager.blender_exe is not None}")
    logger.info(f"Workspace directory: {job_manager.workspace_dir}")
    logger.info(f"Output directory: {job_manager.output_dir}")

    app.run(host='0.0.0.0', port=8080, debug=False)