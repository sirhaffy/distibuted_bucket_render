#!/usr/bin/env python3
"""
Development script to reload the distributed render addon
FIXED VERSION - handles operator conflicts and cleanup
"""

import bpy
import sys
import os
from pathlib import Path
import importlib

# Configuration - automatically detect structure
ADDON_NAME = "distributed_render_addon"

# Try to auto-detect addon path
script_dir = Path(__file__).parent
possible_paths = [
    script_dir / ADDON_NAME,                    # Same level
    script_dir / ADDON_NAME / ADDON_NAME,       # Nested (your case)
    script_dir.parent / ADDON_NAME,             # One level up
]

ADDON_PATH = None
for path in possible_paths:
    if path.exists() and (path / "__init__.py").exists():
        ADDON_PATH = path
        break

# Fallback to your specific path if auto-detection fails
if ADDON_PATH is None:
    ADDON_PATH = Path(r"D:\Dev\Python\distributed_render_addon\distributed_render_addon")

print(f"Script location: {Path(__file__).parent}")
print(f"Detected addon path: {ADDON_PATH}")

def force_cleanup():
    """
    Force cleanup of all addon-related data
    """
    print("\n=== Force Cleanup ===")
    
    # Clear UI from any running operators
    try:
        for area in bpy.context.screen.areas:
            area.tag_redraw()
    except:
        pass
    
    # Remove scene properties that might reference old operators
    scene_props_to_remove = [
        'distributed_render_enabled',
        'distributed_render_res_x', 
        'distributed_render_res_y',
        'distributed_render_percentage',
        'distributed_render_engine',
        'distributed_render_device',
        'distributed_render_samples',
        'distributed_render_buckets_x',
        'distributed_render_buckets_y',
        'distributed_render_containers',
        'distributed_render_status',
        'distributed_render_docker_status',
        'distributed_render_progress',
    ]
    
    for prop in scene_props_to_remove:
        if hasattr(bpy.types.Scene, prop):
            try:
                delattr(bpy.types.Scene, prop)
                print(f"  - Removed scene property: {prop}")
            except:
                print(f"  - Could not remove scene property: {prop}")
    
    # Force remove any operator classes that might be stuck
    operator_classes_to_remove = [
        'RENDER_OT_distributed_render',
        'RENDER_OT_distributed_render_stop', 
        'RENDER_OT_check_docker_status',
        'RENDER_OT_start_docker_containers',
        'RENDER_OT_test_docker_connection',
        'DISTRIB_OT_start_render',
        'DISTRIB_OT_stop_render',
        'DISTRIB_OT_pack_scene',
        'DISTRIB_OT_preview_buckets',
    ]
    
    for op_class_name in operator_classes_to_remove:
        if hasattr(bpy.types, op_class_name):
            try:
                op_class = getattr(bpy.types, op_class_name)
                bpy.utils.unregister_class(op_class)
                print(f"  - Force unregistered operator: {op_class_name}")
            except:
                print(f"  - Could not unregister operator: {op_class_name}")
    
    # Force UI refresh
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except:
        pass

def reload_addon():
    """
    Reload the distributed render addon for development
    """
    
    print(f"\n=== Reloading addon: {ADDON_NAME} ===")
    
    # Check if addon path exists
    if not ADDON_PATH.exists():
        print(f"ERROR: Addon path does not exist: {ADDON_PATH}")
        print("Make sure the addon folder structure is correct")
        return False
    
    # Force cleanup first
    force_cleanup()
    
    # Disable addon if currently enabled
    if ADDON_NAME in bpy.context.preferences.addons:
        print(f"Disabling {ADDON_NAME}")
        try:
            bpy.ops.preferences.addon_disable(module=ADDON_NAME)
        except Exception as e:
            print(f"Could not disable addon: {e}")
    
    # Remove from modules if loaded - be more aggressive
    modules_to_remove = []
    for module_name in list(sys.modules.keys()):  # Create list copy to avoid dict change during iteration
        if (module_name.startswith(ADDON_NAME) or 
            module_name.startswith('distributed_render') or
            'distributed_render' in module_name):
            modules_to_remove.append(module_name)
    
    print(f"Removing {len(modules_to_remove)} cached modules...")
    for module_name in modules_to_remove:
        print(f"  - Removing module: {module_name}")
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
        except Exception as e:
            print(f"    Warning: Could not remove {module_name}: {e}")
    
    # Add addon parent path to sys.path
    addon_parent_path = str(ADDON_PATH.parent)
    if addon_parent_path not in sys.path:
        sys.path.insert(0, addon_parent_path)
        print(f"Added to sys.path: {addon_parent_path}")
    else:
        print(f"Path already in sys.path: {addon_parent_path}")
    
    # Wait a moment for cleanup
    import time
    time.sleep(0.1)
    
    # Refresh addon list
    print("Refreshing addon list...")
    try:
        bpy.ops.preferences.addon_refresh()
    except Exception as e:
        print(f"Warning: Could not refresh addon list: {e}")
    
    # Enable addon
    try:
        print(f"Enabling {ADDON_NAME}...")
        bpy.ops.preferences.addon_enable(module=ADDON_NAME)
        
        # Check if addon is properly loaded
        if ADDON_NAME in bpy.context.preferences.addons:
            print("✓ Addon successfully reloaded and enabled!")
            return True
        else:
            print("✗ Addon failed to activate")
            return False
            
    except Exception as e:
        print(f"✗ Error enabling addon: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_addon_status():
    """
    Check current status of the addon
    """
    print(f"\n--- Addon Status: {ADDON_NAME} ---")
    print(f"Addon path: {ADDON_PATH}")
    print(f"Path exists: {ADDON_PATH.exists()}")
    
    if ADDON_NAME in bpy.context.preferences.addons:
        print("Status: ENABLED ✓")
    else:
        print("Status: DISABLED ✗")
    
    # List loaded modules
    related_modules = [name for name in sys.modules if ADDON_NAME in name or 'distributed_render' in name]
    print(f"Loaded modules: {len(related_modules)}")
    for module in related_modules[:10]:
        print(f"  - {module}")
    if len(related_modules) > 10:
        print(f"  ... and {len(related_modules) - 10} more")
    
    # Check if important files exist
    important_files = [
        "__init__.py",
        "addon_preferences.py", 
        "panels/__init__.py",
        "panels/render_panel.py",
        "operators/__init__.py",
        "operators/render_operator.py"
    ]
    
    print("\nFile check:")
    for file_path in important_files:
        full_path = ADDON_PATH / file_path
        status = "✓" if full_path.exists() else "✗"
        print(f"  {status} {file_path}")
    
    # Check for operator conflicts
    print("\nOperator status:")
    operator_classes = [
        'RENDER_OT_distributed_render',
        'DISTRIB_OT_start_render',
        'RENDER_PT_distributed_render',
        'DISTRIB_PT_main_panel'
    ]
    
    for op_name in operator_classes:
        if hasattr(bpy.types, op_name):
            print(f"  ✓ {op_name} registered")
        else:
            print(f"  ✗ {op_name} not found")

def quick_test():
    """
    Quick test to see if addon is working
    """
    try:
        # Try to access addon
        addon_prefs = bpy.context.preferences.addons.get(ADDON_NAME)
        if addon_prefs:
            print("✓ Addon preferences accessible")
        else:
            print("✗ Cannot access addon preferences")
        
        # Check if scene properties exist
        scene = bpy.context.scene
        if hasattr(scene, 'distributed_render_enabled'):
            print("✓ Scene properties found")
            print(f"  - Enabled: {scene.distributed_render_enabled}")
        else:
            print("✗ Scene properties not found")
        
        # Check if operators are accessible
        try:
            # Try to find either operator version
            if hasattr(bpy.ops, 'distrib') and hasattr(bpy.ops.distrib, 'start_render'):
                print("✓ DISTRIB operators found")
            elif hasattr(bpy.ops, 'render') and hasattr(bpy.ops.render, 'distributed_render'):
                print("✓ RENDER operators found")
            else:
                print("✗ No operators found")
        except Exception as e:
            print(f"✗ Error checking operators: {e}")
            
    except Exception as e:
        print(f"✗ Error in quick test: {e}")

if __name__ == "__main__":
    # Show current status
    check_addon_status()
    
    # Reload addon
    success = reload_addon()
    
    # Show status after reload
    check_addon_status()
    
    if success:
        quick_test()
        print("\n=== Reload Complete! ===")
        print("✓ Check the 3D Viewport > N-panel > Render tab or Properties > Render for the plugin UI")
    else:
        print("\n=== Reload Failed! ===")
        print("Check the console output above for error details")
        print("\nTroubleshooting tips:")
        print("1. Make sure all Python files have correct syntax")
        print("2. Check that operator names don't conflict")
        print("3. Try restarting Blender if issues persist")