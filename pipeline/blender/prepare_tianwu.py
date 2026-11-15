"""Rebuild Tianwu neck/shoulder and sacral tissue from disclosed donors.
All coordinates are Blender X longitudinal (front=-X), Y lateral, Z up.
No paid calls. Source donors are immutable; all output goes to an explicit directory.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[2]

def smooth(x):
    x = np.clip(x, 0, 1)
    return x*x*(3-2*x)

def unit(x):
    return x/max(np.linalg.norm(x), 1e-12)

def mesh(name, points, faces):
    data = bpy.data.meshes.new(name)
    data.from_pydata(np.asarray(points).tolist(), [], [list(face) for face in faces])
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    for p in data.polygons:
        p.use_smooth = True
    return obj

def load(path):
    old = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(path), disable_bone_shape=True)
    result = [o for o in bpy.context.scene.objects if o not in old and o.type == 'MESH']
    for o in result:
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.select_all(action='DESELECT')
        o.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return result

def join(objects):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    return objects[0]

def bezier(c, t):
    a,b,d,e = c
    p=(1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t*t*d+t**3*e
    v=3*((1-t)**2*(b-a)+2*(1-t)*t*(d-b)+t*t*(e-d))
    return p, unit(v)

def tube(name, control, radii, segments=32, samples=64):
    points=[]; faces=[]
    for i,t in enumerate(np.linspace(0,1,samples)):
        p,v=bezier(np.asarray(control),t)
        u=unit(np.cross(v,[0,0,1]))
        if np.linalg.norm(u)<.1:
            u=unit(np.cross(v,[0,1,0]))
        w=np.cross(v,u)
        radius=float(np.interp(t, np.linspace(0,1,len(radii)),radii))
        for angle in np.arange(segments)*2*math.pi/segments:
            points.append(p+radius*(math.cos(angle)*u+math.sin(angle)*w))
        if i:
            for j in range(segments):
                a=(i-1)*segments+j;b=(i-1)*segments+(j+1)%segments
                c=i*segments+(j+1)%segments;d=i*segments+j
                faces.extend([[a,b,c],[a,c,d]])
    points.extend([control[0],control[-1]])
    for j in range(segments):
        faces.extend([[len(points)-2,(j+1)%segments,j],
                      [len(points)-1,(samples-1)*segments+j,(samples-1)*segments+(j+1)%segments]])
    return mesh(name,points,faces)

def body_material():
    mat=bpy.data.materials.new('Inferred_azurite_gamboge_tiger_wash')
    mat.use_nodes=True;n=mat.node_tree.nodes;l=mat.node_tree.links
    bs=n.get('Principled BSDF');bs.inputs['Roughness'].default_value=.82
    tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=5.5
    tex.inputs['Detail'].default_value=2.2;tex.inputs['Roughness'].default_value=.6
    ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.27
    ramp.color_ramp.elements[0].color=(.045,.16,.13,1)
    ramp.color_ramp.elements[1].position=.74;ramp.color_ramp.elements[1].color=(.48,.31,.065,1)
    mid=ramp.color_ramp.elements.new(.48);mid.color=(.12,.30,.22,1)
    l.new(tex.outputs['Fac'],ramp.inputs[0]);l.new(ramp.outputs['Color'],bs.inputs['Base Color'])
    return mat

def construct(a,out):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body=load(a.body)[0]
    body.name='tianwu_eight_paws_rebuilt_organic_body'
    # Lift the chest and pelvis while keeping the actual paws at ground level.
    for v in body.data.vertices:
        v.co.z += .11*float(smooth((v.co.z-.14)/.40))
    mat=body_material();body.data.materials.clear();body.data.materials.append(mat)
    parts=[body];records={'heads':[],'tails':[],'feet':[]}
    # Versioned deterministic layout, independent of an ignored frozen GLB.
    head_layout=[];tail_layout=[]
    for row in range(2):
        for col,y in enumerate([-.42,-.14,.14,.42]):
            yaw=[-24,-8,8,24][col];lean=8 if row==0 else 2
            rotation=Matrix.Rotation(-math.pi/2-math.radians(yaw),4,'Z')@Matrix.Rotation(math.radians(lean),4,'X')
            head_layout.append({'row':row,'headRotation':np.array(rotation.to_3x3()).tolist(),
                'cutTarget':[[-.96,-.65][row],y,[.8784,1.1834][row]]})
            tail_layout.append({'yaw':([-40,-14,14,40] if row==0 else [-32,-10,10,32])[col],
                'pitch':([-12,-8,-8,-12] if row==0 else [10,14,14,10])[col]})
    old={'headLayout':head_layout,'tailLayout':tail_layout}
    donor=load(a.head)[0]
    p=np.array([tuple(v.co) for v in donor.data.vertices]);lo=p.min(0);hi=p.max(0)
    origin=np.r_[(lo[:2]+hi[:2])/2,lo[2]];length=max(hi-lo)
    for v in donor.data.vertices:
        v.co=(v.co-Vector(origin))/length
    # Remove the donor bust below the source-approved .34 neck section.
    bm=bmesh.new();bm.from_mesh(donor.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-7)
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
        dist=1e-7,plane_co=(0,0,.34),plane_no=(0,0,1),clear_inner=True)
    bm.verts.index_update();bm.verts.ensure_lookup_table()
    adjacency={}
    for edge in bm.edges:
        if edge.is_boundary and all(abs(v.co.z-.34)<1e-5 for v in edge.verts):
            a0,b0=[v.index for v in edge.verts]
            adjacency.setdefault(a0,[]).append(b0);adjacency.setdefault(b0,[]).append(a0)
    ring=[min(adjacency)];previous=None
    while True:
        nxt=next(j for j in adjacency[ring[-1]] if j!=previous)
        if nxt==ring[0]:break
        previous=ring[-1];ring.append(nxt)
    bm.to_mesh(donor.data);bm.free()
    p=np.array([tuple(v.co) for v in donor.data.vertices]);ring=np.array(ring)
    center=p[ring].mean(0);offsets=.48*(p[ring,:2]-center[:2])
    angles=np.arctan2(offsets[:,1],offsets[:,0]);radius=float(np.mean(np.linalg.norm(offsets,axis=1)))
    for i,rec in enumerate(old['headLayout']):
        row=rec['row'];col=i%4;y=[-.42,-.14,.14,.42][col]
        R=np.array(rec['headRotation']);target=np.array(rec['cutTarget'])+[0,0,.11]
        root=np.array([-.29 if row==0 else .14, y*.15, .64 if row==0 else .72])
        # All basal caps lie deeply inside the chest. The exact native cut loop
        # continues into the loft, avoiding a circular cuff around the human neck.
        control=np.array([root,root+[-.25,y*.45,.09],target-R[:,2]*.19,target])
        head=bpy.data.objects.new('native_human_face_%02d'%i,donor.data.copy())
        bpy.context.collection.objects.link(head)
        for v in head.data.vertices:
            v.co=.48*(R@(np.array(v.co)-center))+target
        bm=bmesh.new();bm.from_mesh(head.data);bm.verts.ensure_lookup_table()
        native_ring=[bm.verts[int(j)] for j in ring];rings=[]
        for t in np.linspace(0,1,73)[:-1]:
            c,v=bezier(control,t);u=unit(R[:,0]-v*np.dot(R[:,0],v));w=np.cross(v,u)
            rad=float(np.interp(t,[0,.25,.6,1],[.086,.090,.072,radius]))
            blend=float(smooth((t-.70)/.30))
            section=(1-blend)*np.c_[np.cos(angles),np.sin(angles)]*rad+blend*offsets
            rings.append([bm.verts.new(c+u*xx+w*yy) for xx,yy in section])
        rings.append(native_ring)
        material_index=len(head.data.materials);head.data.materials.append(mat)
        for lower,upper in zip(rings[:-1],rings[1:]):
            for j in range(len(ring)):
                face=bm.faces.new([lower[j],lower[(j+1)%len(ring)],upper[(j+1)%len(ring)],upper[j]])
                face.material_index=material_index
        cap=bm.faces.new(list(reversed(rings[0])));cap.material_index=material_index
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(head.data);bm.free();parts.append(head)
        records['heads'].append({'name':'neck_%02d'%i,'control':control.tolist(),
            'headCenter':(target+R[:,2]*.17).tolist(),'radius':radius,
            'sourceCutCenter':center.tolist(),'headRotation':R.tolist()})
    bpy.data.objects.remove(donor,do_unlink=True)
    # Independent round roots run into the volume of the sacrum, never its edge.
    for i,rec in enumerate(old['tailLayout']):
        row=i//4;col=i%4
        root=np.array([1.40,[-.12,-.04,.04,.12][col],[.62,.78][row]])
        yaw=math.radians(rec['yaw']);pitch=math.radians(rec['pitch'])
        direction=np.array([math.cos(yaw)*math.cos(pitch),math.sin(yaw)*math.cos(pitch),math.sin(pitch)])
        control=np.array([root,root+direction*.36+[0,0,.05],
                          root+direction*.81+[0,(-1 if col<2 else 1)*.10,-.17 if row==0 else .17],
                          root+direction*1.16+[0,(-1 if col<2 else 1)*.08,.04]])
        tail=tube('round_tail_%02d'%i,control,[.080,.074,.062,.050,.033,.017,.006],40,96)
        tail.data.materials.append(mat);parts.append(tail)
        records['tails'].append({'name':'tail_%02d'%i,'control':control.tolist()})
    # Join then remesh shared tissue to remove buried caps and arbitrary old folds.
    high=join(parts);high.name='Tianwu_bake_source_disclosed_derived_anatomy'
    actual=high.copy();actual.data=high.data.copy();bpy.context.collection.objects.link(actual)
    high.hide_render=True;high.hide_set(True)
    bpy.ops.object.select_all(action='DESELECT');actual.select_set(True);bpy.context.view_layer.objects.active=actual
    remesh=actual.modifiers.new('Continuous_shoulder_leg_and_sacral_tissue','REMESH')
    remesh.mode='VOXEL';remesh.voxel_size=.0028;remesh.use_smooth_shade=True
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    # Fair only derived tissue. Native faces and paws keep the remesh silhouette.
    group=actual.vertex_groups.new(name='Derived_tissue_fairing')
    for v in actual.data.vertices:
        p=np.array(v.co)
        face_distance=min(np.linalg.norm(p-np.array(h['headCenter'])) for h in records['heads'])
        weight=float(smooth((p[2]-.16)/.14)*smooth((face_distance-.13)/.09))
        if weight>0:
            group.add([v.index],weight,'REPLACE')
    mod=actual.modifiers.new('Round_root_valleys','SMOOTH');mod.factor=.65;mod.iterations=90;mod.vertex_group=group.name
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mod=actual.modifiers.new('Runtime_surface_budget','DECIMATE');mod.ratio=.48
    bpy.ops.object.modifier_apply(modifier=mod.name)
    actual.name='Tianwu_continuous_eight_head_eight_foot_eight_tail'
    for poly in actual.data.polygons:poly.use_smooth=True
    gray=bpy.data.materials.new('Gray_review_only');gray.diffuse_color=(.36,.38,.40,1)
    actual.data.materials.clear();actual.data.materials.append(gray)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'sculpt.blend'))
    (out/'anatomy.json').write_text(json.dumps(records,indent=2))
    export(actual,out/'prepared-gray.glb')
    if not a.no_render:render(actual,out)

def export(obj,path):
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,
        export_animations=False,export_yup=True)

def render(actual,out):
    sc=bpy.context.scene;sc.render.engine='CYCLES';sc.cycles.samples=20;sc.cycles.use_denoising=True
    sc.render.resolution_x=sc.render.resolution_y=1100;sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG';sc.view_settings.view_transform='AgX'
    world=bpy.data.worlds.new('Sculpt_review_world');world.use_nodes=True
    world.node_tree.nodes['Background'].inputs[0].default_value=(.48,.51,.55,1)
    world.node_tree.nodes['Background'].inputs[1].default_value=.5;sc.world=world
    for i,(loc,power,size) in enumerate([((-3,-4,6),600,3),((3,-1,4),300,4),((1,4,5),430,3),((1,0,-3),100,4)]):
        o=bpy.data.objects.new('soft_'+str(i),bpy.data.lights.new('soft_'+str(i),'AREA'));sc.collection.objects.link(o)
        o.location=loc;o.rotation_euler=(Vector((.5,0,.8))-o.location).to_track_quat('-Z','Y').to_euler()
        o.data.energy=power;o.data.size=size
    for name,target,direction,scale in [('front',(-.3,0,.95),(-1,0,.04),2.4),
        ('side',(.8,0,.85),(0,-1,.03),4.5),('oblique',(.75,0,.85),(-.72,-1,.32),4.5),
        ('rear',(.8,0,.85),(1,0,.035),2.6),('shoulder',(-.5,0,.97),(-.4,-1,.35),1.7),
        ('sacrum',(1.64,0,.73),(1,-.8,.25),1.0),('belly',(.65,0,.5),(0,-1,-.55),3.0)]:
        cam=bpy.data.objects.new(name,bpy.data.cameras.new(name));sc.collection.objects.link(cam)
        target=Vector(target);cam.location=target+Vector(direction).normalized()*7
        cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type='ORTHO';cam.data.ortho_scale=scale;sc.camera=cam;sc.render.filepath=str(out/(name+'.png'))
        bpy.ops.render.render(write_still=True);bpy.data.objects.remove(cam,do_unlink=True)

def fair(a,out):
    bpy.ops.wm.open_mainfile(filepath=str(a.blend))
    actual=bpy.data.objects['Tianwu_continuous_eight_head_eight_foot_eight_tail']
    bpy.context.view_layer.objects.active=actual
    group=actual.vertex_groups.new(name='Anatomical_junction_rounding')
    for v in actual.data.vertices:
        x,y,z=v.co
        # Broad radius around the intersections, dying out before distal necks,
        # heads, native lower limbs and the visible thin tails.
        shoulder=float(smooth((x+.67)/.13)*smooth((.32-x)/.20)*smooth((z-.50)/.15)*smooth((1.02-z)/.14))
        sacrum=float(smooth((x-1.28)/.12)*smooth((1.93-x)/.17)*smooth((z-.42)/.13)*smooth((1.02-z)/.13))
        w=max(shoulder,sacrum)
        if w>0:group.add([v.index],w,'REPLACE')
    mod=actual.modifiers.new('Broad_local_muscular_root_fairing','SMOOTH');mod.factor=.70;mod.iterations=850;mod.vertex_group=group.name
    bpy.ops.object.modifier_apply(modifier=mod.name)
    for p in actual.data.polygons:p.use_smooth=True
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'sculpt.blend'))
    (out/'anatomy.json').write_bytes((Path(a.blend).parent/'anatomy.json').read_bytes())
    export(actual,out/'prepared-gray.glb')
    if not a.no_render:render(actual,out)

def occlusion(a,out):
    bpy.ops.wm.open_mainfile(filepath=str(a.blend))
    actual=bpy.data.objects['Tianwu_continuous_eight_head_eight_foot_eight_tail']
    source=bpy.data.objects['Tianwu_bake_source_disclosed_derived_anatomy'];source.hide_render=True;source.hide_set(True)
    material=actual.data.materials[0];nodes=material.node_tree.nodes
    base=next(n.image for n in nodes if n.type=='TEX_IMAGE' and n.image)
    pixels=np.array(base.pixels[:],dtype=np.float32).reshape(-1,4)
    ao=bpy.data.images.new('Tianwu_local_cavity_wash',width=2048,height=2048,alpha=False)
    tex=nodes.new('ShaderNodeTexImage');tex.image=ao;nodes.active=tex
    bpy.ops.object.select_all(action='DESELECT');actual.select_set(True);bpy.context.view_layer.objects.active=actual
    sc=bpy.context.scene;sc.render.engine='CYCLES';sc.cycles.samples=24;sc.render.bake.use_selected_to_active=False
    bpy.ops.object.bake(type='AO')
    values=np.array(ao.pixels[:],dtype=np.float32).reshape(-1,4)
    pixels[:,:3]*=(.16+.84*np.clip(values[:,:3],0,1))
    base.pixels.foreach_set(pixels.ravel());base.update();base.pack();nodes.remove(tex)
    export(actual,out/'prepared.glb');bpy.ops.wm.save_as_mainfile(filepath=str(out/'colored.blend'))
    render(actual,out)

def legacy_projection_bake(a,out):
    bpy.ops.wm.open_mainfile(filepath=str(a.blend))
    actual=bpy.data.objects['Tianwu_continuous_eight_head_eight_foot_eight_tail']
    source=bpy.data.objects['Tianwu_bake_source_disclosed_derived_anatomy']
    actual.hide_set(False);source.hide_set(False);source.hide_render=False
    # Blend the reused native face pigment into the newly colored neck instead
    # of baking a hard horizontal material border at the donor cut.
    for native in source.data.materials:
        if native.name.startswith('Inferred_'):continue
        n=native.node_tree.nodes;l=native.node_tree.links;bs=n.get('Principled BSDF')
        if not bs:continue
        original=bs.inputs['Base Color'].links[0].from_socket if bs.inputs['Base Color'].is_linked else None
        rgb=n.new('ShaderNodeRGB');rgb.outputs[0].default_value=bs.inputs['Base Color'].default_value
        geom=n.new('ShaderNodeNewGeometry');sep=n.new('ShaderNodeSeparateXYZ');l.new(geom.outputs['Position'],sep.inputs[0])
        upper=n.new('ShaderNodeMath');upper.operation='GREATER_THAN';upper.inputs[1].default_value=-.81;l.new(sep.outputs['X'],upper.inputs[0])
        mult=n.new('ShaderNodeMath');mult.operation='MULTIPLY_ADD';mult.inputs[1].default_value=.305;mult.inputs[2].default_value=.9884;l.new(upper.outputs[0],mult.inputs[0])
        delta=n.new('ShaderNodeMath');delta.operation='SUBTRACT';l.new(sep.outputs['Z'],delta.inputs[0]);l.new(mult.outputs[0],delta.inputs[1])
        fade=n.new('ShaderNodeMapRange');fade.interpolation_type='SMOOTHSTEP';fade.clamp=True;fade.inputs['From Min'].default_value=.015;fade.inputs['From Max'].default_value=.125;l.new(delta.outputs[0],fade.inputs['Value'])
        noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=5.5;noise.inputs['Detail'].default_value=2.2
        ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.27;ramp.color_ramp.elements[0].color=(.045,.16,.13,1)
        ramp.color_ramp.elements[1].position=.74;ramp.color_ramp.elements[1].color=(.48,.31,.065,1)
        ramp.color_ramp.elements.new(.48).color=(.12,.30,.22,1);l.new(noise.outputs['Fac'],ramp.inputs[0])
        mix=n.new('ShaderNodeMixRGB');l.new(fade.outputs[0],mix.inputs[0]);l.new(ramp.outputs['Color'],mix.inputs[1]);l.new(original or rgb.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],bs.inputs['Base Color'])
    bpy.ops.object.select_all(action='DESELECT');actual.select_set(True);bpy.context.view_layer.objects.active=actual
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.15,island_margin=.008);bpy.ops.object.mode_set(mode='OBJECT')
    material=bpy.data.materials.new('Tianwu_rebaked_azurite_gamboge_and_native_faces');material.use_nodes=True
    image=bpy.data.images.new('tianwu_colored_anatomy',width=2048,height=2048,alpha=False)
    tex=material.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    material.node_tree.nodes.active=tex
    actual.data.materials.clear();actual.data.materials.append(material)
    for poly in actual.data.polygons:poly.material_index=0
    source.select_set(True);sc=bpy.context.scene;sc.render.engine='CYCLES';sc.cycles.samples=8
    sc.render.bake.use_selected_to_active=True;sc.render.bake.cage_extrusion=.05
    sc.render.bake.max_ray_distance=.10;sc.render.bake.use_pass_direct=False;sc.render.bake.use_pass_indirect=False
    sc.render.bake.use_pass_color=True;sc.render.bake.margin=12
    bpy.ops.object.bake(type='DIFFUSE')
    material.node_tree.links.new(tex.outputs['Color'],material.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    image.pack();source.hide_render=True;source.hide_set(True)
    export(actual,out/'prepared.glb')
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'colored.blend'))
    render(actual,out)

def bake(a,out):
    """Continuous candidate point pigment, without the rejected UV atlas.
    Donor UV luminance is sampled geometrically, then neutral-warm recolored.
    The spatial warm mask is continuous across shared shoulder/neck tissue.
    No native High or preserved PBR claim is made for this reference.
    """
    from mathutils.bvhtree import BVHTree
    bpy.ops.wm.open_mainfile(filepath=str(a.blend))
    actual=bpy.data.objects['Tianwu_continuous_eight_head_eight_foot_eight_tail']
    source=bpy.data.objects['Tianwu_bake_source_disclosed_derived_anatomy']
    source.hide_render=True;source.hide_set(True);actual.hide_set(False)
    anatomy=json.loads((Path(a.blend).parent/'anatomy.json').read_text())
    donor=load(a.head)[0]
    p=np.array([tuple(v.co) for v in donor.data.vertices]);lo=p.min(0);hi=p.max(0)
    p=(p-np.r_[(lo[:2]+hi[:2])/2,lo[2]])/max(hi-lo)
    donor.data.calc_loop_triangles();triangles=list(donor.data.loop_triangles)
    tri=np.array([t.vertices[:] for t in triangles]);uv=np.array([x.uv[:] for x in donor.data.uv_layers.active.data])
    tuv=np.array([uv[list(t.loops)] for t in triangles]);tree=BVHTree.FromPolygons(p.tolist(),tri.tolist(),all_triangles=True)
    image=next(n.image for m in donor.data.materials for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and n.image.name.startswith('diffuse'))
    width,height=image.size;pixels=np.array(image.pixels[:]).reshape(height,width,4)
    q=np.array([tuple(v.co) for v in actual.data.vertices]);x,y,z=q.T
    n=np.sin(x*5.3+y*3.1+np.sin(z*4.4))+.55*np.sin(y*8.1-z*5.8+np.sin(x*2.2))
    t=smooth((n+.95)/1.9)
    colors=(1-t[:,None])*np.array([.075,.22,.16])+t[:,None]*np.array([.48,.32,.085])
    centers=np.array([h['headCenter'] for h in anatomy['heads']]);nearest=np.argmin(np.linalg.norm(q[:,None]-centers,axis=2),axis=1)
    # Max of smooth warm fields avoids hard nearest-head Voronoi boundaries
    # where the two neck rows overlap in the shared shoulder.
    warmth=np.zeros(len(q))
    for h in anatomy['heads']:
        R=np.array(h['headRotation']);target=np.array(h['control'][-1]);rel=q-target
        axial=rel@R[:,2];radial=np.linalg.norm(rel-axial[:,None]*R[:,2],axis=1)
        warmth=np.maximum(warmth,smooth((axial+.12)/.22)*smooth((.22-radial)/.07))
    warm_base=np.array([.48,.325,.215])
    colors=(1-warmth[:,None])*colors+warmth[:,None]*warm_base
    sampled=[]
    for i,h in enumerate(anatomy['heads']):
        R=np.array(h['headRotation']);target=np.array(h['control'][-1]);cut=np.array(h['sourceCutCenter'])
        rel=q-target;axis=R[:,2];axial=rel@axis;radial=np.linalg.norm(rel-axial[:,None]*axis,axis=1)
        mask=smooth((axial-.015)/.085)*smooth((.24-radial)/.06)
        for v in np.flatnonzero((nearest==i)&(mask>0)):
            point=R.T@(q[v]-target)/.48+cut
            hit,normal,idx,dist=tree.find_nearest(Vector(point))
            if hit is None:continue
            a0,b0,c0=p[tri[idx]];v0=b0-a0;v1=c0-a0;v2=np.array(hit)-a0
            d00=v0@v0;d01=v0@v1;d11=v1@v1;d20=v2@v0;d21=v2@v1
            den=max(d00*d11-d01*d01,1e-18);b=(d11*d20-d01*d21)/den;c=(d00*d21-d01*d20)/den
            st=np.array([1-b-c,b,c])@tuv[idx];xx=int(st[0]*width)%width;yy=int(st[1]*height)%height
            lum=float(pixels[yy,xx,:3]@np.array([.2126,.7152,.0722]))
            shade=.015+.985*float(np.clip((lum-.015)/.42,0,1))**1.45
            warm=np.array([.48,.325,.215])*shade
            colors[v]=(1-mask[v])*colors[v]+mask[v]*warm;sampled.append(lum)
    bpy.data.objects.remove(donor,do_unlink=True)
    rgba=np.c_[np.clip(colors,0,1),np.ones(len(q))].astype(np.float32)
    attr=actual.data.color_attributes.new(name='Continuous_pigment',type='FLOAT_COLOR',domain='POINT')
    attr.data.foreach_set('color',rgba.ravel())
    actual.data.color_attributes.active_color_index=len(actual.data.color_attributes)-1
    material=bpy.data.materials.new('Candidate_continuous_vertex_pigment');material.use_nodes=True
    actual.data.materials.clear();actual.data.materials.append(material)
    for poly in actual.data.polygons:poly.material_index=0
    nodes=material.node_tree.nodes;links=material.node_tree.links
    vertex=nodes.new('ShaderNodeVertexColor');vertex.layer_name=attr.name
    bs=nodes.get('Principled BSDF');bs.inputs['Roughness'].default_value=.85;links.new(vertex.outputs['Color'],bs.inputs['Base Color'])
    # Candidate uses explicit COLOR_0, avoiding the rejected atlas. Native High
    # source PBR remains a separate required future production stage.
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'colored.blend'))
    export(actual,out/'prepared.glb')
    (out/'anatomy.json').write_text(json.dumps(anatomy,indent=2))
    print('PIGMENT',json.dumps({'method':'continuous vertex pigment; sampled donor UV luminance recolored; no atlas','faceSamples':len(sampled),'luminancePercentiles':np.percentile(sampled,[0,10,50,90,100]).tolist()}))
    if not a.no_render:render(actual,out)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--body');ap.add_argument('--head');ap.add_argument('--layout')
    ap.add_argument('--blend');ap.add_argument('--stage',choices=['sculpt','fair','bake','occlusion','recipe'],default='sculpt')
    ap.add_argument('--output-dir');ap.add_argument('--output');ap.add_argument('--no-render',action='store_true')
    a=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    for key in ['body','head']:
        value=getattr(a,key)
        if value:setattr(a,key,str((ROOT/Path(value)).resolve()))
    if a.stage=='recipe':
        import shutil
        target=Path(a.output).resolve();out=Path(a.output_dir).resolve() if a.output_dir else target.parent/'anatomy-reference'
        out.mkdir(parents=True,exist_ok=True)
        expected={'body':'926da12651f8201b13e41923466ddfb5021bc251d2e2d94e140de43985d8271a','head':'2e778cc74cfdb032eaa2463037e1a485f6b4acfe381780f0bd482501be9ef7cc'}
        for key,sha in expected.items():assert hashlib.sha256(Path(getattr(a,key)).read_bytes()).hexdigest()==sha,('Changed declared donor',key)
        review=not a.no_render;a.no_render=True
        construct(a,out);a.blend=str(out/'sculpt.blend');fair(a,out);a.no_render=not review;bake(a,out)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(out/'prepared.glb',target)
        if target.parent!=out:shutil.copy2(out/'anatomy.json',target.parent/'anatomy.json')
        (out/'rebuild-receipt.json').write_text(json.dumps({'candidate':True,'high':False,'donors':expected,'scriptSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'stages':['sculpt','fair','continuous-point-pigment']},indent=2))
        print('EXPORTED',target)
    else:
        out=Path(a.output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
        if a.stage=='sculpt':construct(a,out)
        elif a.stage=='fair':fair(a,out)
        elif a.stage=='occlusion':occlusion(a,out)
        else:bake(a,out)
