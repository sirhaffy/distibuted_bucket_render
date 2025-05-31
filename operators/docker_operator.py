"""
Docker management operators for distributed rendering
"""

import bpy
from bpy.types import Operator
import subprocess
import threading
import requests


class DISTRIB_OT_check_docker_status(Operator):
    """Check if Docker containers are running"""
    bl_idname = "distrib.check_docker_status"
    bl_label = "Check Docker Status"
    bl_description = "Check if Docker containers are running"

    def execute(self, context):
        try:
            # Check if containers are running
            result = subprocess.run(['docker', 'ps', '--format', 'table {{.Names}}\t{{.Status}}'],
                                  capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                running_containers = [line for line in result.stdout.split('\n')
                                    if 'blender-render' in line and 'Up' in line]

                if running_containers:
                    context.scene.distributed_render_docker_status = f"{len(running_containers)} containers running"
                    self.report({'INFO'}, f"Found {len(running_containers)} running containers")
                else:
                    context.scene.distributed_render_docker_status = "No containers running"
                    self.report({'WARNING'}, "No Docker containers running")
            else:
                context.scene.distributed_render_docker_status = "Docker not available"
                self.report({'ERROR'}, "Docker not available")

        except Exception as e:
            context.scene.distributed_render_docker_status = f"Error: {str(e)}"
            self.report({'ERROR'}, f"Error checking Docker: {e}")

        return {'FINISHED'}


class DISTRIB_OT_start_docker_containers(Operator):
    """Start Docker containers for rendering"""
    bl_idname = "distrib.start_docker_containers"
    bl_label = "Start Docker Containers"
    bl_description = "Start Docker containers for distributed rendering"

    def execute(self, context):
        try:
            # Start containers using docker-compose
            self.report({'INFO'}, "Starting Docker containers...")

            def start_containers():
                try:
                    result = subprocess.run(['docker-compose', 'up', '-d'],
                                          capture_output=True, text=True, timeout=60)

                    if result.returncode == 0:
                        context.scene.distributed_render_docker_status = "Containers starting..."
                    else:
                        context.scene.distributed_render_docker_status = f"Error: {result.stderr}"

                except Exception as e:
                    context.scene.distributed_render_docker_status = f"Error: {str(e)}"

            # Start in background thread
            thread = threading.Thread(target=start_containers, daemon=True)
            thread.start()

        except Exception as e:
            self.report({'ERROR'}, f"Error starting containers: {e}")

        return {'FINISHED'}


class DISTRIB_OT_test_docker_connection(Operator):
    """Test connection to Docker containers"""
    bl_idname = "distrib.test_docker_connection"
    bl_label = "Test Docker Connection"
    bl_description = "Test HTTP connection to Docker render nodes"

    def execute(self, context):
        try:
            ports = [8080, 8081, 8082, 8083]  # Default ports from docker-compose
            working_containers = 0

            for port in ports:
                try:
                    response = requests.get(f"http://localhost:{port}/health", timeout=2)
                    if response.status_code == 200:
                        working_containers += 1
                except:
                    pass

            if working_containers > 0:
                context.scene.distributed_render_docker_status = f"{working_containers} containers responding"
                self.report({'INFO'}, f"{working_containers} containers are responding")
            else:
                context.scene.distributed_render_docker_status = "No containers responding"
                self.report({'WARNING'}, "No containers are responding to HTTP requests")

        except Exception as e:
            self.report({'ERROR'}, f"Error testing connection: {e}")

        return {'FINISHED'}


def debug_container_status():
    """Manual debug function to check container status"""
    ports = [8080, 8081, 8082, 8083]

    print("=== MANUAL CONTAINER DEBUG ===")

    for port in ports:
        print(f"\n--- Port {port} ---")

        # Check health
        try:
            response = requests.get(f"http://localhost:{port}/health", timeout=2)
            print(f"Health: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Health ERROR: {e}")

        # Check if any jobs are running
        try:
            response = requests.get(f"http://localhost:{port}/jobs", timeout=2)
            print(f"Jobs: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Jobs ERROR: {e}")

        # Check available endpoints
        try:
            response = requests.get(f"http://localhost:{port}/", timeout=2)
            print(f"Root: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Root ERROR: {e}")

        # Check logs endpoint
        try:
            response = requests.get(f"http://localhost:{port}/logs", timeout=2)
            print(f"Logs: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Logs ERROR: {e}")


class DISTRIB_OT_debug_containers(Operator):
    """Debug container status and jobs"""
    bl_idname = "distrib.debug_containers"
    bl_label = "Debug Containers"
    bl_description = "Debug container status and check for running jobs"
    bl_options = {'REGISTER'}

    def execute(self, context):
        debug_container_status()
        self.report({'INFO'}, "Container debug info printed to console")
        return {'FINISHED'}


# Registration
classes = [
    DISTRIB_OT_check_docker_status,
    DISTRIB_OT_start_docker_containers,
    DISTRIB_OT_test_docker_connection,
    DISTRIB_OT_debug_containers,  # ADDED DEBUG OPERATOR
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)