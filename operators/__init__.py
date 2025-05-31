"""
Operators module registration - UPDATED for separated assembly modules
"""
from . import render_operator
from . import docker_operator
from . import bucket_manager
from . import assembly_operators

def register():
    print("Registering operators...")
    render_operator.register()
    docker_operator.register()
    bucket_manager.register()
    assembly_operators.register()
    print("All operators registered")

def unregister():
    print("Unregistering operators...")
    assembly_operators.unregister()
    bucket_manager.unregister()
    docker_operator.unregister()
    render_operator.unregister()
    print("✓ All operators unregistered")