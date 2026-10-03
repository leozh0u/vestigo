"""Render the existing room route with the same rebuilt exterior and fixed lights."""
import argparse,json,runpy,sys
from pathlib import Path
import bpy
parser=argparse.ArgumentParser()
parser.add_argument('--out',default='exterior-rebuild-room')
parser.add_argument('--frames',default='1,36,72,144')
parser.add_argument('--animate',action='store_true')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
root=Path(__file__).resolve().parents[1]/'media/continuous'
out=root/args.out;out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(root/'round-3-motion/apartment.blend'))
scene=bpy.context.scene
scene.frame_set(1)
def box(name,loc,size,material):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
    obj=bpy.context.object;obj.name=name;obj.scale=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    obj.data.materials.append(material)
    return obj
runpy.run_path(str(Path(__file__).with_name('exterior-details.py')))['build'](box,bpy.data.materials['red_brick_03'],bpy.data.materials['Warm painted sash'],bpy.data.materials['Blackened iron'])
scene.cycles.samples=48
preferences=bpy.context.preferences.addons['cycles'].preferences
preferences.compute_device_type='METAL'
preferences.get_devices()
for device in preferences.devices:device.use=device.type=='METAL'
scene.cycles.device='GPU'
scene.render.resolution_x=1280;scene.render.resolution_y=720
scene.render.image_settings.color_mode='RGB'
(out/'camera.json').write_bytes((root/'round-3-motion/camera.json').read_bytes())
(out/'render-source.py').write_bytes(Path(__file__).read_bytes())
bpy.ops.wm.save_as_mainfile(filepath=str(out/'apartment.blend'))
for frame in (range(1,145) if args.animate else map(int,args.frames.split(','))):
    scene.frame_set(frame)
    scene.render.filepath=str(out/f'frame-{frame:04d}.png')
    bpy.ops.render.render(write_still=True)
