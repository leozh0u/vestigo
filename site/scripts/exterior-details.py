"""Native exterior details. Uses existing local materials; no network access."""
import bpy
import math
import random
from pathlib import Path


def build(box, brick, ivory, iron):
    rng = random.Random(42)

    def mat(name, color, rough=.65, metal=0):
        m = bpy.data.materials.new(name)
        m.diffuse_color = (*color, 1)
        m.use_nodes = True
        p = m.node_tree.nodes.get('Principled BSDF')
        p.inputs['Base Color'].default_value = (*color, 1)
        p.inputs['Roughness'].default_value = rough
        p.inputs['Metallic'].default_value = metal
        return m

    def bevel(o, width=.015):
        m = o.modifiers.new('Worn edge radius', 'BEVEL')
        m.width = width
        m.segments = 2
        o.modifiers.new('Surface normals', 'WEIGHTED_NORMAL')
        return o

    def detail(name, loc, size, material, radius=.012):
        return bevel(box(name, loc, size, material), radius)

    def pipe(name, x, y, z, radius, height, material):
        bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=radius, depth=height, location=(x,y,z))
        o=bpy.context.object; o.name=name; o.data.materials.append(material)
        return bevel(o, .008)

    stone=mat('Weathered limestone',(.30,.285,.25),.85)
    darkstone=mat('Soot-darkened coping',(.11,.105,.095),.9)
    flashing=mat('Oxidized zinc flashing',(.23,.255,.26),.42,.62)
    tar=mat('Roof membrane',(.075,.077,.072),.94)
    # Fine aggregate and broad damp patches keep the roof from reading as plastic.
    n=tar.node_tree.nodes; links=tar.node_tree.links; p=n.get('Principled BSDF')
    tc=n.new('ShaderNodeTexCoord')
    noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=2.8;noise.inputs['Detail'].default_value=5
    links.new(tc.outputs['Object'],noise.inputs['Vector'])
    ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.033,.035,.032,1);ramp.color_ramp.elements[1].color=(.14,.145,.13,1)
    links.new(noise.outputs['Fac'],ramp.inputs[0]);links.new(ramp.outputs[0],p.inputs['Base Color'])
    fine=n.new('ShaderNodeTexNoise');fine.inputs['Scale'].default_value=130
    links.new(tc.outputs['Object'],fine.inputs['Vector'])
    bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.3;bump.inputs['Distance'].default_value=.015
    links.new(fine.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs[0],p.inputs['Normal'])
    patch=mat('Roof repairs',(.045,.048,.047),.97)
    vent=mat('Aged galvanized equipment',(.28,.295,.29),.5,.5)
    rust=mat('Oxidized metal',(.12,.055,.026),.88,.18)
    shadow=mat('Interior shadow',(.015,.013,.011),1)
    blinds=[mat('Faded blind '+str(i),c,.91) for i,c in enumerate([(.32,.29,.22),(.45,.42,.33),(.17,.21,.22),(.25,.235,.21)])]
    trims=[mat('Window paint '+str(i),c,.64) for i,c in enumerate([(.31,.30,.26),(.52,.49,.42),(.18,.20,.19),(.38,.36,.31)])]
    for material in trims+[stone]:
        n=material.node_tree.nodes;links=material.node_tree.links;p=n.get('Principled BSDF')
        base=tuple(p.inputs['Base Color'].default_value)
        noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=28;noise.inputs['Detail'].default_value=3
        ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.32;ramp.color_ramp.elements[0].color=tuple(c*.48 for c in base[:3])+(1,)
        ramp.color_ramp.elements[1].position=.65;ramp.color_ramp.elements[1].color=base
        links.new(noise.outputs['Fac'],ramp.inputs[0]);links.new(ramp.outputs[0],p.inputs['Base Color'])
        bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.2;bump.inputs['Distance'].default_value=.004
        links.new(noise.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs[0],p.inputs['Normal'])

    # Authored CC0 architectural modules retain their UVs, mouldings and worn paint.
    # All masonry uses one world coordinate frame so mortar courses line up.
    anchor=bpy.data.objects.new('Exterior masonry coordinates',None)
    bpy.context.collection.objects.link(anchor)
    anchor.rotation_euler=(0,0,0)
    facade=brick.copy();facade.name='Continuous facade brick'
    for node in facade.node_tree.nodes:
        if node.type=='TEX_COORD':node.object=anchor
    n=facade.node_tree.nodes; links=facade.node_tree.links
    p=n.get('Principled BSDF')
    coords=n.new('ShaderNodeTexCoord');coords.object=anchor
    split=n.new('ShaderNodeSeparateXYZ');links.new(coords.outputs['Object'],split.inputs[0])
    uv=n.new('ShaderNodeCombineXYZ');links.new(split.outputs['X'],uv.inputs['X']);links.new(split.outputs['Z'],uv.inputs['Y'])
    scale=n.new('ShaderNodeVectorMath');scale.operation='SCALE';scale.inputs[3].default_value=.72;links.new(uv.outputs[0],scale.inputs[0])
    for node in n:
        if node.type=='TEX_IMAGE':
            node.projection='FLAT';links.new(scale.outputs[0],node.inputs['Vector'])
    tex=n.new('ShaderNodeTexImage')
    tex.image=bpy.data.images.load(str(Path(__file__).resolve().parents[1]/'media/continuous/assets/red_brick_03/Displacement.jpg'))
    tex.image.colorspace_settings.name='Non-Color';tex.projection='FLAT'
    mapping=scale
    links.new(mapping.outputs[0],tex.inputs['Vector'])
    bump=n.new('ShaderNodeBump');bump.inputs['Distance'].default_value=.012;bump.inputs['Strength'].default_value=.55
    links.new(tex.outputs['Color'],bump.inputs['Height']);links.new(bump.outputs['Normal'],p.inputs['Normal'])
    for obj in bpy.data.objects:
        if obj.name.startswith('Masonry'):
            obj.data.materials.clear();obj.data.materials.append(facade)

    asset=Path(__file__).resolve().parents[1]/'media/continuous/assets/modular_urban_apartments_facade'
    names=['wall_window_centered_small_01','window_centered_small_01',
           'wall_window_centered_large_01','window_centered_large_01','crown_standard_standard_01']
    before=set(bpy.data.images)
    with bpy.data.libraries.load(str(asset/'modular_urban_apartments_facade_2k.blend'),link=False) as (src,dst):
        dst.objects=list(names)
    sources={obj.name:obj for obj in dst.objects}
    for image in set(bpy.data.images)-before:
        if image.source=='FILE':
            image.filepath=str(asset/'textures'/Path(image.filepath).name)
            image.reload()
    glass=mat('Architectural clear glazing',(.94,.97,.98),.075)
    g=glass.node_tree.nodes.get('Principled BSDF');g.inputs['Transmission Weight'].default_value=1;g.inputs['IOR'].default_value=1.46
    for source in sources.values():
        for i,m in enumerate(source.data.materials):
            if m.name.endswith('_plaster'):source.data.materials[i]=facade
            elif m.name.endswith('_glass'):source.data.materials[i]=glass

    def module(name,x,z):
        source=sources[name];obj=source.copy();obj.data=source.data
        obj.parent=None;obj.location=(x+1.65,-.48,z);obj.scale=(1.1,1,1.1)
        bpy.context.collection.objects.link(obj)
        return obj

    # Five bays, five upper floors, deep rooms behind the windows. The selected
    # open window below remains aligned with the continuous camera flight.
    box('Building lower stories',(0,11,-9),(16.5,23,14),facade)
    box('Upper rear mass',(0,13.2,12.85),(16.5,18.6,16.5),facade)
    for side in [-1,1]:
        box('Building return',(side*8.14,11,12.85),(.22,23,16.5),facade)
        box('Lower facade extension',(side*6.76,-.23,1.4),(2.98,.48,6.4),facade)
    xs=[-6.6,-3.3,0,3.3,6.6]
    for row in range(5):
        base=4.6+row*3.3
        for col,x in enumerate(xs):
            variant='large' if col in (0,4) else 'small'
            wall=module('wall_window_centered_'+variant+'_01',x,base)
            solid=wall.modifiers.new('Masonry reveal depth','SOLIDIFY');solid.thickness=.24;solid.offset=-1
            module('window_centered_'+variant+'_01',x,base)
            width=2.05*1.1 if variant=='large' else 1.05*1.1
            box('Apartment recess',(x,2.1,base+1.26),(width,.15,2.55),shadow)
            for side in [-1,1]:box('Window interior reveal',(x+side*(width/2+.015),.85,base+1.28),(.04,2.6,2.56),shadow)
            box('Recess ceiling',(x,.9,base+2.57),(width,2.7,.05),shadow)
            if rng.random()<.82:
                drop=rng.uniform(.35,1.7)
                blind=blinds[rng.randrange(len(blinds))]
                box('Apartment blind',(x,.15,base+2.35-drop/2),(width-.1,.018,drop),blind)
                for j in range(int(drop/.07)):
                    box('Blind slat',(x,.133,base+2.35-j*.07),(width-.11,.018,.014),trims[0])
            detail('Stone window sill',(x,-.51,base-.035),(width+.22,.53,.13),stone,.02)
    for x in xs:module('crown_standard_standard_01',x,21.1)
    for source in sources.values():bpy.data.objects.remove(source,do_unlink=True)

    # Stable lighting for both approach and room. The interior fill is physically
    # inside the opening, aimed inward, so it cannot paint a hotspot on the facade.
    from mathutils import Vector
    key=bpy.data.objects['Soft daylight through the open sash']
    key.data.animation_data_clear();key.location=(0,.16,2.55)
    key.data.energy=65;key.data.size=1.2;key.data.shape='DISK'
    key.rotation_euler=(Vector((0,3.4,1.0))-key.location).to_track_quat('-Z','Y').to_euler()
    key.data.color=(.9,.94,1)
    bpy.data.objects['Late afternoon sun'].data.specular_factor=.2
    # Roofing has seams, repairs and equipment with physical scale and shadows.
    box('Roof deck',(0,11,21.65),(16.5,23,.3),tar)
    for x in range(-8,9,2):box('Roof membrane seam',(x,11,21.806),(.025,22.5,.01),patch)
    for x,y,w,h in [(-4,5,2.3,3.1),(5,16,3.1,2.0),(1,11,1.3,4.8)]:box('Roof patch',(x,y,21.81),(w,h,.012),patch)
    for x in [-8.05,8.05]:
        box('Side parapet',(x,11,22),(.45,23,.7),facade)
        detail('Side coping',(x,11,22.39),(.57,23.1,.12),darkstone,.02)
    box('Front parapet',(0,-.35,22),(16.65,.55,.7),facade)
    detail('Parapet coping',(0,-.35,22.39),(16.8,.68,.12),darkstone,.02)
    box('Rear parapet',(0,22.25,22),(16.5,.45,.7),facade)
    for x,y in [(-5.6,8),(5.3,15)]:
        detail('Roof HVAC plinth',(x,y,21.94),(2.1,2.5,.27),darkstone,.04)
        detail('Roof HVAC housing',(x,y,22.46),(1.8,2.15,.8),vent,.035)
        for j in range(7):box('HVAC louvre',(x,y-1.086,22.17+j*.086),(1.58,.018,.026),iron)
        pipe('Exhaust collar',x+.45,y,23.0,.22,.35,flashing)
        detail('Exhaust cap',(x+.45,y,23.2),(.6,.6,.06),flashing,.025)
    for x,y in [(-6,19),(6,5)]:
        detail('Chimney',(x,y,22.5),(.72,.8,1.4),facade,.02)
        detail('Chimney crown',(x,y,23.23),(.9,.98,.13),stone,.025)
        pipe('Terracotta flue',x,y,23.45,.2,.36,rust)
    for x,y in [(-7,12),(3,19),(7,9)]:
        pipe('Plumbing flashing',x,y,21.86,.28,.08,flashing)
        pipe('Plumbing stack',x,y,22.18,.07,.7,iron)
    for z in [7,11,15,19]:
        detail('Drain bracket',(7.85,-.60,z),(.18,.08,.04),iron,.003)
    pipe('Rainwater downpipe',7.85,-.69,13.0,.07,17,iron)
