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
parser.add_argument('--out', default='approach-final')
parser.add_argument('--frames', default='1,13,25,37,49,61,73,85,97')
parser.add_argument('--width', type=int, default=1280)
parser.add_argument('--samples', type=int, default=48)
parser.add_argument('--animate', action='store_true')
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

roofmat=bpy.data.materials.new('Weathered mineral roofing')
roofmat.use_nodes=True
nodes=roofmat.node_tree.nodes; links=roofmat.node_tree.links
bs=nodes.get('Principled BSDF');bs.inputs['Roughness'].default_value=.92
noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=28
ramp=nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].color=(.09,.085,.075,1)
ramp.color_ramp.elements[1].color=(.23,.22,.20,1)
links.new(noise.outputs['Fac'],ramp.inputs['Fac']);links.new(ramp.outputs[0],bs.inputs['Base Color'])
coords=nodes.new('ShaderNodeTexCoord')
scale=nodes.new('ShaderNodeVectorMath');scale.operation='SCALE';scale.inputs[3].default_value=.25
links.new(coords.outputs['Object'],scale.inputs[0])
for kind,socket in [('Diffuse','Base Color'),('Rough','Roughness'),('nor_gl','Normal')]:
    tex=nodes.new('ShaderNodeTexImage')
    tex.image=bpy.data.images.load(str(root/'assets/worn_concrete_floor'/f'{kind}.jpg'))
    tex.projection='BOX';tex.projection_blend=.1
    links.new(scale.outputs[0],tex.inputs['Vector'])
    if kind=='nor_gl':
        tex.image.colorspace_settings.name='Non-Color'
        normal=nodes.new('ShaderNodeNormalMap');links.new(tex.outputs['Color'],normal.inputs['Color'])
        links.new(normal.outputs[0],bs.inputs[socket])
    else:
        if kind=='Rough':tex.image.colorspace_settings.name='Non-Color'
        links.new(tex.outputs['Color'],bs.inputs[socket])
# The apartment remains untouched. Additional stories lie outside its first frame.
box('Building lower stories', (0,11,-9), (14,23,14), brick)
box('Building upper roof', (0,11,21.65), (18,23,.3), roofmat)
box('Upper storeys', (0,11,13.05), (18,23,16.9), brick)
box('Facade string course',(0,-.52,4.55),(18.1,.22,.18),ivory)
box('Roof parapet', (0,-.35,22), (18.3,.55,.7), brick)
for x in [-6,6]:
    box('Roof vent',(x,8,22.1),(1.2,1.8,.8),roofmat)
    for z in [21.9,22.1,22.3]:
        box('Vent louvre',(x,7.08,z),(1.05,.05,.035),iron)
for x in [-8.8,8.8]:
    box('Side parapet',(x,11,22),(.45,23,.7),brick)
for x in [-6.15,6.15]:
    box('Extended side facade', (x,-.23,1.4), (1.7,.48,6.4),brick)
for x in [-6.6,-3.3,0,3.3,6.6]:
    for z in [-13,-9.7,-6.4,-3.1,6.0,9.3,12.6,15.9,19.2]:
        box('Neighbour window frame',(x,-.49,z),(1.25,.12,1.9),ivory)
        box('Neighbour dark glass',(x,-.56,z),(1.08,.03,1.7),iron)
        box('Neighbour sill',(x,-.60,z-.95),(1.4,.32,.12),ivory)
        box('Neighbour sash crossbar',(x,-.59,z),(1.10,.04,.055),ivory)
        box('Neighbour sash centre',(x,-.59,z),(.04,.04,1.70),ivory)

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
(out/'camera.json').write_text(json.dumps(data,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(out/'approach.blend'))
for frame in (range(1,98) if args.animate else map(int,args.frames.split(','))):
    scene.frame_set(frame)
    scene.render.filepath=str(out/f'frame-{frame:04d}.png')
    bpy.ops.render.render(write_still=True)
