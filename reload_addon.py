#!/usr/bin/env python3
"""
Development script to reload the distributed render addon
Run this script in Blender's Python console during development

USAGE:
1. Save this file in your project root (same level as distributed_render_addon folder)
2. In Blender, go to Scripting workspace
3. Open this file and run it, OR
4. In Blender's Python console, type: exec(open(r"C:\path\to\your\project\reload_addon.py").read())
"""

import bpy
import sys
import os
from pathlib import Path
import importlib

ADDON_NAME = "distributed_render_addon"
ADDON_PATH = r"D:\Dev\Python\distributed_render_addon\distributed_render_addon"


def reload_addon():
    """
    Reload the distributed render addon for development
    """
    print(f"\n=== Reloading addon: {ADDON_NAME} ===")

    # Check if addon path exists
    if not ADDON_PATH.exists():
        print(f"ERROR: Addon path does not exist: {ADDON_PATH}")
        print("Make sure this script is in the same directory as 'distributed_render_addon' folder")
        return False

    # Disable addon if currently enabled
    if ADDON_NAME in bpy.context.preferences.addons:
        print(f"Disabling {ADDON_NAME}")
        try:
            bpy.ops.preferences.addon_disable(module=ADDON_NAME)
        except:
            print("Could not disable addon (might not be enabled)")

    # Remove from modules if loaded
    modules_to_remove = []
    for module_name in sys.modules:
        if module_name.startswith(ADDON_NAME):
            modules_to_remove.append(module_name)

    print(f"Removing {len(modules_to_remove)} cached modules...")
    for module_name in modules_to_remove:
        print(f"  - Removing module: {module_name}")
        del sys.modules[module_name]

    # Add addon path to sys.path if not already there
    addon_parent_path = str(PROJECT_ROOT)
    if addon_parent_path not in sys.path:
        sys.path.insert(0, addon_parent_path)
        print(f"Added to sys.path: {addon_parent_path}")
    else:
        print(f"Path already in sys.path: {addon_parent_path}")

    # Refresh addon list
    print("Refreshing addon list...")
    bpy.ops.preferences.addon_refresh()

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
        # Try to show more detailed error info
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

    # List loaded modules related to our addon
    related_modules = [name for name in sys.modules if name.startswith(ADDON_NAME)]
    print(f"Loaded modules: {len(related_modules)}")
    for module in related_modules[:10]:  # Show first 10
        print(f"  - {module}")
    if len(related_modules) > 10:
        print(f"  ... and {len(related_modules) - 10} more")

    # Check if files exist
    important_files = [
        "__init__.py",
        "addon_preferences.py",
        "panels/render_panel.py",
        "operators/render_operator.py"
    ]

    print("\nFile check:")
    for file_path in important_files:
        full_path = ADDON_PATH / file_path
        status = "✓" if full_path.exists() else "✗"
        print(f"  {status} {file_path}")


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

        # Check if panel exists
        scene = bpy.context.scene
        if hasattr(scene, 'distributed_render_enabled'):
            print("✓ Scene properties found")
        else:
            print("✗ Scene properties not found")

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
        print("✓ Check the 3D Viewport > N-panel > Render tab for the plugin UI")
    else:
        print("\n=== Reload Failed! ===")
        print("Check the console output above for error details")

# If you want to run this directly in Blender's console, uncomment the next line:
# reload_addon()