"""
Panels module registration
"""

from . import render_panel

def register():
    render_panel.register()

def unregister():
    render_panel.unregister()