"""Offline Screen Peng: left/right heads, not Bingfeng's front/rear anatomy.
Only verified Zheng Extreme-High masters are read. Body/heads retain dense
source geometry and UVs; a manually authored bifurcating shoulder joins them.
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


def remove_vertices(obj,predicate):
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if predicate(v.co)],context='VERTS')
    bm.to_mesh(obj.data);bm.free();obj.data.update()


def source_corrections(p):
    q=p.copy();x,y,z=p.T
    roof=.902+.50*(y+.4)-3*x*x
    horn=(abs(x)<.044)&(y<-.39)&(z>roof)
    q[horn,2]=roof[horn]+(z[horn]-roof[horn])*.015
    hock=(z>.13)&(z<.25)&(y>.455);q[hock,1]=.455+(y[hock]-.455)*.02
    return q


def head(source,sign):
    obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj)
    remove_vertices(obj,lambda p:not(p.y<-.27 and p.z>.66))
    # Rotate both copies with positive determinant. They occupy opposite X
    # sides at the same longitudinal station; neither is at the rear.
    pivot=Vector((0,-.31,.75));root=Vector((sign*.17,-.24,.875))
    rot=Matrix.Rotation(sign*math.radians(62),3,'Z')
    matrix=Matrix.Translation(root)@rot.to_4x4()@Matrix.Diagonal((1.02,1.02,1.02,1))@Matrix.Translation(-pivot)
    obj.data.transform(matrix)
    mat=source.data.materials[0].copy();mat.name='ScreenPengHeadL' if sign>0 else 'ScreenPengHeadR'
    obj.data.materials.clear();obj.data.materials.append(mat);obj.name='head_l' if sign>0 else 'head_r'
    print('HEAD_HIGH',obj.name,len(obj.data.polygons),'triangles')
    return obj


def neck_material():
    size=1024;u,v=np.meshgrid(np.linspace(0,1,size),np.linspace(0,1,size))
    # Warm coat, fine fur grain and irregular dark rosettes on original neck
    # geometry. Neither the species nor these colours are claimed as source.
    grain=.045*np.sin(u*900+np.sin(v*30))*np.sin(v*170)
    px=np.ones((size,size,4),dtype=np.float32);px[:,:,:3]=np.array([.50,.35,.21])*(.94+grain[...,None])
    rng=np.random.default_rng(217)
    for _ in range(390):
        cx,cy=rng.uniform(0,size,2);rx,ry=rng.uniform(6,17),rng.uniform(5,13)
        x0,x1=max(0,int(cx-rx*1.3)),min(size,int(cx+rx*1.3)+1)
        y0,y1=max(0,int(cy-ry*1.3)),min(size,int(cy+ry*1.3)+1)
        xx,yy=np.meshgrid(np.arange(x0,x1),np.arange(y0,y1));a=(xx-cx)/rx;b=(yy-cy)/ry
        mask=a*a+b*b<1+.20*np.sin(np.arctan2(b,a)*3+rng.uniform(0,math.tau))
        patch=px[y0:y1,x0:x1,:3];patch[mask]*=rng.uniform(.10,.25)
    im=bpy.data.images.new('ScreenPengNeckFur',width=size,height=size);im.pixels.foreach_set(px.ravel());im.pack()
    mat=bpy.data.materials.new('ScreenPengNeck');mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Roughness'].default_value=.9
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=im;mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    return mat


def shoulder():
    parts=[]
    # Only the original joining geometry is voxel-unioned. Source HIGH meshes
    # are never remeshed or simplified. Overlaps sit below the retained coat.
    for center,scale in [((0,-.205,.705),(.145,.115,.105)),
                         ((.095,-.215,.775),(.105,.085,.105)),
                         ((-.095,-.215,.775),(.105,.085,.105)),
                         ((.16,-.23,.835),(.080,.075,.090)),
                         ((-.16,-.23,.835),(.080,.075,.090))]:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=40,ring_count=24,location=center)
        obj=bpy.context.object;obj.scale=scale;bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);parts.append(obj)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in parts:obj.select_set(True)
    bpy.context.view_layer.objects.active=parts[0];bpy.ops.object.join();obj=parts[0];obj.name='bifurcating_shoulders'
    mod=obj.modifiers.new('authored_union','REMESH');mod.mode='VOXEL';mod.voxel_size=.006
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mod=obj.modifiers.new('authored_smooth','SMOOTH');mod.factor=.55;mod.iterations=4;bpy.ops.object.modifier_apply(modifier=mod.name)
    uv=obj.data.uv_layers.new()
    for poly in obj.data.polygons:
        poly.use_smooth=True
        for loop in poly.loop_indices:
            p=obj.data.vertices[obj.data.loops[loop].vertex_index].co
            uv.data[loop].uv=((math.atan2(p.y+.22,p.x)/math.tau+.5),p.z*2)
    obj.data.materials.append(neck_material())
    return obj


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
    remove_vertices(obj,lambda p:p.z>.72 and p.y<-.18)
    # The broad authored shoulder covers the old central neck opening; no
    # third head or duplicate original neck is retained.
    parts=[obj,*heads,shoulder(),tail(a.tail)]
    bpy.ops.object.select_all(action='DESELECT')
    for part in parts:part.select_set(True)
    bpy.context.view_layer.objects.active=obj;bpy.ops.object.join();obj.name='screen_peng'
    obj.data.calc_loop_triangles();print('SCREEN_PENG_FINAL',len(obj.data.loop_triangles),'triangles')
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    Path(a.views).mkdir(parents=True,exist_ok=True);render_views(obj,setup_render(1024),a.views)


if __name__=='__main__':main()
