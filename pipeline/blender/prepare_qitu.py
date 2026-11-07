"""Offline HIGH crow separation: headless/tailless body, one head, one tail.
Blender --background --python prepare_qitu.py -- normalized_high.glb output_dir concept_dir
"""
import os
import sys
import math
import bpy
import bmesh
import numpy as np
from mathutils import Vector, Euler
sys.path.insert(0,os.path.dirname(__file__))
from prepare_qingniao import prepare, remodel
from turnaround import setup_render,render_views

HEAD_CUT=.76
NECK=(0,-.26,.69)
TAIL=(0,.19,.34)
HEADS=[(-.08,0,-.07,-.55), (0,-.06,.05,0), (.08,0,-.07,.55)]
TAIL_ANGLES=[-.85,-.51,-.17,.17,.51,.85]


def source(path):
    obj,original=prepare(path)
    image=next(n.image for n in obj.active_material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'diffuse' in n.image.name)
    px=np.array(image.pixels[:],dtype=np.float32).reshape(image.size[1],image.size[0],4)
    r,g,b=px[:,:,0].copy(),px[:,:,1].copy(),px[:,:,2].copy()
    value=px[:,:,:3].max(axis=2)
    shade=.65+.70*value
    px[:,:,:3]=np.array([.18,.20,.27])*shade[:,:,None]
    px[value<.08,:3]=[.015,.018,.022]
    glint=(value>.55)&(np.abs(r-g)<.10)&(np.abs(g-b)<.15)
    px[glint,:3]=[.75,.77,.70]
    image.pixels.foreach_set(px.ravel());image.pack()
    obj.name='qitu_body'
    return obj,original


def cut(obj,point,normal):
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-5)
    result=bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
        plane_co=point,plane_no=normal,clear_outer=True,clear_inner=False,dist=1e-6)
    edges=[e for e in result['geom_cut'] if isinstance(e,bmesh.types.BMEdge) and e.is_boundary]
    if edges: bmesh.ops.holes_fill(bm,edges=edges,sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data);bm.free();obj.data.update()


def duplicate(obj,name):
    part=bpy.data.objects.new(name,obj.data.copy())
    bpy.context.scene.collection.objects.link(part)
    return part


def extract(obj,original):
    head=duplicate(obj,'qitu_head')
    cut(head,(0,0,HEAD_CUT),(0,0,-1))
    # A little clipped feather debris can remain beside the skull; retain the
    # connected head/neck island, never promote those fragments to extra heads.
    bm=bmesh.new();bm.from_mesh(head.data)
    seen=set();islands=[]
    for v in bm.verts:
        if v in seen: continue
        stack=[v];seen.add(v);group=[]
        while stack:
            item=stack.pop();group.append(item)
            for e in item.link_edges:
                n=e.other_vert(item)
                if n not in seen: seen.add(n);stack.append(n)
        islands.append(group)
    largest=max(islands,key=len)
    bmesh.ops.delete(bm,geom=[v for group in islands if group is not largest for v in group],context='VERTS')
    bm.to_mesh(head.data);bm.free()
    for v in head.data.vertices:
        v.co-=Vector((0,-.29,HEAD_CUT))
        v.co.z=v.co.z*1.65 if v.co.z<.14 else v.co.z+.091
    tail=duplicate(obj,'qitu_tail')
    for v,p in zip(tail.data.vertices,original): v.co=Vector(p)
    cut(tail,(0,.24,0),(0,-1,0))
    for v in tail.data.vertices:
        x,y,z=v.co
        v.co=(x*.45,(y-.24)*1.9,(z-.34+.85*(y-.24))*.35)
    for part in [head,tail]:
        part.data.update()
        for face in part.data.polygons: face.use_smooth=True
    return head,tail


def trim_body(obj,original):
    # Remove the native tail before folding wings, so no folded flight feathers
    # are mistaken for the tail. UVs and preassigned anatomical weights survive.
    for v,p in zip(obj.data.vertices,original): v.co=Vector(p)
    cut(obj,(0,.24,0),(0,1,0))
    for v in obj.data.vertices: v.co=remodel(v.co.copy())
    cut(obj,(0,0,HEAD_CUT),(0,0,1))


def export(path,objects,animated=False):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.export_scene.gltf(filepath=path,export_format='GLB',use_selection=True,
        export_animations=animated,export_animation_mode='NLA_TRACKS',export_skins=animated,export_def_bones=False)


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:]
    os.makedirs(args[1],exist_ok=True);os.makedirs(args[2],exist_ok=True)
    body,original=source(args[0]);head,tail=extract(body,original);trim_body(body,original)
    for name,obj in [('body',body),('head',head),('tail',tail)]:
        export(f'{args[1]}/{name}_norm.glb',[obj]);print('PART',name,len(obj.data.polygons))
    pieces=[body]
    for i,(x,y,z,lean) in enumerate(HEADS):
        part=duplicate(head,f'head_{i}')
        part.location=Vector(NECK)+Vector((x,y,z));part.rotation_euler=(0,lean,0);part.scale=(.88,)*3;pieces.append(part)
    for i,angle in enumerate(TAIL_ANGLES):
        part=duplicate(tail,f'tail_{i}')
        part.location=Vector(TAIL)+Vector((-angle*.10,.03,(-1 if i%2 else 1)*.018))
        part.rotation_euler=Euler((.10+(i%2)*.04,0,angle),'XYZ');pieces.append(part)
    bpy.data.objects.remove(head,do_unlink=True);bpy.data.objects.remove(tail,do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    for part in pieces: part.select_set(True)
    bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    render_views(body,setup_render(1024),args[2])
