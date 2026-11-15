"""Produce disclosed modular High-stage references, never submit paid jobs.
The full candidate is a layout reference only. Four separate High mothers cover
all visible regions: new trunk, retained lower-paw reference, human neck, tail.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('tianwu_prepare',Path(__file__).with_name('prepare_tianwu.py'))
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)

def components(obj):
    adjacency=[[] for _ in obj.data.vertices]
    for edge in obj.data.edges:
        a,b=edge.vertices;adjacency[a].append(b);adjacency[b].append(a)
    remaining=set(range(len(adjacency)));result=[]
    while remaining:
        seed=remaining.pop();stack=[seed];group=[seed]
        while stack:
            for j in adjacency[stack.pop()]:
                if j in remaining:remaining.remove(j);stack.append(j);group.append(j)
        result.append(np.array(group))
    return result

def extract(source,ids,name):
    chosen=set(ids);mapping={v:i for i,v in enumerate(ids)}
    faces=[[mapping[v] for v in p.vertices] for p in source.data.polygons if all(v in chosen for v in p.vertices)]
    return P.mesh(name,[source.data.vertices[int(i)].co[:] for i in ids],faces)

def extend_leg(leg):
    # Continue the actual cut ring instead of overlapping a separately capped
    # cylinder. This removes the cuff that the first mother reference exposed.
    bm=bmesh.new();bm.from_mesh(leg.data)
    # glTF duplicates coincident vertices at UV/normal seams. Weld those seams
    # before finding the single cut cycle and constructing a watertight loft.
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,plane_co=(0,0,.23),plane_no=(0,0,1),clear_outer=True)
    bm.verts.index_update();bm.verts.ensure_lookup_table();adj={}
    for edge in bm.edges:
        if edge.is_boundary and all(abs(v.co.z-.23)<1e-5 for v in edge.verts):
            a,b=[v.index for v in edge.verts];adj.setdefault(a,[]).append(b);adj.setdefault(b,[]).append(a)
    assert adj and all(len(n)==2 for n in adj.values()),'Expected one intact paw cut loop'
    order=[min(adj)];previous=None
    while True:
        nxt=next(j for j in adj[order[-1]] if j!=previous)
        if nxt==order[0]:break
        previous=order[-1];order.append(nxt)
    native=[bm.verts[i] for i in order];target=np.mean([v.co[:] for v in native],axis=0)
    offsets=np.array([[v.co.x-target[0],-(v.co.y-target[1])] for v in native]);angles=np.arctan2(offsets[:,1],offsets[:,0]);radius=np.linalg.norm(offsets,axis=1).mean()
    control=np.array([[-.368,-.16,.58],[-.40,-.19,.43],target+[0,0,.10],target]);rings=[]
    for t in np.linspace(0,1,49)[:-1]:
        c,d=P.bezier(control,t);u=P.unit(np.array([1,0,0])-d*d[0]);w=np.cross(d,u);r=np.interp(t,[0,.35,.75,1],[.095,.080,.049,radius]);blend=float(P.smooth((t-.65)/.35));section=(1-blend)*np.c_[np.cos(angles),np.sin(angles)]*r+blend*offsets
        rings.append([bm.verts.new(c+u*x+w*y) for x,y in section])
    rings.append(native)
    for lower,upper in zip(rings[:-1],rings[1:]):
        for j in range(len(native)):bm.faces.new([lower[j],lower[(j+1)%len(native)],upper[(j+1)%len(native)],upper[j]])
    bm.faces.new(list(reversed(rings[0])))
    # The disclosed lower-paw donor contains small open toe loops. Seal them
    # before voxel fusion: an open shell is discarded by the volume remesher.
    boundary=[edge for edge in bm.edges if edge.is_boundary]
    if boundary:bmesh.ops.holes_fill(bm,edges=boundary,sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    if bm.calc_volume(signed=True)<0:bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
    assert not any(edge.is_boundary for edge in bm.edges),'Single limb loft must close before local fusion'
    print('LEG_LOFT',json.dumps({'volume':bm.calc_volume(signed=True),'boundaryEdges':sum(e.is_boundary for e in bm.edges),'ring':len(native)}))
    bm.to_mesh(leg.data);bm.free()
    return leg

def trunk():
    # Limbless organic core, separate from the eight-foot layout. These dimensions
    # are explicit artistic inference, not a claimed native High generation.
    xs=np.linspace(-.60,1.72,129);points=[];faces=[];segments=64
    profile=np.array([[-.60,.003,.61,.61],[-.43,.21,.91,.44],[-.12,.27,.96,.40],[.30,.24,.94,.43],[.75,.20,.90,.49],[1.15,.24,.94,.46],[1.48,.22,.92,.44],[1.72,.003,.66,.66]])
    for x in xs:
        width=np.interp(x,profile[:,0],profile[:,1]);top=np.interp(x,profile[:,0],profile[:,2]);bottom=np.interp(x,profile[:,0],profile[:,3]);z=(top+bottom)/2;r=max((top-bottom)/2,.003)
        for angle in np.arange(segments)*2*math.pi/segments:points.append([x,width*math.cos(angle),z+r*math.sin(angle)])
    for i in range(len(xs)-1):
        for j in range(segments):
            a=i*segments+j;b=i*segments+(j+1)%segments;c=(i+1)*segments+(j+1)%segments;d=(i+1)*segments+j
            faces.extend([[a,b,c],[a,c,d]])
    points.extend([[-.60,0,.61],[1.72,0,.66]])
    for j in range(segments):faces.extend([[len(points)-2,(j+1)%segments,j],[len(points)-1,(len(xs)-1)*segments+j,(len(xs)-1)*segments+(j+1)%segments]])
    obj=P.mesh('Procedural_limbless_trunk_reference_not_High',points,faces)
    bpy.context.view_layer.objects.active=obj
    mod=obj.modifiers.new('Core_contour_rounding','SMOOTH');mod.factor=.7;mod.iterations=12;bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj

def pigment(obj,tree,q,tri,field,kind):
    colors=[]
    for v in obj.data.vertices:
        if kind=='trunk':
            x,y,z=v.co;n=math.sin(x*5.3+y*3.1+math.sin(z*4.4))+.55*math.sin(y*8.1-z*5.8+math.sin(x*2.2));t=float(P.smooth((n+.95)/1.9));color=(1-t)*np.array([.075,.22,.16])+t*np.array([.48,.32,.085])
        else:
            hit,normal,idx,dist=tree.find_nearest(v.co)
            a,b,c=q[tri[idx]];d0=b-a;d1=c-a;d2=np.array(hit)-a
            den=max((d0@d0)*(d1@d1)-(d0@d1)**2,1e-18);u=((d1@d1)*(d2@d0)-(d0@d1)*(d2@d1))/den;w=((d0@d0)*(d2@d1)-(d0@d1)*(d2@d0))/den
            color=np.array([1-u-w,u,w])@field[tri[idx],:3]
        colors.append([*np.clip(color,0,1),1])
    attr=obj.data.color_attributes.new(name='Reference_pigment',type='FLOAT_COLOR',domain='POINT');attr.data.foreach_set('color',np.asarray(colors,dtype=np.float32).ravel())
    mat=bpy.data.materials.new('Reference_'+kind);mat.use_nodes=True;vertex=mat.node_tree.nodes.new('ShaderNodeVertexColor');vertex.layer_name=attr.name
    bs=mat.node_tree.nodes['Principled BSDF'];bs.inputs['Roughness'].default_value=.85;mat.node_tree.links.new(vertex.outputs['Color'],bs.inputs['Base Color']);obj.data.materials.clear();obj.data.materials.append(mat)

def render(obj,out,closeups=False):
    out.mkdir(parents=True,exist_ok=True);sc=bpy.context.scene
    for other in sc.objects:
        if other.type=='MESH':other.hide_render=other!=obj
    p=np.array([tuple(v.co) for v in obj.data.vertices]);lo=p.min(0);hi=p.max(0);target=Vector((lo+hi)/2);scale=float(np.linalg.norm(hi-lo))*1.45
    sc.render.engine='CYCLES';sc.cycles.samples=24;sc.cycles.use_denoising=True;sc.render.resolution_x=sc.render.resolution_y=1024;sc.render.resolution_percentage=100
    if not any(o.type=='LIGHT' for o in sc.objects):
        world=bpy.data.worlds.new('Mother_reference_world');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.48,.51,.55,1);world.node_tree.nodes['Background'].inputs[1].default_value=.5;sc.world=world
        for i,(loc,power,size) in enumerate([((-3,-4,6),600,3),((3,-1,4),300,4),((1,4,5),430,3)]):
            light=bpy.data.objects.new('Mother_soft_'+str(i),bpy.data.lights.new('Mother_soft_'+str(i),'AREA'));sc.collection.objects.link(light);light.location=loc;light.rotation_euler=(target-light.location).to_track_quat('-Z','Y').to_euler();light.data.energy=power;light.data.size=size
    sc.view_settings.view_transform='AgX'
    for name,direction in [('view_34',(-.8,-1,.30)),('view_side',(0,-1,.05)),('view_front',(-1,0,.04)),('view_back',(1,0,.04))]:
        camera=bpy.data.objects.new('Mother_camera',bpy.data.cameras.new('Mother_camera'));sc.collection.objects.link(camera)
        camera.location=target+Vector(direction).normalized()*7;camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=scale;sc.camera=camera;sc.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True);bpy.data.objects.remove(camera,do_unlink=True)
    if closeups:
        for name,height in [('detail_upper',.74),('detail_lower',.20)]:
            focus=target.copy();focus.z=float(lo[2]+height*(hi[2]-lo[2]))
            camera=bpy.data.objects.new('Source_detail_camera',bpy.data.cameras.new('Source_detail_camera'));sc.collection.objects.link(camera)
            camera.location=focus+Vector((-.8,-1,.2)).normalized()*7;camera.rotation_euler=(focus-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=scale*.43;sc.camera=camera;sc.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True);bpy.data.objects.remove(camera,do_unlink=True)

def review_actual(path,out):
    # Review untouched returned geometry/PBR before normalization or assembly.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    obj=P.join(P.load(path));obj.name='Actual_source_unmodified'
    obj.data.calc_loop_triangles()
    receipt={'status':'actual returned source awaiting visual acceptance',
        'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'triangles':len(obj.data.loop_triangles),'vertices':len(obj.data.vertices),
        'textures':[{ 'name':im.name,'width':im.size[0],'height':im.size[1]} for im in bpy.data.images if im.size[0]],
        'geometryEdits':False,'paidRequestsByThisScript':0}
    render(obj,out,closeups=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'actual-source.blend'))
    (out/'actual-source-receipt.json').write_text(json.dumps(receipt,indent=2))

def main():
    ap=argparse.ArgumentParser();source=ap.add_mutually_exclusive_group(required=True);source.add_argument('--blend');source.add_argument('--actual');ap.add_argument('--output-dir',required=True);ap.add_argument('--only',choices=['trunk','leg','headneck','tail']);args=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    out=Path(args.output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    if args.actual:
        review_actual(Path(args.actual).resolve(),out);return
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.blend).resolve()))
    source=bpy.data.objects['Tianwu_bake_source_disclosed_derived_anatomy'];actual=bpy.data.objects['Tianwu_continuous_eight_head_eight_foot_eight_tail'];anatomy=json.loads((Path(args.blend).parent/'anatomy.json').read_text())
    actual.data.calc_loop_triangles();q=np.array([v.co[:] for v in actual.data.vertices]);tri=np.array([t.vertices[:] for t in actual.data.loop_triangles]);field=np.array([v.color[:] for v in actual.data.color_attributes['Continuous_pigment'].data]);tree=BVHTree.FromPolygons(q.tolist(),tri.tolist(),all_triangles=True)
    sq=np.array([v.co[:] for v in source.data.vertices]);groups=components(source)
    def nearest_component(point):return min(groups,key=lambda ids:np.linalg.norm(sq[ids]-point,axis=1).min())
    head=extract(source,nearest_component(np.array(anatomy['heads'][0]['headCenter'])),'Single_complete_human_face_curved_neck_reference')
    tail=extract(source,nearest_component(P.bezier(np.array(anatomy['tails'][0]['control']),.72)[0]),'Single_round_curved_tail_reference')
    body_ids=max(groups,key=len);body_q=sq[body_ids]
    mask=(np.argmin(abs(body_q[:,0,None]-np.array([-.368,.3765,.732,1.4765])),axis=1)==0)&(body_q[:,1]<0)&(body_q[:,2]<.40)
    cropped=extract(source,body_ids[mask],'Cropped_paw_with_disconnected_belly_fragments')
    leg=extract(cropped,max(components(cropped),key=len),'One_complete_paw_limb_reference')
    bpy.data.objects.remove(cropped,do_unlink=True)
    leg=extend_leg(leg)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=20,location=(-.368,-.16,.565));cap=bpy.context.object;cap.scale=(.096,.096,.10);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    leg=P.join([leg,cap]);bpy.context.view_layer.objects.active=leg;mod=leg.modifiers.new('Rounded_proximal_root','REMESH');mod.mode='VOXEL';mod.voxel_size=.002;mod.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=mod.name)
    # Round only the newly built upper root; retain the visible paw silhouette.
    group=leg.vertex_groups.new(name='New_upper_tissue')
    for v in leg.data.vertices:
        if v.co.z>.13:group.add([v.index],float(P.smooth((v.co.z-.13)/.14)),'REPLACE')
    mod=leg.modifiers.new('Upper_limb_fairing','SMOOTH');mod.factor=.65;mod.iterations=100;mod.vertex_group=group.name;bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.context.view_layer.objects.active=head;mod=head.modifiers.new('Neck_reference_rounding','REMESH');mod.mode='VOXEL';mod.voxel_size=.002;mod.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=mod.name)
    root=anatomy['tails'][0]['control'][0]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=20,location=root);cap=bpy.context.object;cap.scale=(.09,.079,.079);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    tail=P.join([tail,cap]);bpy.context.view_layer.objects.active=tail;mod=tail.modifiers.new('Rounded_tail_root','REMESH');mod.mode='VOXEL';mod.voxel_size=.002;mod.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=mod.name)
    mothers={'trunk':trunk(),'leg':leg,'headneck':head,'tail':tail};records={}
    for kind,obj in mothers.items():
        if args.only and args.only!=kind:continue
        obj.hide_set(False);pigment(obj,tree,q,tri,field,kind);dest=out/kind;dest.mkdir(exist_ok=True);P.export(obj,dest/'reference.glb');render(obj,dest)
        records[kind]={'geometry':'procedural limbless core' if kind=='trunk' else 'extracted disclosed donor-derived reference','high':False,'paid':False,'glb':str(dest/'reference.glb'),'sha256':hashlib.sha256((dest/'reference.glb').read_bytes()).hexdigest()}
    (out/'reference-receipt.json').write_text(json.dumps({'status':'candidate awaiting parent review; no High job submitted','wholeLayoutIsHigh':False,'parts':records,'sourceBlend':str(Path(args.blend).resolve())},indent=2))
if __name__=='__main__':main()
