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

    glasses=[]
    for i in range(5):
        m=mat('Old window glass '+str(i),(.88,.94,.97),.025+i*.008,0)
        p=m.node_tree.nodes.get('Principled BSDF')
        p.inputs['Transmission Weight'].default_value=1
        p.inputs['IOR'].default_value=1.48
        n=m.node_tree.nodes; links=m.node_tree.links
        tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=5;tex.inputs['Detail'].default_value=2
        bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.018
        links.new(tex.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs[0],p.inputs['Normal'])
        glasses.append(m)

    # A reflection-only card reuses the saved city image. It creates parallax in
    # the glazing without fetching tiles or altering the accepted room lighting.
    reflection=mat('Saved city reflection',(.1,.1,.1))
    n=reflection.node_tree.nodes;links=reflection.node_tree.links;n.clear()
    out=n.new('ShaderNodeOutputMaterial');em=n.new('ShaderNodeEmission');em.inputs['Strength'].default_value=.8
    image=n.new('ShaderNodeTexImage');image.image=bpy.data.images.load(str(Path(__file__).resolve().parents[1]/'media/continuous/approach-final/city-0061.png'))
    links.new(image.outputs['Color'],em.inputs['Color'])
    # Reflect only into the added upper stories. Rays from the accepted room
    # pass through, preserving its original window and interior reflections.
    geom=n.new('ShaderNodeNewGeometry');ray=n.new('ShaderNodeLightPath')
    scale=n.new('ShaderNodeVectorMath');scale.operation='SCALE'
    links.new(geom.outputs['Incoming'],scale.inputs[0]);links.new(ray.outputs['Ray Length'],scale.inputs[3])
    add=n.new('ShaderNodeVectorMath');add.operation='ADD'
    links.new(geom.outputs['Position'],add.inputs[0]);links.new(scale.outputs[0],add.inputs[1])
    xyz=n.new('ShaderNodeSeparateXYZ');links.new(add.outputs[0],xyz.inputs[0])
    upper=n.new('ShaderNodeMath');upper.operation='GREATER_THAN';upper.inputs[1].default_value=4.7;links.new(xyz.outputs['Z'],upper.inputs[0])
    transparent=n.new('ShaderNodeBsdfTransparent');mix=n.new('ShaderNodeMixShader')
    links.new(upper.outputs[0],mix.inputs[0]);links.new(transparent.outputs[0],mix.inputs[1]);links.new(em.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],out.inputs['Surface'])
    bpy.ops.mesh.primitive_plane_add(size=2,location=(0,-23,14),rotation=(math.pi/2,0,0))
    card=bpy.context.object;card.name='City reflection only';card.scale=(35,22,1);card.data.materials.append(reflection)
    card.visible_camera=False;card.visible_diffuse=False;card.visible_shadow=False;card.visible_transmission=False

    stain=mat('Sill runoff',(.07,.052,.033),1)
    n=stain.node_tree.nodes;links=stain.node_tree.links;p=n.get('Principled BSDF');out=n.get('Material Output')
    tc=n.new('ShaderNodeTexCoord');xyz=n.new('ShaderNodeSeparateXYZ');links.new(tc.outputs['Generated'],xyz.inputs[0])
    noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=7;noise.inputs['Detail'].default_value=3
    stretch=n.new('ShaderNodeVectorMath');stretch.operation='MULTIPLY';stretch.inputs[1].default_value=(4,1,.3)
    links.new(tc.outputs['Generated'],stretch.inputs[0]);links.new(stretch.outputs[0],noise.inputs[0])
    fade=n.new('ShaderNodeMath');fade.operation='MULTIPLY';links.new(xyz.outputs['Z'],fade.inputs[0]);links.new(noise.outputs['Fac'],fade.inputs[1])
    strength=n.new('ShaderNodeMath');strength.operation='MULTIPLY';strength.inputs[1].default_value=.38;links.new(fade.outputs[0],strength.inputs[0])
    clear=n.new('ShaderNodeBsdfTransparent');mix=n.new('ShaderNodeMixShader');links.new(strength.outputs[0],mix.inputs[0]);links.new(clear.outputs[0],mix.inputs[1]);links.new(p.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],out.inputs[0])

    # One coordinate space keeps brick courses aligned across piers/spandrels.
    anchor=bpy.data.objects.new('Exterior masonry coordinates',None)
    bpy.context.collection.objects.link(anchor)
    facade=brick.copy(); facade.name='Exterior aged brick'
    n=facade.node_tree.nodes; links=facade.node_tree.links
    for node in n:
        if node.type=='TEX_COORD': node.object=anchor
    bs=n.get('Principled BSDF')
    original=bs.inputs['Base Color'].links[0].from_socket
    tc=n.new('ShaderNodeTexCoord');tc.object=anchor
    stretch=n.new('ShaderNodeVectorMath');stretch.operation='MULTIPLY';stretch.inputs[1].default_value=(1.3,1.3,.12)
    links.new(tc.outputs['Object'],stretch.inputs[0])
    noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=1.6;noise.inputs['Detail'].default_value=4
    links.new(stretch.outputs[0],noise.inputs['Vector'])
    ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.24;ramp.color_ramp.elements[0].color=(.43,.40,.36,1)
    ramp.color_ramp.elements[1].position=.72;ramp.color_ramp.elements[1].color=(.92,.89,.84,1)
    links.new(noise.outputs['Fac'],ramp.inputs[0])
    mix=n.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=.6
    links.new(original,mix.inputs[1]);links.new(ramp.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],bs.inputs['Base Color'])

    # Keep the room shell intact. The upper wall has true apertures and deep reveals.
    box('Building lower stories',(0,11,-9),(14,23,14),brick)
    box('Upper rear mass',(0,12.5,13.05),(18,20,16.9),facade)
    xs=[-6.6,-3.3,0,3.3,6.6]; zs=[6,9.3,12.6,15.9,19.2]
    for lo,hi in zip([-9]+[x+.68 for x in xs], [x-.68 for x in xs]+[9]):
        box('Masonry pier',((lo+hi)/2,.98,13.05),(hi-lo,3,16.9),facade)
    for lo,hi in zip([4.6]+[z+1.02 for z in zs], [z-1.02 for z in zs]+[21.5]):
        for x in xs:
            box('Masonry spandrel',(x,.98,(lo+hi)/2),(1.36,3,hi-lo),facade)
    detail('Transition stone belt',(0,-.54,4.57),(18.1,.24,.16),stone)
    for x in [-6.15,6.15]:box('Extended side facade',(x,-.23,1.4),(1.7,.48,6.4),brick)

    for row,z in enumerate(zs):
        for col,x in enumerate(xs):
            trim=trims[rng.randrange(len(trims))]
            glass=glasses[rng.randrange(len(glasses))]
            # Dark recess, reflective inset glazing, separate rails and putty lines.
            box('Recess back',(x,1.0,z),(1.35,.08,2.02),shadow)
            box('Inset glass',(x,-.17,z),(1.18,.008,1.88),glass)
            for side in [-1,1]:
                detail('Recess jamb',(x+side*.626,-.29,z),(.09,.27,2.04),trim,.007)
                detail('Sash side',(x+side*.562,-.23,z),(.045,.07,1.9),trim,.004)
            for dz in [-.975,.975]:detail('Recess head and foot',(x,-.29,z+dz),(1.34,.27,.09),trim,.007)
            detail('Sash centre rail',(x,-.235,z-.04),(1.17,.075,.075),trim,.006)
            detail('Stone sill',(x,-.52,z-1.06),(1.57,.53,.15),stone,.025)
            detail('Lintel',(x,-.535,z+1.11),(1.54,.16,.19),stone,.012)
            # Differing partial blinds sit in front of dark panes to read at speed.
            if rng.random()<.78:
                drop=rng.uniform(.24,1.3)
                blind=blinds[rng.randrange(len(blinds))]
                box('Lowered blind',(x,.02,z+.91-drop/2),(1.1,.014,drop),blind)
                for j in range(int(drop/.065)):
                    box('Blind slat shadow',(x,.009,z+.91-j*.065),(1.09,.009,.009),trims[0])
                detail('Blind bottom rail',(x,.004,z+.91-drop),(1.11,.025,.024),trim,.003)
            if (row*5+col) in [2,6,13,19,22]:
                detail('Window AC casing',(x,-.64,z-.79),(.82,.62,.4),vent,.025)
                box('AC intake',(x,-.959,z-.79),(.71,.012,.28),iron)
                for j in range(9):box('AC grille',(x-.32+j*.08,-.974,z-.79),(.014,.018,.27),flashing)
                detail('AC support',(x,-.54,z-1.01),(.88,.64,.055),rust,.008)
            # Slightly irregular sealant under sills and drip stains.
            box('Rain streaks',(x,-.523,z-1.40),(1.46,.002,.47),stain)
            box('Sill underside',(x,-.535,z-1.155),(1.42,.024,.025),darkstone)

    # Roofing has seams, repairs and equipment with physical scale and shadows.
    box('Roof deck',(0,11,21.65),(18,23,.3),tar)
    for x in range(-8,9,2):box('Roof membrane seam',(x,11,21.806),(.025,22.5,.01),patch)
    for x,y,w,h in [(-4,5,2.3,3.1),(5,16,3.1,2.0),(1,11,1.3,4.8)]:box('Roof patch',(x,y,21.81),(w,h,.012),patch)
    for x in [-8.8,8.8]:
        box('Side parapet',(x,11,22),(.45,23,.7),facade)
        detail('Side coping',(x,11,22.39),(.57,23.1,.12),darkstone,.02)
    box('Front parapet',(0,-.35,22),(18.3,.55,.7),facade)
    detail('Parapet coping',(0,-.35,22.39),(18.45,.68,.12),darkstone,.02)
    box('Rear parapet',(0,22.25,22),(18,.45,.7),facade)
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
        detail('Drain bracket',(8.3,-.60,z),(.18,.08,.04),iron,.003)
    pipe('Rainwater downpipe',8.3,-.69,13.0,.07,17,iron)
