"""Render the native apartment exterior over a transparent city background."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

parser = argparse.ArgumentParser()
parser.add_argument('--out', default='exterior-realism-3')
parser.add_argument('--frames', default='1,13,25,37,49,61,73,85,97')
parser.add_argument('--width', type=int, default=1280)
parser.add_argument('--samples', type=int, default=48)
parser.add_argument('--animate', action='store_true')
parser.add_argument('--reuse-invisible-from')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
root = Path(__file__).resolve().parents[1] / 'media/continuous'
out = root / args.out
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(root / 'round-3-motion/apartment.blend'))
scene = bpy.context.scene
camera = scene.camera
scene.frame_set(1)
camera.animation_data_clear()
scene.animation_data_clear()
scene.render.engine = 'CYCLES'
scene.cycles.samples = args.samples
scene.render.resolution_x = args.width
scene.render.resolution_y = round(args.width*9/16)
scene.render.use_motion_blur = False
scene.render.film_transparent=True
scene.render.image_settings.color_mode='RGBA'
scene.frame_end = 97
scene.view_settings.exposure = .2
end_loc = camera.location.copy()
end_rot = camera.rotation_euler.to_quaternion()
brick = bpy.data.materials['red_brick_03']
ivory = bpy.data.materials['Warm painted sash']
iron = bpy.data.materials['Blackened iron']

def box(name, loc, size, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o=bpy.context.object
    o.name=name
    o.scale=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(material)
    return o

# Exterior geometry is separate from the accepted room and shared camera.
import runpy
runpy.run_path(str(Path(__file__).with_name('exterior-details.py')))['build'](box, brick, ivory, iron)

# Broad daylight on the exterior; smoothly meet the room's established fill
# as the camera reaches its window. The accepted endpoint remains unchanged.
fill = bpy.data.objects['Soft daylight through the open sash'].data
fill.animation_data_clear()
for f, energy, size in [(1, 55, 8), (78, 55, 8), (85, 105, 6.8), (97, 450, 3)]:
    fill.energy = energy
    fill.size = size
    fill.keyframe_insert(data_path='energy', frame=f)
    fill.keyframe_insert(data_path='size', frame=f)

# Match the usable aerial frame at 8.25 seconds, then meet the accepted room camera.
t=8.25/9.4
height=math.exp(math.log(3e6)+(math.log(150)-math.log(3e6))*(1-(1-t)**1.25))
u=(t-.58)/.42
tilt=u*u*(3-2*u)
pitch=-math.pi/2*(1-.6*tilt)
start=Vector((0,-14,height-16))
camera.location=start
camera.rotation_euler=Vector((0,math.cos(pitch),math.sin(pitch))).to_track_quat('-Z','Y').to_euler()
start_rot=camera.rotation_euler.to_quaternion()
bpy.context.view_layer.update()
def hermite(a,b,va,vb,t):
    return (2*t**3-3*t*t+1)*a+(t**3-2*t*t+t)*va+(-2*t**3+3*t*t)*b+(t**3-t*t)*vb

data=[]
for frame in range(1,98):
    t=(frame-1)/96
    scene.frame_set(frame)
    camera.location=(0,hermite(start.y,end_loc.y,0,9.73,t),hermite(start.z,end_loc.z,-height*2.1,-.436,t))
    k=t*t*(3-2*t)
    camera.rotation_euler=start_rot.slerp(end_rot,k).to_euler()
    camera.keyframe_insert(data_path='location',frame=frame)
    camera.keyframe_insert(data_path='rotation_euler',frame=frame)
    data.append({'frame':frame,'position':list(camera.location),'rotation':list(camera.rotation_euler), 'forward':list(camera.rotation_euler.to_quaternion()@Vector((0,0,-1))), 'up':list(camera.rotation_euler.to_quaternion()@Vector((0,1,0)))})
(out/'render-source.py').write_text(Path(__file__).read_text())
(out/'exterior-details.py').write_text(Path(__file__).with_name('exterior-details.py').read_text())
(out/'camera.json').write_text(json.dumps(data,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(out/'approach.blend'))
for frame in (range(1,98) if args.animate else map(int,args.frames.split(','))):
    scene.frame_set(frame)
    scene.render.filepath=str(out/f'frame-{frame:04d}.png')
    # Reuse an empty render only when every camera-visible object's bounding
    # box is outside the current frustum. This avoids rendering empty sky.
    if args.reuse_invisible_from:
        visible = False
        for obj in scene.objects:
            if obj.type != 'MESH' or obj.hide_render or not obj.visible_camera:
                continue
            points = [world_to_camera_view(scene, camera, obj.matrix_world @ Vector(p)) for p in obj.bound_box]
            if all(p.z > 0 for p in points) and (all(p.x < 0 for p in points) or all(p.x > 1 for p in points) or all(p.y < 0 for p in points) or all(p.y > 1 for p in points)):
                continue
            if all(p.z < 0 for p in points):
                continue
            visible = True
            break
        if not visible:
            import shutil
            source = root / args.reuse_invisible_from / f'frame-{frame:04d}.png'
            check = bpy.data.images.load(str(source), check_existing=False)
            empty = max(check.pixels[:][3::4]) == 0
            bpy.data.images.remove(check)
            if empty:
                shutil.copy2(source, scene.render.filepath)
                print(f'Reused verified empty frame {frame}', flush=True)
                continue
    bpy.ops.render.render(write_still=True)
