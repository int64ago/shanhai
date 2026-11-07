"""Offline Screen Peng: left/right heads, not Bingfeng's front/rear anatomy.
Only verified Zheng Extreme-High masters are read. Native upper shoulder/neck
tissue is deformed into two branches, unioned and stitched to retained lower
body/head surfaces. Retained UVs and a donor-projected coat atlas stay separate.
No generation/network requests. Input +Z-up, forward -Y.
"""
import argparse
import math
import sys
from pathlib import Path
import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def transform(obj, fn):
    p=np.array([v.co[:] for v in obj.data.vertices]);q=fn(p)
    jac=np.empty((len(p),3,3))
    for a in range(3):
        d=np.zeros(3);d[a]=1e-5;jac[:,:,a]=(fn(p+d)-fn(p-d))/(2e-5)
    inv=np.linalg.inv(jac)
    n=np.array([v.vector[:] for v in obj.data.corner_normals]);ids=np.array([v.vertex_index for v in obj.data.loops])
    n=np.einsum('ni,nij->nj',n,inv[ids]);length=np.linalg.norm(n,axis=1)
    n[length<1e-8]=[0,0,1];n/=np.maximum(np.linalg.norm(n,axis=1),1e-8)[:,None]
    assert np.isfinite(q).all() and np.isfinite(n).all()
    for v,co in zip(obj.data.vertices,q):v.co=co
    obj.data.normals_split_custom_set(n.tolist());obj.data.update()


def coat(obj):
    mat=obj.data.materials[0];mat.name='ScreenPengBody'
    shader=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    image=shader.inputs['Base Color'].links[0].from_node.image
    w,h=image.size;pixels=np.empty(w*h*4,dtype=np.float32);image.pixels.foreach_get(pixels)
    rgba=pixels.reshape(h,w,4);src=rgba[:,:,:3].copy()
    red=(src[:,:,0]>src[:,:,1]*1.25)&(src[:,:,0]>src[:,:,2]*1.3)
    shade=np.clip(src[:,:,0:1]/.68,.2,1.25)
    rgba[:,:,:3][red]=(np.array([.50,.35,.21])*shade)[red]
    white=(src.min(axis=2)>.5)&(src.max(axis=2)-src.min(axis=2)<.22)
    rgba[:,:,:3][white]=(src*np.array([.98,.94,.85]))[white]
    gray=(src.min(axis=2)>.14)&(src.max(axis=2)<.60)&(src.max(axis=2)-src.min(axis=2)<.16)&(src[:,:,2]>src[:,:,0]*.85)
    rgba[:,:,:3][gray]=(np.array([.50,.35,.21])*np.clip(src[:,:,0:1]*2,.6,1))[gray]
    image.pixels.foreach_set(rgba.ravel());image.update();image.file_format='PNG';image.pack()
    return mat


def source_corrections(p):
    q=p.copy();x,y,z=p.T
    roof=.902+.50*(y+.4)-3*x*x
    horn=(abs(x)<.044)&(y<-.39)&(z>roof)
    q[horn,2]=roof[horn]+(z[horn]-roof[horn])*.015
    shoulder=np.exp(-((y+.18)/.22)**4)*np.clip((z-.53)/.18,0,1)*np.clip((.79-z)/.06,0,1)
    q[:,0]*=1+.30*shoulder
    hock=(z>.13)&(z<.25)&(y>.455);q[hock,1]=.455+(y[hock]-.455)*.02
    # Consolidate only the lowest plantar skin into a genuinely flat support
    # band. Keep a positive derivative for guarded inverse-transpose normals.
    sole=np.clip((z-.004)/.004,0,1);sole=sole*sole*(3-2*sole)
    low=z<.008;q[low,2]=z[low]*(.01+.99*sole[low])
    return q


HEAD_BASE=Vector((0,-.270,.800))
HEAD_NORMAL=Vector((0,-.65,.76)).normalized()


def cut(obj,point,normal,keep_above):
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,
                         plane_co=point,plane_no=normal,clear_inner=keep_above,clear_outer=not keep_above)
    bm.to_mesh(obj.data);bm.free();obj.data.update()


def head(source,sign):
    obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj)
    # An oblique anatomical neck section retains the complete jaw and posterior
    # skull. The previous coordinate crop sliced straight through both heads.
    cut(obj,HEAD_BASE,HEAD_NORMAL,True)
    root=Vector((sign*.130,-.245,.845));rot=Matrix.Rotation(sign*math.radians(48),3,'Z')
    matrix=Matrix.Translation(root)@rot.to_4x4()@Matrix.Translation(-HEAD_BASE)
    obj.data.transform(matrix)
    mat=source.data.materials[0].copy();mat.name='ScreenPengHeadL' if sign>0 else 'ScreenPengHeadR'
    obj.data.materials.clear();obj.data.materials.append(mat);obj.name='head_l' if sign>0 else 'head_r'
    print('HEAD_RETAINED',obj.name,len(obj.data.polygons),'polygons before seam fairing')
    return obj,root,rot@HEAD_NORMAL


def neck_material():
    # Temporary slot, replaced with the baked donor coat after stitching.
    mat=bpy.data.materials.new('ScreenPengNeck');mat.use_nodes=True
    return mat


def shoulder(source,heads):
    # Deform REAL native feline neck/shoulder tissue, with the lower scapular
    # region common to both branches. This retains the donor's irregular
    # trapezius, throat and fur surface instead of constructing round tubes.
    donors=[];volumes=[]
    for sign,(_,root,_) in zip([1,-1],heads):
        obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj)
        cut(obj,HEAD_BASE+HEAD_NORMAL*.025,HEAD_NORMAL,False)
        cut(obj,Vector((0,0,.54)),Vector((0,0,1)),True)
        rot=Matrix.Rotation(sign*math.radians(48),3,'Z')
        for vertex in obj.data.vertices:
            p=vertex.co.copy();d=(p-HEAD_BASE).dot(HEAD_NORMAL)
            alpha=max(0,min(1,(d+.19)/.14));alpha=alpha*alpha*(3-2*alpha)
            low=max(0,min(1,(p.z-.620)/.075));low=low*low*(3-2*low)
            alpha*=low
            vertex.co=p.lerp(root+rot@(p-HEAD_BASE),alpha)
        obj.data.update();donors.append(obj)
        volume=obj.copy();volume.data=obj.data.copy();bpy.context.collection.objects.link(volume)
        # Only temporary union inputs are closed. All closing disks are cut
        # away after the union; none survive in the stitched delivered mesh.
        bm=bmesh.new();bm.from_mesh(volume.data)
        boundary=[e for e in bm.edges if e.is_boundary]
        bmesh.ops.holes_fill(bm,edges=boundary,sides=0);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(volume.data);bm.free();volumes.append(volume)
    bpy.ops.object.select_all(action='DESELECT')
    for volume in volumes:volume.select_set(True)
    obj=volumes[0];bpy.context.view_layer.objects.active=obj;bpy.ops.object.join();obj.name='bifurcating_shoulders'
    mod=obj.modifiers.new('native_neck_union','REMESH');mod.mode='VOXEL';mod.voxel_size=.002
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mod=obj.modifiers.new('tissue_relax','SMOOTH');mod.factor=.45;mod.iterations=3;bpy.ops.object.modifier_apply(modifier=mod.name)
    cut(obj,Vector((0,0,.611)),Vector((0,0,1)),True)
    for _,point,normal in heads:cut(obj,point-normal*.012,normal,False)
    obj.data.materials.clear();obj.data.materials.append(neck_material())
    return obj,donors


def coat_sampler(objects):
    points=[];triangles=[];uvs=[]
    shader=next(n for n in objects[0].data.materials[0].node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    image=shader.inputs['Base Color'].links[0].from_node.image
    width,height=image.size;pixels=np.empty(width*height*4,dtype=np.float32);image.pixels.foreach_get(pixels);pixels=pixels.reshape(height,width,4)
    for obj in objects:
        mesh=obj.data;mesh.calc_loop_triangles();offset=len(points);points.extend(v.co.copy() for v in mesh.vertices)
        for tri in mesh.loop_triangles:
            triangles.append(tuple(offset+i for i in tri.vertices))
            uvs.append([Vector((*mesh.uv_layers.active.data[li].uv,0)) for li in tri.loops])
    tree=BVHTree.FromPolygons(points,triangles,all_triangles=True)
    def sample(p):
        nearest,_,index,_=tree.find_nearest(p)
        tri=triangles[index];uv=barycentric_transform(nearest,*[points[i] for i in tri],*uvs[index])
        x=(uv.x%1)*width-.5;y=(uv.y%1)*height-.5;ix=math.floor(x);iy=math.floor(y);fx=x-ix;fy=y-iy
        colour=(pixels[iy%height,ix%width,:3]*(1-fx)*(1-fy)+pixels[iy%height,(ix+1)%width,:3]*fx*(1-fy)+pixels[(iy+1)%height,ix%width,:3]*(1-fx)*fy+pixels[(iy+1)%height,(ix+1)%width,:3]*fx*fy)
        # The reused donor has warm pink texels in its central white chest.
        # Duplicating that patch produced an unintended flesh-coloured knot at
        # the joined sternum. Neutralise only those pale warm throat texels;
        # geometry is one unioned surface and has no crossing fur strips.
        if abs(p.x)<.075 and p.y<-.235 and .58<p.z<.80 and min(colour)>.32 and colour[0]>colour[1]*1.10 and colour[1]>colour[2]*1.08:
            colour=np.array([1,.97,.91])*float(np.mean(colour))
        # Image.pixels supplies encoded donor values; vertex colours are linear
        # and an emission bake encodes them again into the destination sRGB map.
        return np.where(colour<=.04045,colour/12.92,((colour+.055)/1.055)**2.4)
    return sample


def bake_neck(body,sample):
    # Bake just the new tissue into its own UV atlas. Keeping this object
    # separate while baking prevents Blender from writing into donor images.
    index=len(body.data.materials)-1
    faces=[p for p in body.data.polygons if p.material_index==index]
    used=sorted(set(i for p in faces for i in p.vertices));remap={v:i for i,v in enumerate(used)}
    mesh=bpy.data.meshes.new('neck_bake_mesh');mesh.from_pydata([body.data.vertices[i].co for i in used],[],[[remap[i] for i in p.vertices] for p in faces]);mesh.update()
    obj=bpy.data.objects.new('neck_bake',mesh);bpy.context.collection.objects.link(obj)
    colours=mesh.color_attributes.new(name='Coat',type='FLOAT_COLOR',domain='POINT')
    for i,source in enumerate(used):colours.data[i].color=(*sample(body.data.vertices[source].co),1)
    material=bpy.data.materials.new('ScreenPengNeckBaked');material.use_nodes=True
    nodes=material.node_tree.nodes;nodes.clear();out=nodes.new('ShaderNodeOutputMaterial');emission=nodes.new('ShaderNodeEmission');attribute=nodes.new('ShaderNodeVertexColor');attribute.layer_name='Coat'
    material.node_tree.links.new(attribute.outputs['Color'],emission.inputs['Color']);material.node_tree.links.new(emission.outputs[0],out.inputs[0])
    image=bpy.data.images.new('ScreenPengContinuousFur',width=1024,height=1024);tex=nodes.new('ShaderNodeTexImage');tex.image=image;nodes.active=tex
    mesh.materials.append(material)
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=.004);bpy.ops.object.mode_set(mode='OBJECT')
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=1;scene.render.bake.margin=8
    bpy.ops.object.bake(type='EMIT');image.pack()
    uv=body.data.uv_layers.active
    for source,target in zip(faces,mesh.polygons):
        for a,b in zip(source.loop_indices,target.loop_indices):uv.data[a].uv=mesh.uv_layers.active.data[b].uv
    nodes.remove(attribute);nodes.remove(emission)
    bsdf=nodes.new('ShaderNodeBsdfPrincipled');bsdf.inputs['Roughness'].default_value=.9
    material.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color']);material.node_tree.links.new(bsdf.outputs[0],out.inputs[0])
    body.data.materials[index]=material;bpy.data.objects.remove(obj,do_unlink=True)
    bpy.context.view_layer.objects.active=body;body.select_set(True)
    print('BAKED_CONTINUOUS_COAT',len(used),'vertices',len(faces),'faces')


def stitch(body,heads,neck,donors):
    sample=coat_sampler([body,*[h[0] for h in heads],*donors])
    for donor in donors:bpy.data.objects.remove(donor,do_unlink=True)
    # Retain source UV islands. New faces are one connected pair-of-pants
    # surface; bridges may have unequal edge counts and contain no caps.
    parts=[body,*[h[0] for h in heads],neck]
    bpy.ops.object.select_all(action='DESELECT')
    for part in parts:part.select_set(True)
    bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
    bm=bmesh.new();bm.from_mesh(body.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    boundaries=[e for e in bm.edges if e.is_boundary]
    loops=[];pending=set(boundaries)
    while pending:
        edge=pending.pop();component={edge};todo=[edge]
        while todo:
            e=todo.pop()
            for v in e.verts:
                for other in v.link_edges:
                    if other in pending:pending.remove(other);component.add(other);todo.append(other)
        if len(component)>12:loops.append(list(component))
    print('STITCH_LOOPS',[(len(e),tuple(sum((v.co for v in set(v for edge in e for v in edge.verts)),Vector())/len(set(v for edge in e for v in edge.verts)))) for e in loops])
    # The source can have tiny eye/mouth boundaries. Pair only the six surgical
    # loops, using centroids and their short separation.
    def center(edges):
        vs=set(v for e in edges for v in e.verts);return sum((v.co for v in vs),Vector())/len(vs)
    surgical=[e for e in loops if center(e).z<.94 and center(e).z>.58]
    while surgical:
        a=surgical.pop(0);ca=center(a);b=min(surgical,key=lambda e:(center(e)-ca).length)
        surgical.remove(b)
        assert (center(b)-ca).length<.05,(ca,center(b))
        result=bmesh.ops.bridge_loops(bm,edges=a+b,use_pairs=True)
        for face in result['faces']:face.material_index=len(body.data.materials)-1;face.smooth=True
        edges=list(set(e for f in result['faces'] for e in f.edges))
        bmesh.ops.subdivide_edges(bm,edges=edges,cuts=2,use_grid_fill=True)
    # Fair across the real seams, including retained neck tissue. Clearing the
    # imported custom normals below is essential: otherwise the newly welded
    # surface still shades as separate cut cylinders.
    def seam_band(v):
        if .575<v.co.z<.630:return True
        return any(abs((v.co-point).dot(normal))<.035 for _,point,normal in heads)
    authored=[v for v in bm.verts if any(f.material_index==len(body.data.materials)-1 for f in v.link_faces) or seam_band(v)]
    for _ in range(32):bmesh.ops.smooth_vert(bm,verts=authored,factor=.35,use_axis_x=True,use_axis_y=True,use_axis_z=True)
    bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=1e-8)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(body.data);bm.free();body.data.update()
    bpy.context.view_layer.objects.active=body
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
    for poly in body.data.polygons:poly.use_smooth=True
    # Bake a new atlas only for reconstructed tissue; retained UVs stay intact.
    bake_neck(body,sample)
    return body


def tail(path):
    previous=set(bpy.context.scene.objects);bpy.ops.import_scene.gltf(filepath=path)
    obj=next(o for o in bpy.context.scene.objects if o not in previous and o.type=='MESH')
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    print('TAIL_HIGH',len(obj.data.polygons),'source triangles')
    points=np.array([v.co[:] for v in obj.data.vertices]);lo=points.min(axis=0);hi=points.max(axis=0);span=hi-lo;center=(hi+lo)/2
    def curve(p):
        t=(p[:,0]-lo[0])/span[0];u=2*(p[:,1]-center[1])/span[1];v=2*(p[:,2]-center[2])/span[2]
        q=np.empty_like(p);q[:,0]=.055*np.sin(t*math.pi)+.026*u*np.sqrt(np.maximum(.01,1-v*v/2))
        q[:,1]=.40+.60*t
        q[:,2]=.61-.25*np.sin(t*math.pi*.8)+.026*v*np.sqrt(np.maximum(.01,1-u*u/2))
        return q
    transform(obj,curve);coat(obj);obj.data.materials[0]=obj.data.materials[0].copy();obj.data.materials[0].name='ScreenPengTail';obj.name='single_tail'
    return obj


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('body');p.add_argument('tail');p.add_argument('output');p.add_argument('views');a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    obj=load(a.body);print('BODY_HIGH',len(obj.data.polygons),'source triangles')
    transform(obj,source_corrections);coat(obj)
    heads=[head(obj,s) for s in [1,-1]]
    neck,donors=shoulder(obj,heads)
    cut(obj,Vector((0,0,.60)),Vector((0,0,1)),False)
    obj=stitch(obj,heads,neck,donors)
    tail_obj=tail(a.tail)
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);tail_obj.select_set(True)
    bpy.context.view_layer.objects.active=obj;bpy.ops.object.join();obj.name='screen_peng'
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.output).with_suffix('.blend')))
    obj.data.calc_loop_triangles();print('SCREEN_PENG_FINAL',len(obj.data.loop_triangles),'triangles')
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    Path(a.views).mkdir(parents=True,exist_ok=True);render_views(obj,setup_render(1024),a.views)


if __name__=='__main__':main()
