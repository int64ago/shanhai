"""HIGH bird torso + HIGH shoulderless human head + nine original feather necks.
Blender --background --python prepare_jiufeng.py -- bird_norm.glb head_clean.glb out_dir concept_dir
"""
import math
import os
import sys
import bpy
import numpy as np
from mathutils import Vector
sys.dont_write_bytecode=True
sys.path.insert(0,os.path.dirname(__file__))
from prepare_qingniao import prepare as bird_source,remodel as bird_remodel
from prepare_qitu import cut,export
from turnaround import setup_render,render_views,smoothstep

HEAD_SCALE=.63
HEAD_CUT=.76
# Five low/front faces and four high/rear faces: nine, not nine plus a native bird head.
LAYOUT=[(x,-.245,.98,-x*.18) for x in [-.42,-.21,0,.21,.42]]+[(x,.01,1.23,-x*.18) for x in [-.315,-.105,.105,.315]]


def remodel(p):
    q=bird_remodel(p);q.x*=1.35
    return q


def prepare_body(path):
    obj,original=bird_source(path)
    for v,p in zip(obj.data.vertices,original):v.co=remodel(Vector(p))
    image=next(n.image for n in obj.active_material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'diffuse' in n.image.name)
    px=np.array(image.pixels[:],dtype=np.float32).reshape(image.size[1],image.size[0],4)
    value=px[:,:,:3].max(axis=2);px[:,:,:3]=np.array([.25,.36,.42])*(.60+.65*value[:,:,None])
    image.pixels.foreach_set(px.ravel());image.pack();obj.data.update();obj.name='jiufeng_bird_torso'
    return obj,original


def trim(obj):
    cut(obj,(0,0,HEAD_CUT),(0,0,1))
    # Taper the removed native neck rim into the shoulders before covering it;
    # otherwise an exposed planar shelf remains below the nine narrow roots.
    for v in obj.data.vertices:
        w=smoothstep(.59,HEAD_CUT,v.co.z);factor=1-.25*w
        v.co.x*=factor;v.co.y=-.14+(v.co.y+.14)*factor
    obj.data.update()


def layout(obj):
    result=[]
    for i,(x,y,z,yaw) in enumerate(LAYOUT):
        bx=(x/.42)*(.14 if i<5 else .15);by=-.235 if i<5 else -.035
        hit,p,_,_=obj.ray_cast(Vector((bx,by,1.5)),Vector((0,0,-1)))
        if not hit:raise RuntimeError(f'Neck root {i} missed torso')
        base=p-Vector((0,0,.028));end=Vector((x,y,z+.012))
        result.append((base,end,yaw))
    return result


def curve(base,end,t):
    a=base+Vector((0,0,.14));b=end-Vector((0,0,.11))
    p=(1-t)**3*base+3*(1-t)**2*t*a+3*(1-t)*t*t*b+t**3*end
    tangent=3*(1-t)**2*(a-base)+6*(1-t)*t*(b-a)+3*t*t*(end-b)
    return p,tangent.normalized()


def neck_material():
    mat=bpy.data.materials.new('original_slate_feather_necks');mat.use_nodes=True
    image=bpy.data.images.new('jiufeng_neck_feather_wash',width=64,height=64);pixels=[]
    for row in range(64):
        for col in range(64):
            fx=(col/64*8+math.floor(row/64*8)*.5)%1;fy=(row/64*8)%1
            shade=.83+.08*math.cos(fx*math.tau)*math.sin(fy*math.pi)+.09*math.exp(-((fy-abs(fx-.5)*.7-.15)/.08)**2)
            pixels.extend((.25*shade,.36*shade,.42*shade,1))
    image.pixels.foreach_set(pixels);image.pack();tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    bsdf=mat.node_tree.nodes.get('Principled BSDF');mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color']);bsdf.inputs['Roughness'].default_value=.9
    return mat


def neck_mesh(base,end,index,mat):
    sides=20;rings=24;verts=[];faces=[]
    for i in range(rings+1):
        t=i/rings;p,tangent=curve(base,end,t)
        axis=tangent.cross(Vector((0,1,0))).normalized();other=tangent.cross(axis).normalized()
        radius=.046*(1-t)+.029*t
        for j in range(sides):
            a=j*math.tau/sides;r=radius*(1+.12*math.cos(a*4+t*math.tau*9))
            verts.append(tuple(p+r*(math.cos(a)*axis+math.sin(a)*other)))
    for i in range(rings):
        for j in range(sides):
            a=i*sides+j;b=i*sides+(j+1)%sides;faces.append((a,b,b+sides,a+sides))
    faces.append(tuple(reversed(range(sides))));faces.append(tuple(rings*sides+j for j in range(sides)))
    mesh=bpy.data.meshes.new(f'jiufeng_neck_{index}');mesh.from_pydata(verts,[],faces);mesh.update()
    uv=mesh.uv_layers.new(name='UVMap')
    for loop in mesh.loops:uv.data[loop.index].uv=((loop.vertex_index%sides)/sides,(loop.vertex_index//sides)/rings)
    obj=bpy.data.objects.new(f'jiufeng_neck_{index}',mesh);bpy.context.scene.collection.objects.link(obj);mesh.materials.append(mat)
    for f in mesh.polygons:f.use_smooth=True
    return obj


def shoulder_ruff(mat):
    # Original feathered shoulder dome covers the removal cap and buries all nine
    # neck roots; this is new offline geometry, not an extra generated HIGH part.
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=1,location=(0,-.13,.70))
    obj=bpy.context.object;obj.name='jiufeng_original_shoulder_ruff'
    for v in obj.data.vertices:
        a=math.atan2(v.co.y,v.co.x);v.co*=1+.025*math.cos(a*10+v.co.z*math.pi*7)
    obj.scale=(.25,.23,.14);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    # Apply location so joined skinned vertices share the torso's coordinate space.
    bpy.ops.object.transform_apply(location=True,rotation=False,scale=False)
    obj.data.materials.append(mat)
    for p in obj.data.polygons:p.use_smooth=True
    return obj


def load_head(path):
    before=set(bpy.context.scene.objects);bpy.ops.import_scene.gltf(filepath=path)
    meshes=[o for o in bpy.context.scene.objects if o not in before and o.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:o.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    if len(meshes)>1:bpy.ops.object.join()
    obj=bpy.context.view_layer.objects.active;bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    for o in list(bpy.context.scene.objects):
        if o not in before and o is not obj:bpy.data.objects.remove(o,do_unlink=True)
    for mat in obj.data.materials:
        for n in mat.node_tree.nodes:
            if n.type=='TEX_IMAGE' and n.image and max(n.image.size)>1024:n.image.scale(1024,1024);n.image.pack()
    obj.name='jiufeng_human_head'
    return obj


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:];os.makedirs(args[2],exist_ok=True);os.makedirs(args[3],exist_ok=True)
    body,_=prepare_body(args[0]);trim(body);mounts=layout(body);head=load_head(args[1]);export(f'{args[2]}/head_norm.glb',[head])
    mat=neck_material();pieces=[body,shoulder_ruff(mat)]
    for i,(base,end,yaw) in enumerate(mounts):
        pieces.append(neck_mesh(base,end,i,mat));part=bpy.data.objects.new(f'human_face_{i}',head.data.copy());bpy.context.scene.collection.objects.link(part)
        part.location=end-Vector((0,0,.012));part.rotation_euler.z=yaw;part.scale=(HEAD_SCALE,)*3;pieces.append(part)
    bpy.data.objects.remove(head,do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    for o in pieces:o.select_set(True)
    bpy.context.view_layer.objects.active=body;bpy.ops.object.join();render_views(body,setup_render(1024),args[3])
    print('EXACT_NINE_HUMAN_FACES roots',[(list(a),list(b)) for a,b,_ in mounts])
