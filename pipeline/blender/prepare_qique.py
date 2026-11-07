"""Offline Qique anatomy from the verified Jingwei Extreme-High master.
Retain dense feather geometry, shorten the beak, deepen the breast, raise the
fowl tail, replace avian toes with sculpted five-digit rodent-like feet and
curved feline claws. No generation/network calls. Input +Z-up, head -Y.
"""
import argparse
import math
import sys
from pathlib import Path
import bmesh
import bpy
import numpy as np
from mathutils import Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render, smoothstep


def paint(obj):
    shader = next(n for n in obj.data.materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    image = shader.inputs['Base Color'].links[0].from_node.image
    w, h = image.size
    px = np.empty(w*h*4, dtype=np.float32)
    image.pixels.foreach_get(px)
    rgba = px.reshape(h, w, 4)
    old = rgba.copy()
    uv = obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        coords = np.array([(uv[i].uv.x*(w-1), uv[i].uv.y*(h-1)) for i in tri.loops])
        lo = np.maximum(np.floor(coords.min(axis=0)).astype(int)-1, 0)
        hi = np.minimum(np.ceil(coords.max(axis=0)).astype(int)+1, [w-1,h-1])
        xx, yy = np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1))
        a,b,c = coords
        d = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(d)<1e-8: continue
        u=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/d
        v=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/d
        pts=np.array([obj.data.vertices[i].co[:] for i in tri.vertices])
        xyz=u[...,None]*pts[0]+v[...,None]*pts[1]+(1-u-v)[...,None]*pts[2]
        x,y,z=xyz[...,0],xyz[...,1],xyz[...,2]
        src=old[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3]
        brightness=src.max(axis=2)
        shade=np.clip(brightness*3+.55,.5,1.4)[...,None]
        colour=np.array([.28,.17,.085])*shade
        head=(np.clip((z-.84)/.10,0,1)*np.clip((.22-abs(x))/.06,0,1)*np.clip((-.12-y)/.08,0,1))[...,None]
        white=np.array([.88,.865,.80])*(.82+.18*np.clip(brightness*4,0,1))[...,None]
        colour=colour*(1-head)+white*head
        # Preserve the small dark orbital region, not the original dark crown.
        eye=(abs(x)>.065)&(((y+.445)/.055)**2+((z-1.013)/.039)**2<1)&(brightness<.12)
        colour[eye]=src[eye]*.5
        beak=(y<-.495)&(z>.86)&(z<1.025)&(abs(x)<.075)
        colour[beak]=(np.array([.24,.17,.08])*shade)[beak]
        # The new bare lower shins blend into the separately sculpted paws.
        shin=(z<.34)&(y<.12)
        colour[shin]=(np.array([.43,.32,.24])*shade)[shin]
        mask=(u>=-.02)&(v>=-.02)&(u+v<=1.02)
        dst=rgba[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3]
        dst[mask]=np.clip(colour,0,1)[mask]
    image.pixels.foreach_set(rgba.ravel());image.update();image.file_format='PNG';image.pack()


def material(name, colour, skin=False):
    size=256
    image=bpy.data.images.new(name,width=size,height=size)
    u,v=np.meshgrid(np.linspace(0,1,size),np.linspace(0,1,size))
    grain=np.sin(u*129+np.sin(v*61))*np.sin(v*147+u*47)*.025
    crease=(np.maximum(0,np.cos(u*math.tau*9))**18)*.16 if skin else .03*np.cos(v*math.tau*6)
    shade=1+grain-crease
    pixels=np.ones((size,size,4),dtype=np.float32)
    pixels[:,:,:3]=np.array(colour)*shade[...,None]
    image.pixels.foreach_set(pixels.ravel());image.pack()
    mat=bpy.data.materials.new(name);mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF')
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value=.8
    return mat


def tube(name, centers, radii, mat, flatten=.8):
    sides=16
    verts=[];faces=[];uvs=[]
    for i,p in enumerate(centers):
        tangent=(centers[min(i+1,len(centers)-1)]-centers[max(0,i-1)]).normalized()
        lateral=Vector((1,0,0))
        if abs(tangent.dot(lateral))>.95: lateral=Vector((0,1,0))
        a=tangent.cross(lateral).normalized();b=tangent.cross(a).normalized()
        for j in range(sides):
            theta=j/sides*math.tau
            verts.append(p+radii[i]*(a*math.cos(theta)*flatten+b*math.sin(theta)))
    for i in range(len(centers)-1):
        for j in range(sides):
            faces.append((i*sides+j,i*sides+(j+1)%sides,(i+1)*sides+(j+1)%sides,(i+1)*sides+j))
    faces.extend([tuple(range(sides-1,-1,-1)),tuple((len(centers)-1)*sides+j for j in range(sides))])
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
    mesh.materials.append(mat)
    uv=mesh.uv_layers.new()
    for face in mesh.polygons:
        face.use_smooth=True
        for loop in face.loop_indices:
            index=mesh.loops[loop].vertex_index
            uv.data[loop].uv=(index//sides/(len(centers)-1),index%sides/sides)
    return obj


def feet(obj):
    skin=material('QiqueSkin',(.49,.38,.29),True)
    claw=material('QiqueClaw',(.65,.57,.43))
    parts=[]
    for sign in [1,-1]:
        ankle=Vector((sign*.145,-.045,.34))
        # Long, low plantigrade palm and a narrow bare ankle, unlike avian toes.
        centers=[ankle.lerp(Vector((sign*.145,-.085,.040)),i/14) for i in range(15)]
        radii=[.012+.009*(1-i/14)**6+.026*(i/14)**6 for i in range(15)]
        parts.append(tube(f'palm_{sign}',centers,radii,skin,.75))
        for digit,length in enumerate([.075,.105,.125,.110,.080]):
            spread=(digit-2)*.024
            start=Vector((sign*.145+spread*.65,-.085,.032))
            end=Vector((sign*.145+spread*1.5,-.085-length,.014))
            centers=[];radii=[]
            for i in range(21):
                t=i/20
                p=start.lerp(end,t);p.z+=.009*math.sin(t*math.pi*3)**2
                centers.append(p)
                radii.append((.014-.004*t)*(1+.14*math.cos(t*math.pi*4)))
            parts.append(tube(f'digit_{sign}_{digit}',centers,radii,skin,.9))
            # Broad curved feline claw, emerging from each distal digit. The
            # ventral hook tapers to a sharp tip just above the ground plane.
            direction=(end-start).normalized();direction.z=0;direction.normalize()
            centers=[];radii=[]
            for i in range(19):
                t=i/18
                p=end+direction*(.039*t)
                p.z=.024+.018*math.sin(t*math.pi)-.013*t*t
                centers.append(p);radii.append(.0125*(1-t)**.72+.0005)
            parts.append(tube(f'claw_{sign}_{digit}',centers,radii,claw,.85))
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    for part in parts: part.select_set(True)
    bpy.context.view_layer.objects.active=obj;bpy.ops.object.join()
    return obj


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('output');p.add_argument('views');a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    obj=load(a.input)
    original=len(obj.data.polygons)
    paint(obj)
    # Replace both bare lower legs and toes, so the new ankle is continuous
    # under the feather cuff rather than meeting a jagged old toe-cut boundary.
    # The source feather tail behind y=.15 is retained throughout.
    bm=bmesh.new();bm.from_mesh(obj.data)
    remove=[v for v in bm.verts if v.co.z<.30 and v.co.y<.15]
    bmesh.ops.delete(bm,geom=remove,context='VERTS');bm.to_mesh(obj.data);bm.free()
    # Smooth analytic proportions; keep all authored normals (never recompute
    # vertex normals on degenerate source triangles after nonuniform scaling).
    normals=[n.vector.copy() for n in obj.data.corner_normals]
    factors=[]
    for vertex in obj.data.vertices:
        q=vertex.co
        breast=(1-smoothstep(.20,.29,abs(q.x)))*smoothstep(.30,.45,q.z)*(1-smoothstep(.70,.85,q.z))
        sx=1+.28*breast
        sy=.5 if q.y<-.405 and q.z>.84 else 1
        tail=q.y>.17 and q.z<.52
        q.x*=sx
        if sy<1:q.y=-.405+(q.y+.405)*sy
        if tail:q.z+=(q.y-.17)*.72;q.y=.17+(q.y-.17)*.78
        factors.append((sx,sy,tail))
    for loop,n in zip(obj.data.loops,normals):
        sx,sy,tail=factors[loop.vertex_index];n.x/=sx
        if tail:n.y=(n.y-.72*n.z)/.78
        else:n.y/=sy
        if n.length>1e-8:n.normalize()
        else:n[:]=(0,0,1)
    obj.data.normals_split_custom_set(normals);obj.data.update()
    obj=feet(obj)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    Path(a.views).mkdir(parents=True,exist_ok=True)
    render_views(obj,setup_render(1024),a.views)
    obj.data.calc_loop_triangles()
    print('QIQUE_HIGH',original,'source triangles;',len(obj.data.loop_triangles),'final triangles; ten sculpted digits/claws')

if __name__=='__main__':main()
