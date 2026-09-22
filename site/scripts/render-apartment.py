"""Build the connected apartment set and render camera-path proofs with Blender.

blender -b --python scripts/render-apartment.py -- --frames 1,45,90 --width 960
blender -b --python scripts/render-apartment.py -- --animate --width 1280 --samples 48

Assets: python3 scripts/fetch-scene-assets.py. All dimensions are metres.
The exterior, opening, furniture and screen share one scene and one camera.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE / "media" / "continuous"
ASSETS = ROOT / "assets"
parser = argparse.ArgumentParser()
parser.add_argument("--width", type=int, default=960)
parser.add_argument("--samples", type=int, default=32)
parser.add_argument("--frames", default="1,36,72,108,144")
parser.add_argument("--animate", action="store_true")
parser.add_argument("--out", default="round-1")
parser.add_argument("--engine", choices=["CYCLES", "BLENDER_EEVEE_NEXT"], default="CYCLES")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
OUT = ROOT / args.out
OUT.mkdir(parents=True, exist_ok=True)
random.seed(19)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = args.engine
scene.render.resolution_x = args.width
scene.render.resolution_y = round(args.width * 9 / 16)
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.fps = 24
scene.frame_start, scene.frame_end = 1, 144
scene.render.film_transparent = False
scene.render.use_file_extension = True
scene.render.use_persistent_data = True
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.5
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"
scene.view_settings.exposure = 0.7
if args.engine == "CYCLES":
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.cycles.adaptive_threshold = 0.035
    scene.cycles.max_bounces = 8
    scene.cycles.diffuse_bounces = 4
    scene.cycles.glossy_bounces = 4
    preferences = bpy.context.preferences.addons["cycles"].preferences
    preferences.compute_device_type = "METAL"
    preferences.get_devices()
    for device in preferences.devices:
        device.use = device.type == "METAL"
    scene.cycles.device = "GPU"


def material(name, rgb, rough=0.5, metal=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return m


def pbr(name, scale=1):
    m = material(name, (0.6, 0.6, 0.6))
    n, link = m.node_tree.nodes, m.node_tree.links
    coords = n.new("ShaderNodeTexCoord")
    mapping = n.new("ShaderNodeVectorMath")
    mapping.operation = "SCALE"
    mapping.inputs[3].default_value = scale
    link.new(coords.outputs["Object"], mapping.inputs[0])
    bsdf = n.get("Principled BSDF")
    for kind, socket in [("Diffuse", "Base Color"), ("Rough", "Roughness"), ("nor_gl", "Normal")]:
        f = next((ASSETS / name).glob(kind + ".*"))
        image = n.new("ShaderNodeTexImage")
        image.image = bpy.data.images.load(str(f), check_existing=True)
        image.projection = "BOX"
        image.projection_blend = 0.15
        link.new(mapping.outputs[0], image.inputs["Vector"])
        if kind != "Diffuse":
            image.image.colorspace_settings.name = "Non-Color"
        if kind == "nor_gl":
            normal = n.new("ShaderNodeNormalMap")
            normal.inputs["Strength"].default_value = 0.6
            link.new(image.outputs["Color"], normal.inputs["Color"])
            link.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
        else:
            link.new(image.outputs["Color"], bsdf.inputs[socket])
    return m


def cube(name, loc, size, mat, bevel=0.0, rotation=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if rotation:
        obj.rotation_euler = rotation
    if mat:
        obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("Soft manufactured edges", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        obj.modifiers.new("Corner normals", "WEIGHTED_NORMAL")
    return obj


def cylinder(name, loc, radius, depth, mat, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    mod = obj.modifiers.new("Rolled edge", "BEVEL")
    mod.width = min(radius / 8, 0.004)
    mod.segments = 3
    obj.modifiers.new("Normals", "WEIGHTED_NORMAL")
    return obj


def line(name, points, radius, mat):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    poly = curve.splines.new("POLY")
    poly.points.add(len(points) - 1)
    for p, xyz in zip(poly.points, points):
        p.co = (*xyz, 1)
    obj = bpy.data.objects.new(name, curve)
    scene.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def asset(name, loc, height, turn=0):
    path = ASSETS / name / f"{name}.blend"
    with bpy.data.libraries.load(str(path), link=False) as (src, dest):
        dest.objects = src.objects
    objects = [o for o in dest.objects if o]
    for obj in objects:
        scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    visible = [o for o in objects if o.type == "MESH" and not o.hide_render and not o.name.startswith("wdg_")]
    bounds = [o.matrix_world @ Vector(c) for o in visible for c in o.bound_box]
    lo = Vector([min(v[i] for v in bounds) for i in range(3)])
    hi = Vector([max(v[i] for v in bounds) for i in range(3)])
    root = bpy.data.objects.new(name + " placement", None)
    scene.collection.objects.link(root)
    for obj in objects:
        if obj.name.startswith("wdg_"):
            obj.hide_render = True
        if obj.parent not in objects:
            matrix = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = matrix
    factor = height / (hi.z - lo.z)
    root.scale = (factor,) * 3
    root.rotation_euler.z = turn
    root.location = Vector(loc) - Vector((0, 0, lo.z * factor))
    return root


def text(name, body, loc, size, mat, rotation=(math.pi / 2, 0, 0)):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.align_x = "CENTER"
    curve.size = size
    curve.extrude = 0.0001
    curve.space_character = 1.1
    obj = bpy.data.objects.new(name, curve)
    scene.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = rotation
    obj.data.materials.append(mat)
    return obj


brick = pbr("red_brick_03", 0.72)
floor = pbr("old_wood_floor", 0.55)
plaster = pbr("plastered_wall_02", 0.6)
oak = pbr("oak_veneer_01", 0.85)
ivory = material("Warm painted sash", (0.78, 0.76, 0.69), 0.6)
black = material("Blackened iron", (0.025, 0.03, 0.033), 0.38, 0.72)
aluminum = material("Space grey anodized aluminum", (0.23, 0.25, 0.27), 0.29, 0.82)
rubber = material("Soft keyboard black", (0.012, 0.014, 0.018), 0.62)
paper = material("Paper", (0.78, 0.76, 0.69), 0.86)
navy = material("Rice blue fabric", (0.009, 0.026, 0.075), 0.88)
linen = material("Linen", (0.72, 0.68, 0.57), 0.9)
ceramic = material("Porcelain", (0.8, 0.8, 0.76), 0.25)
green = material("Powder coated bottle", (0.075, 0.13, 0.1), 0.55)

# Small paint and textile variation survives close views without coarse noise.
for mat, strength, distance in [(ivory, 0.18, 0.0005), (navy, 0.22, 0.0007), (linen, 0.2, 0.0006)]:
    n, l = mat.node_tree.nodes, mat.node_tree.links
    noise = n.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 180
    bump = n.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    l.new(noise.outputs["Fac"], bump.inputs["Height"])
    l.new(bump.outputs["Normal"], n.get("Principled BSDF").inputs["Normal"])

# Room: window at y=0, desk at y=4.1, ceiling z=3.05.
cube("Oak floor", (0, 2.3, -0.09), (4.1, 4.8, 0.18), floor)
cube("Back wall", (0, 4.72, 1.55), (4.1, 0.2, 3.1), plaster)
cube("Left wall", (-2.05, 2.35, 1.55), (0.18, 4.9, 3.1), plaster)
cube("Right wall", (2.05, 2.35, 1.55), (0.18, 4.9, 3.1), plaster)
cube("Ceiling", (0, 2.35, 3.12), (4.25, 5, 0.16), ivory)
for x in [-1.95, 1.95]:
    cube("Wall skirting", (x, 2.3, 0.085), (0.04, 4.7, 0.17), ivory, 0.008)
cube("Back skirting", (0, 4.59, 0.085), (3.9, 0.04, 0.17), ivory, 0.008)

# Connected facade, including the wall around the actual open sash.
for x in [-3.0, 3.0]:
    cube("Masonry beside opening", (x, -0.23, 1.4), (4.55, 0.48, 6.4), brick, 0.018)
cube("Masonry below window", (0, -0.23, -0.4), (1.48, 0.48, 2.72), brick)
cube("Masonry above window", (0, -0.23, 3.68), (1.48, 0.48, 1.62), brick)
for x in [-0.735, 0.735]:
    cube("Window jamb", (x, -0.22, 1.95), (0.09, 0.53, 1.98), ivory, 0.008)
cube("Window sill", (0, -0.26, 0.96), (1.68, 0.74, 0.12), ivory, 0.012)
cube("Window lintel", (0, -0.30, 2.96), (1.65, 0.65, 0.15), ivory, 0.012)
cube("Raised sash lower rail", (0, -0.35, 2.25), (1.40, 0.07, 0.075), ivory, 0.006)
cube("Raised sash top rail", (0, -0.35, 2.86), (1.40, 0.07, 0.07), ivory, 0.006)
for x in [-0.685, -0.23, 0.23, 0.685]:
    cube("Sash vertical bar", (x, -0.35, 2.55), (0.036, 0.055, 0.63), ivory, 0.003)
cube("Sash horizontal bar", (0, -0.35, 2.57), (1.37, 0.055, 0.025), ivory, 0.002)
glass = material("Old window glass", (0.88, 0.96, 1.0), 0.05)
glass.node_tree.nodes.get("Principled BSDF").inputs["Transmission Weight"].default_value = 1
cube("Upper window glass", (0, -0.365, 2.55), (1.34, 0.009, 0.56), glass)

# Fire escape remains off the flight axis; a physical platform below the sill.
for x in [i * 0.12 for i in range(-11, 12)]:
    cube("Fire escape grating", (x, -1.12, 0.68), (0.018, 1.60, 0.03), black, 0.003)
for x in [-1.42, 1.42]:
    cube("Fire escape outer rail", (x, -1.15, 1.46), (0.035, 1.70, 0.035), black, 0.005)
    for y in [-1.95, -1.55, -1.15, -0.75, -0.35]:
        cube("Fire escape upright", (x, y, 1.05), (0.028, 0.028, 0.82), black, 0.003)

# Pleated curtain with depth, not a rectangular image beside the opening.
verts, faces = [], []
for iz in range(31):
    z = 0.85 + iz / 30 * 2.05
    for ix in range(31):
        x = -1.0 + ix / 30 * 0.36
        y = 0.14 + 0.07 * math.sin(ix / 30 * math.pi * 9) + 0.025 * math.sin(z * 2)
        verts.append((x, y, z))
        if iz and ix:
            i = iz * 31 + ix
            faces.append((i - 32, i - 31, i, i - 1))
mesh = bpy.data.meshes.new("Curtain folds")
mesh.from_pydata(verts, [], faces)
curtain = bpy.data.objects.new("Linen curtain", mesh)
scene.collection.objects.link(curtain)
curtain.data.materials.append(linen)
for polygon in mesh.polygons:
    polygon.use_smooth = True

# Desk, chair and actual scanned props.
cube("Desk top", (0, 4.0, 0.76), (1.64, 0.75, 0.06), oak, 0.012)
for x in [-0.73, 0.73]:
    for y in [3.72, 4.28]:
        cube("Desk leg", (x, y, 0.355), (0.055, 0.055, 0.71), oak, 0.005)
asset("painted_wooden_chair_01", (1.03, 3.05, 0), 0.91, -0.35)
asset("potted_plant_02", (-0.63, 4.15, 0.79), 0.49, 0.3)
asset("desk_lamp_arm_01", (0.61, 4.18, 0.79), 0.62, math.pi)
asset("wooden_bookshelf_worn", (-1.33, 4.26, 0), 1.82)

# Detailed upholstered daybed and scanned cushions, kept beside the flight.
asset("vintage_day_bed", (1.43, 1.55, 0), 1.10, -math.pi / 2)
asset("throw_pillows_01", (1.39, 2.13, 0.51), 0.30, -0.25)

# A loose throw falls over the near side with broad folds and fine wrinkles.
verts, faces = [], []
for iy in range(61):
    v = iy / 60
    y = 0.84 + v * 0.90
    for ix in range(81):
        u = ix / 80
        x = 0.82 + u * 1.03
        drape = max(0, (1.02 - x) / 0.20)
        z = 0.60 - 0.43 * drape + 0.026 * math.sin(24*v + 3*u) * (0.4 + drape)
        z += 0.008 * math.sin(73*u + 31*v) + 0.012 * math.sin(18*u - 21*v)
        x += 0.018 * drape * math.sin(v * 42)
        verts.append((x, y + 0.012*math.sin(u*24), z))
        if iy and ix:
            k = iy * 81 + ix
            faces.append((k-82, k-81, k, k-1))
mesh = bpy.data.meshes.new("Draped woven throw")
mesh.from_pydata(verts, [], faces)
throw = bpy.data.objects.new("Navy throw with hanging folds", mesh)
scene.collection.objects.link(throw)
throw.data.materials.append(navy)
for polygon in mesh.polygons:
    polygon.use_smooth = True
solid = throw.modifiers.new("Woven thickness", "SOLIDIFY")
solid.thickness = 0.003

# Library books retain their scanned bindings, page edges and uneven lean.
with bpy.data.libraries.load(str(ASSETS / "decorative_book_set_01" / "decorative_book_set_01.blend")) as (src, dst):
    dst.objects = src.objects
books = [o for o in dst.objects if o and o.type == "MESH" and not o.hide_render]
for book in books:
    scene.collection.objects.link(book)
bpy.context.view_layer.update()
books.sort(key=lambda o: min((o.matrix_world @ Vector(c)).x for c in o.bound_box))
row, cursor = 0, -1.82
for index, book in enumerate(books):
    if index and index % 15 == 0:
        row += 1
        cursor = -1.83 + random.uniform(0, 0.25)
    book.scale *= 0.8
    bpy.context.view_layer.update()
    bounds = [book.matrix_world @ Vector(c) for c in book.bound_box]
    lo = Vector([min(v[i] for v in bounds) for i in range(3)])
    hi = Vector([max(v[i] for v in bounds) for i in range(3)])
    if row > 5:
        book.hide_render = True
        continue
    shelf_z = [0.099, 0.346, 0.593, 0.849, 1.131, 1.466][row]
    book.location += Vector((cursor-lo.x, 4.03-lo.y, shelf_z-lo.z))
    cursor += hi.x - lo.x + random.uniform(0.001, 0.004)

# The desk uses the same photographed bindings as the shelf, laid in a loose stack.
stack_top = 0.791
for i, index in enumerate([5, 28, 40]):
    book = books[index].copy()
    book.data = books[index].data.copy()
    book.name = f"Desk book {i+1}"
    scene.collection.objects.link(book)
    book.location = (0, 0, 0)
    book.rotation_euler = (0, math.pi/2, [-0.08, 0.02, 0.12][i])
    book.scale = (1.05,)*3
    bpy.context.view_layer.update()
    bounds = [book.matrix_world @ Vector(c) for c in book.bound_box]
    lo = Vector([min(v[j] for v in bounds) for j in range(3)])
    hi = Vector([max(v[j] for v in bounds) for j in range(3)])
    book.location = Vector((0.35 + i*0.008, 3.82-i*0.009, stack_top)) - lo
    stack_top += hi.z-lo.z + 0.002

# Open notes and a pencil beside the keyboard.
for x in [-0.255, -0.164]:
    cube("Open notebook pages", (x, 3.74, 0.795), (0.090, 0.137, 0.005), paper, 0.001)
    for k in range(12):
        line("Notebook rule", [(x-0.038,3.69+k*0.008,0.798), (x+0.038,3.69+k*0.008,0.798)], 0.00015, navy)
line("Wood pencil", [(-0.31,3.74,0.80),(-0.27,3.88,0.80)],0.003,oak)
cylinder("Water bottle", (-0.42, 3.78, 0.905), 0.032, 0.23, green)
cylinder("Bottle cap", (-0.42, 3.78, 1.028), 0.033, 0.018, black)
cylinder("Mug", (0.43, 4.20, 0.84), 0.042, 0.095, ceramic)
line("Charging cable", [(0.16, 3.96, 0.8), (0.27, 4.0, 0.80), (0.62, 4.12, 0.80),
                       (0.82, 4.22, 0.74), (0.86, 4.24, 0.30)], 0.002, ivory)

# Printed cloth and poster, placed on the actual back wall.
cube("Rice banner cloth", (-0.69, 4.602, 2.16), (0.76, 0.006, 0.91), navy, 0.005)
text("Rice banner lettering", "RICE", (-0.69, 4.592, 2.27), 0.19, ivory)
text("Rice banner small type", "UNIVERSITY", (-0.69, 4.590, 2.06), 0.054, ivory)
text("Rice banner founding", "HOUSTON, TEXAS", (-0.69, 4.590, 1.96), 0.035, ivory)
cube("Fencing print", (0.39, 4.60, 2.17), (0.60, 0.007, 0.82), paper, 0.003)
text("Fencing poster title", "FENCING", (0.39, 4.589, 2.42), 0.095, navy)
text("Fencing poster subtitle", "FOIL / EPEE / SABRE", (0.39, 4.589, 1.84), 0.025, navy)
line("Printed blade one", [(0.16, 4.587, 2.02), (0.61, 4.587, 2.30)], 0.0035, navy)
line("Printed blade two", [(0.17, 4.587, 2.30), (0.60, 4.587, 2.02)], 0.0035, navy)

# Detailed CC0 laptop with its key legends, ports, hinges and worn surface.
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=str(ASSETS / "classic_laptop" / "classic_laptop.gltf"))
laptop_objects = list(set(bpy.data.objects)-before)
laptop = bpy.data.objects.new("Laptop placement", None)
scene.collection.objects.link(laptop)
for obj in laptop_objects:
    if obj.parent not in laptop_objects:
        matrix = obj.matrix_world.copy()
        obj.parent = laptop
        obj.matrix_world = matrix
laptop.scale = (0.52,)*3
laptop.location = (0, 3.98, 0.79)
# The 16:9 interface occupies a letterboxed region of the physical 4:3 panel.
for obj in laptop_objects:
    if obj.type == "MESH":
        for index, mat in enumerate(obj.data.materials):
            if mat.name == "classic_laptop_screen":
                obj.data.materials[index] = rubber
screen_width, screen_height = 0.43904*0.52, 0.43904*0.52*9/16
screen_y, screen_z = 3.98+0.206747*0.52-0.0005, 0.79+0.329625*0.52
screen_vertices = [(-screen_width/2, screen_y, screen_z-screen_height/2),
                   (screen_width/2, screen_y, screen_z-screen_height/2),
                   (screen_width/2, screen_y, screen_z+screen_height/2),
                   (-screen_width/2, screen_y, screen_z+screen_height/2)]
mesh = bpy.data.meshes.new("Display surface")
mesh.from_pydata(screen_vertices, [], [(0, 1, 2, 3)])
uv = mesh.uv_layers.new()
for loop, point in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
    loop.uv = point
display = bpy.data.objects.new("Vestigo screen", mesh)
scene.collection.objects.link(display)
screen_mat = material("Working Vestigo interface", (0.02, 0.02, 0.02))
n, link = screen_mat.node_tree.nodes, screen_mat.node_tree.links
image = n.new("ShaderNodeTexImage")
image.image = bpy.data.images.load(str(SITE / "media" / "ui.png"))
emission = n.new("ShaderNodeEmission")
emission.inputs["Strength"].default_value = 0.75
link.new(image.outputs["Color"], emission.inputs["Color"])
link.new(emission.outputs[0], n.get("Material Output").inputs["Surface"])
display.data.materials.append(screen_mat)

# Resolve asset image paths on append without depending on the working directory.
files = {f.name: f for f in ASSETS.rglob("*") if f.is_file()}
for image in bpy.data.images:
    # Texture packs reuse names such as Diffuse.jpg. Only repair unresolved
    # library-relative model paths; never remap a valid absolute texture path.
    if Path(image.filepath).is_absolute() and Path(image.filepath).is_file():
        continue
    filename = Path(image.filepath).name
    if filename in files:
        image.filepath = str(files[filename])
        image.reload()

world = bpy.data.worlds.new("Daylight outside the window")
world.use_nodes = True
scene.world = world
n, link = world.node_tree.nodes, world.node_tree.links
env = n.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load(str(ASSETS / "courtyard.hdr"))
link.new(env.outputs["Color"], n.get("Background").inputs["Color"])
n.get("Background").inputs["Strength"].default_value = 0.55
bpy.ops.object.light_add(type="AREA", location=(-1.1, -2.7, 4.2))
key = bpy.context.object
key.name = "Soft daylight through the open sash"
key.data.energy = 450
key.data.color = (1.0, 0.91, 0.79)
key.data.shape = "DISK"
key.data.size = 3.0
key.rotation_euler = (Vector((0, 3.4, 1.0)) - key.location).to_track_quat("-Z", "Y").to_euler()
# The open window supplies broad sky fill as well as direct sunlight.
bpy.ops.object.light_add(type="AREA", location=(0.0, 0.10, 1.88))
fill = bpy.context.object
fill.name = "Window sky fill"
fill.data.energy = 18
fill.data.color = (0.73, 0.83, 1.0)
fill.data.shape = "RECTANGLE"
fill.data.size, fill.data.size_y = 1.2, 1.1
fill.rotation_euler = (Vector((0, 4.0, 1.2)) - fill.location).to_track_quat("-Z", "Y").to_euler()
bpy.ops.object.light_add(type="SUN", location=(-3, -5, 8))
sun = bpy.context.object
sun.name = "Late afternoon sun"
sun.data.energy = 2.4
sun.data.angle = 0.035
sun.data.color = (1.0, 0.86, 0.66)
sun.rotation_euler = Vector((0.06, 1.0, -0.14)).to_track_quat("-Z", "Y").to_euler()

bpy.ops.object.camera_add()
camera = bpy.context.object
camera.name = "Continuous camera"
camera.data.type = "PERSP"
camera.data.lens = 36 / (2 * math.tan(math.radians(42) / 2) * (16 / 9))
camera.data.sensor_width = 36
camera.data.clip_start = 0.015
camera.data.clip_end = 1000
scene.camera = camera

# One continuous path. The desk shot never swaps photos or resets the camera.
def hermite(a, b, va, vb, t):
    return ((2*t**3-3*t**2+1)*a + (t**3-2*t**2+t)*va
            + (-2*t**3+3*t**2)*b + (t**3-t**2)*vb)


def place(frame):
    scene.frame_set(frame)
    t = (frame-1) / (scene.frame_end-1)
    # Approach travels at speed through the window, then decelerates at the desk.
    end_y = screen_y - screen_height / (2 * math.tan(math.radians(42) / 2))
    y = hermite(-5.0, end_y, 14.5, 0.35, t)
    z = hermite(1.92, screen_z, -0.65, 0, t)
    x = 0.07 * math.sin(math.pi*t) * (1-t)
    camera.location = (x, y, z)
    target = Vector((0, screen_y, screen_z + 0.27*(1-t)**2))
    camera.rotation_euler = (target-camera.location).to_track_quat("-Z", "Y").to_euler()
    adaptation = min(1, max(0, (y+0.5)/2))
    scene.view_settings.exposure = 0.2 + 0.75 * adaptation**2 * (3-2*adaptation)
    bpy.context.view_layer.update()
    corners = [world_to_camera_view(scene, camera, Vector(v)) for v in screen_vertices]
    return {"frame": frame, "seconds": (frame-1)/scene.render.fps,
            "camera": list(camera.location), "rotation": list(camera.rotation_euler),
            "lens_mm": camera.data.lens,
            "screen": [[v.x, 1-v.y] for v in corners]}


trajectory = []
for i in range(1, scene.frame_end+1):
    trajectory.append(place(i))
    camera.keyframe_insert(data_path="location", frame=i)
    camera.keyframe_insert(data_path="rotation_euler", frame=i)
    scene.view_settings.keyframe_insert(data_path="exposure", frame=i)
# Ray-test the actual scene along each camera segment before spending a render.
depsgraph = bpy.context.evaluated_depsgraph_get()
collisions = []
for previous, current in zip(trajectory, trajectory[1:]):
    a, b = Vector(previous["camera"]), Vector(current["camera"])
    delta = b-a
    hit, _, _, _, obj, _ = scene.ray_cast(depsgraph, a, delta.normalized(), distance=delta.length)
    if hit:
        collisions.append({"frame":current["frame"], "object":obj.name})
if collisions:
    raise RuntimeError(f"Camera intersects scene geometry: {collisions}")
if trajectory[-1]["camera"][1] - trajectory[0]["camera"][1] < 8:
    raise RuntimeError("Camera animation did not advance along the expected path")
expected = [(0, 1), (1, 1), (1, 0), (0, 0)]
if max(abs(a-b) for point, target in zip(trajectory[-1]["screen"], expected)
       for a, b in zip(point, target)) > 0.002:
    raise RuntimeError("Final display does not fill the rendered viewport")
source_bytes = Path(__file__).read_bytes()
(OUT / "render-source.py").write_bytes(source_bytes)
(OUT / "render-settings.json").write_text(json.dumps({
    "blender": bpy.app.version_string, "engine": args.engine,
    "samples": args.samples, "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "frames": scene.frame_end, "fps": scene.render.fps, "shutter": scene.render.motion_blur_shutter,
    "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    "asset_lock_sha256": hashlib.sha256(Path(__file__).with_name("scene-assets.json").read_bytes()).hexdigest(),
    "screen_image_sha256": hashlib.sha256((SITE / "media" / "ui.png").read_bytes()).hexdigest(),
    "camera_segment_collisions": collisions,
    "scope": "Window-to-screen proof only; city registration and live UI handoff are not implemented"
}, indent=2)+"\n")
(OUT / "camera.json").write_text(json.dumps(trajectory, indent=2))
place(1)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "apartment.blend"))
frames = range(1, scene.frame_end+1) if args.animate else [int(s) for s in args.frames.split(",")]
timings = []
for frame in frames:
    place(frame)
    scene.render.filepath = str(OUT / f"frame-{frame:04d}.png")
    start = time.time()
    bpy.ops.render.render(write_still=True)
    elapsed = time.time()-start
    timings.append({"frame":frame,"seconds":round(elapsed,2)})
    print(f"FRAME {frame}: {elapsed:.2f}s", flush=True)
    (OUT / "timings.json").write_text(json.dumps(timings, indent=2))
