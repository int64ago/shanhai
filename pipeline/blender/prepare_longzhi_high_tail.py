"""Offline High-tail shape/UV derivative; source geometry tier stays disclosed.
Actual High vertices are reshaped to a round fox-tail envelope. A reviewed
Medium coat is only a texture donor; this is not an untouched High generation.
"""
import argparse,hashlib,json,math,sys
from pathlib import Path
import bpy,bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree


def load(path,name):
    old=set(bpy.context.scene.objects);bpy.ops.import_scene.gltf(filepath=str(path))
    meshes=[o for o in bpy.context.scene.objects if o not in old and o.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:o.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    if len(meshes)>1:bpy.ops.object.join()
    o=bpy.context.object;bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);o.name=name
    return o


def frame(obj):
    p=np.array([v.co[:] for v in obj.data.vertices]);lo=p.min(0);hi=p.max(0);scale=1.6/(hi[0]-lo[0]);p=(p-(lo+hi)*.5)*scale;p[:,2]+=.15
    return p


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--high',required=True,type=Path);ap.add_argument('--coat-reference',required=True,type=Path);ap.add_argument('--output-dir',required=True,type=Path)
    args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    donor=load(args.coat_reference,'reviewed_medium_texture_reference');dp=frame(donor);mesh=donor.data;uv=mesh.uv_layers.active
    colors={}
    for i,material in enumerate(mesh.materials):
        if not material or not material.use_nodes:continue
        shader=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        tex=shader.inputs['Base Color'].links[0].from_node;image=tex.image;pixels=np.empty(image.size[0]*image.size[1]*4,np.float32);image.pixels.foreach_get(pixels);colors[i]=(pixels.reshape(image.size[1],image.size[0],4),image.size[:])
    center=np.array([0,0,.15]);angle=np.arctan2(dp[:,2]-.15,dp[:,1]);tree=KDTree(len(dp));vertex_uv={}
    for face in mesh.polygons:
        for loop in face.loop_indices:vertex_uv.setdefault(mesh.loops[loop].vertex_index,(uv.data[loop].uv[:],face.material_index))
    for i,p in enumerate(dp):tree.insert(((p[0]+.8)/1.6,math.cos(angle[i])*.14,math.sin(angle[i])*.14),i)
    tree.balance()
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform
    mesh.calc_loop_triangles();triangles=list(mesh.loop_triangles)
    surface=BVHTree.FromPolygons([Vector(p) for p in dp],[list(tri.vertices) for tri in triangles],all_triangles=True)
    size=1024;pixels=np.ones((size,size,4),np.float32)
    for row in range(size):
        a=row/(size-1)*math.tau
        for col in range(size):
            t=col/(size-1);direction=Vector((0,math.cos(a),math.sin(a)));origin=Vector((-.8+1.6*t,0,.15))+direction*.5;hit,normal,index,distance=surface.ray_cast(origin,-direction,1.)
            if hit is None:hit,normal,index,distance=surface.find_nearest(origin)
            tri=triangles[index];source_uv=[Vector((*uv.data[i].uv,0)) for i in tri.loops];value=barycentric_transform(hit,*[Vector(dp[i]) for i in tri.vertices],*source_uv);u,v=value.x,value.y;image,(w,h)=colors[tri.material_index]
            xx=max(0,min(w-1,u*w));yy=max(0,min(h-1,v*h));x0=int(xx);y0=int(yy);fx=xx-x0;fy=yy-y0;x1=min(w-1,x0+1);y1=min(h-1,y0+1);color=(image[y0,x0,:3]*(1-fx)+image[y0,x1,:3]*fx)*(1-fy)+(image[y1,x0,:3]*(1-fx)+image[y1,x1,:3]*fx)*fy
            white=max(0,min(1,(t-.86-.012*math.sin(a*11))/.09));white=white*white*(3-2*white)
            pixels[row,col,:3]=color*(1-white)+np.array([.87,.83,.74])*white
    bpy.data.objects.remove(donor,do_unlink=True)
    obj=load(args.high,'longzhi_tail_high_geometry_repainted');p=frame(obj)
    t=(p[:,0]+.8)/1.6
    centers=[];radii=[];levels=np.linspace(0,1,81)
    for level in levels:
        points=p[abs(t-level)<.016]
        if not len(points):points=p[[np.argmin(abs(t-level))]]
        c=(points[:,1:].min(0)+points[:,1:].max(0))*.5;r=np.maximum(np.ptp(points[:,1:],axis=0)*.5,.0001);centers.append(c);radii.append(r)
    centers=np.array(centers);radii=np.array(radii)
    for axis in range(2):
        for _ in range(5):
            centers[1:-1,axis]=(centers[:-2,axis]+2*centers[1:-1,axis]+centers[2:,axis])/4
            radii[1:-1,axis]=(radii[:-2,axis]+2*radii[1:-1,axis]+radii[2:,axis])/4
    cy=np.interp(t,levels,centers[:,0]);cz=np.interp(t,levels,centers[:,1]);ry=np.interp(t,levels,radii[:,0]);rz=np.interp(t,levels,radii[:,1]);y=(p[:,1]-cy)/ry;z=(p[:,2]-cz)/rz
    profile=np.array([[0,.024],[.07,.049],[.25,.108],[.42,.116],[.7,.079],[.88,.030],[1,.0015]])
    radius=np.interp(t,profile[:,0],profile[:,1])
    # Smooth axial profile without changing longitudinal High vertex ordering.
    for _ in range(3):
        sampled=np.interp(levels,profile[:,0],profile[:,1]);sampled[1:-1]=(sampled[:-2]+2*sampled[1:-1]+sampled[2:])/4;radius=np.interp(t,levels,sampled)
    p[:,1]=radius*y;p[:,2]=.15+radius*z+.105*np.sin(math.pi*t)
    for vertex,q in zip(obj.data.vertices,p):vertex.co=q
    angle=np.mod(np.arctan2(z,y),math.tau)/math.tau
    for layer in list(obj.data.uv_layers):obj.data.uv_layers.remove(layer)
    uv=obj.data.uv_layers.new(name='RoundTailRepaintUV')
    for face in obj.data.polygons:
        values=[angle[i] for i in face.vertices];seam=max(values)-min(values)>.5
        for loop in face.loop_indices:
            i=obj.data.loops[loop].vertex_index;v=angle[i];uv.data[loop].uv=(float(t[i]),float(v+1 if seam and v<.5 else v))
        face.use_smooth=True
    bm=bmesh.new();bm.from_mesh(obj.data);bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-7);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
    image=bpy.data.images.new('offline_medium_coat_repaint_on_high_tail',width=size,height=size);image.pixels.foreach_set(pixels.ravel());image.pack()
    mat=bpy.data.materials.new('High_geometry_repainted_round_fox_tail');mat.use_nodes=True;shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Roughness'].default_value=.88;tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image;mat.node_tree.links.new(tex.outputs['Color'],shader.inputs['Base Color']);obj.data.materials.clear();obj.data.materials.append(mat)
    bpy.ops.export_scene.gltf(filepath=str(out/'tail.glb'),export_format='GLB',export_animations=False)
    audit={'highSource':str(args.high),'highSourceSha256':hashlib.sha256(args.high.read_bytes()).hexdigest(),'coatDonor':str(args.coat_reference),'coatDonorSha256':hashlib.sha256(args.coat_reference.read_bytes()).hexdigest(),'geometryDerivative':True,'uvReplaced':True,'mediumGeometryUsed':False,'paidCalls':0,'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons),'accepted':False};(out/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    sys.path.insert(0,str(Path(__file__).resolve().parent));from prepare_longzhi_continuous import render
    render(obj,out,900)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'tail.blend'))

if __name__=='__main__':main()
