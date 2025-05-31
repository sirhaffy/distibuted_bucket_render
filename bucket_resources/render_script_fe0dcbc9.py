import bpy
import os

print('=== RENDER SCRIPT START ===')
scene = bpy.context.scene
render = scene.render

print(f'Scene: {scene.name}')
print(f'Camera: {scene.camera.name if scene.camera else "No camera"}')
print(f'Frame: {scene.frame_current}')

scene.frame_set(1)
print(f'Set frame to: 1')

render.resolution_x = 1920
print(f'Set resolution X: 1920')
render.resolution_y = 1080
print(f'Set resolution Y: 1080')
render.resolution_percentage = 100
print(f'Set resolution %: 100')
render.engine = 'CYCLES'
print(f'Set engine: CYCLES')

# Cycles settings
scene.cycles.samples = 128
print(f'Set samples: 128')
scene.cycles.device = 'CPU'
print(f'Set device: CPU')

# Border rendering (bucket)
render.use_border = True
render.border_min_x = 0.0
render.border_min_y = 0.5
render.border_max_x = 0.5
render.border_max_y = 1.0
render.use_crop_to_border = False
print(f'Border: (0.000,0.500) to (0.500,1.000)')


# Output settings
render.filepath = '/workspace/bucket_0002'
render.image_settings.file_format = 'PNG'
render.image_settings.color_mode = 'RGBA'
print(f'Output path: /workspace/bucket_0002')

# Verify camera
if not scene.camera:
    print('ERROR: No active camera in scene!')
    cameras = [obj for obj in scene.objects if obj.type == 'CAMERA']
    if cameras:
        scene.camera = cameras[0]
        print(f'Set camera to: {cameras[0].name}')
    else:
        print('ERROR: No cameras found in scene!')
        exit(1)

print('=== RENDER SCRIPT COMPLETE ===')
print('Scene is now configured for rendering')
