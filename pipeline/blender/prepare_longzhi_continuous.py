"""Longzhi: reconstruct continuous muscular roots from the reviewed 20261115 layout.

Offline derivative, never a new Rodin generation. Run with --disable-autoexec.
The source layout and its manifest are explicit arguments; no shared raw is written.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import bpy
import bmesh
from mathutils import Matrix, Vector
import numpy as np
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform


def select(objects):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def smoothstep(t):
    t = max(0., min(1., t))
    return t*t*(3-2*t)


def roots(obj, anchor, role, row):
    """Flare the original lower neck/tail, with a C1 falloff into untouched skin."""
    points = [v.co.copy() for v in obj.data.vertices]
    if role == 'head':
        # Work along the rising neck, retaining the whole original skull.
        length = [.115, .195, .285][row]
        from bisect import bisect_left, bisect_right
        ordered = sorted(points, key=lambda p: p.z)
        heights = [p.z for p in ordered]
        for vertex in obj.data.vertices:
            q = vertex.co
            h = q.z-anchor.z
            t = max(0., min(1., h/length))
            if h > length:
                continue
            # Estimate the actual curved neck center from a thin source slice.
            band = ordered[bisect_left(heights,q.z-.004):bisect_right(heights,q.z+.004)]
            if not band:
                continue
            center = sum(band, Vector())/len(band)
            center.z = q.z
            factor = 1 + 2.7*(1-smoothstep(t))**2
            q.x = center.x+(q.x-center.x)*factor
            q.y = center.y+(q.y-center.y)*factor
            q.z -= .024*(1-smoothstep(t))
    else:
        # Tail's original cap-to-tip axis, transformed with the real source node.
        far = max(points, key=lambda p: (p-anchor).length)
        axis = (far-anchor).normalized()
        from bisect import bisect_left,bisect_right
        sections=sorted(((p-anchor).dot(axis),p) for p in points)
        levels=[p[0] for p in sections]
        for vertex in obj.data.vertices:
            delta = vertex.co-anchor
            h = delta.dot(axis)
            t = max(0., min(1., h/.14))
            if h > .14:
                continue
            band=[p for _,p in sections[bisect_left(levels,h-.005):bisect_right(levels,h+.005)]]
            center=sum(band,Vector())/len(band) if band else anchor+axis*h
            center+=axis*(h-(center-anchor).dot(axis))
            radial=vertex.co-center
            radius=max((p-center).length for p in band) if band else .01
            scale=1+max(0,.047/max(radius,.003)-1)*(1-smoothstep(t))
            vertex.co=center-axis*.035*(1-smoothstep(t))+radial*scale
    obj.data.update()


def neck_coat():
    size=512
    u,v=np.meshgrid(np.linspace(0,1,size),np.linspace(0,1,size))
    rng=np.random.default_rng(17)
    noise=rng.random((size,size))-.5
    short_fur=.035*np.sin(137*u+4*np.sin(65*v))+.018*np.sin(331*u+9*np.sin(123*v))+.035*noise
    cream=np.exp(-((u-.5)/.16)**4)*smoothstep(1.)
    cream*=np.clip((v-.56)/.35,0,1)
    coat=np.ones((size,size,4),np.float32)
    brown=np.array([.52,.225,.085]);white=np.array([.79,.73,.60])
    coat[:,:,:3]=brown[None,None,:]*(1-cream[:,:,None])+white[None,None,:]*cream[:,:,None]+short_fur[:,:,None]
    coat[:,:,:3]=np.clip(coat[:,:,:3],0,1)
    image=bpy.data.images.new('painted_short_fur_neck_transition',width=size,height=size)
    image.pixels.foreach_set(coat.ravel());image.pack()
    mat=bpy.data.materials.new('sculpted_neck_coat');mat.use_nodes=True
    shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Roughness'].default_value=.9
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    mat.node_tree.links.new(tex.outputs['Color'],shader.inputs['Base Color'])
    return mat


def rebuild_neck(obj,item,coat):
    """Keep the complete native cranium; replace only the lower anatomical neck."""
    matrix=Matrix(item['worldBlenderMatrix'])
    collar_raw=Vector((0,(.10+.00022119526734331785)/.5261648629514518,(.44-.5001471812547346)/.5261648629514518))
    collar=matrix@collar_raw
    normal=(matrix.to_3x3()@Vector((0,0,1))).normalized()
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-6,plane_co=collar,plane_no=normal,clear_inner=True)
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
    border=[e for e in bm.edges if e.is_boundary and all(abs((v.co-collar).dot(normal))<2e-5 for v in e.verts)]
    neighbors={}
    for edge in border:
        a,b=edge.verts;neighbors.setdefault(a,[]).append(b);neighbors.setdefault(b,[]).append(a)
    assert neighbors and all(len(n)==2 for n in neighbors.values()),obj.name
    start=next(iter(neighbors));ring=[start];previous=None;current=start
    while True:
        nxt=next(v for v in neighbors[current] if v is not previous)
        if nxt is start:break
        ring.append(nxt);previous,current=current,nxt
    assert len(ring)==len(neighbors)
    top=[v.co.copy() for v in ring];center=sum(top,Vector())/len(top)
    root=Vector(item['targetEmbeddedAnchor'])-Vector((0,-.012,.048))
    offset=[p-center for p in top]
    axisx=(matrix.to_3x3()@Vector((1,0,0))).normalized()
    axisy=normal.cross(axisx).normalized()
    rx=max(abs(p.dot(axisx)) for p in offset);ry=max(abs(p.dot(axisy)) for p in offset)
    angles=[math.atan2(p.dot(axisy)/ry,p.dot(axisx)/rx) for p in offset]
    material_index=len(obj.data.materials);obj.data.materials.append(coat)
    uv=bm.loops.layers.uv.active
    n=len(ring);last=None;rings=36
    for row in range(rings):
        t=row/rings
        # Cubic broad scapular origin, neck narrows gradually under the jaw.
        c=root.lerp(center,t)+Vector((0,.015*math.sin(math.pi*t),0))
        tangent=(center-root).normalized()
        xx=(axisx-tangent*axisx.dot(tangent)).normalized();yy=tangent.cross(xx).normalized()
        radius=.061*(1-smoothstep(t/.8))+.023*smoothstep(t/.8)
        generated=[]
        blend=smoothstep((t-.78)/.22)
        for j,angle in enumerate(angles):
            regular=xx*radius*math.cos(angle)+yy*radius*.82*math.sin(angle)
            q=c+regular.lerp(offset[j],blend)
            generated.append(bm.verts.new(q))
        if last:
            for j in range(n):
                k=(j+1)%n;face=bm.faces.new((last[j],last[k],generated[k],generated[j]));face.material_index=material_index;face.smooth=True
                for loop in face.loops:
                    angle=angles[j] if loop.vert in (last[j],generated[j]) else angles[k]
                    loop[uv].uv=((angle/math.tau+.5)%1,t if loop.vert in generated else (row-1)/rings)
        else:bm.faces.new(tuple(reversed(generated)))
        last=generated
    for j in range(n):
        k=(j+1)%n;face=bm.faces.new((last[j],last[k],ring[k],ring[j]));face.material_index=material_index;face.smooth=True
        for loop in face.loops:loop[uv].uv=(j/n,1 if loop.vert in ring else (rings-1)/rings)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free();obj.data.update()
    return {'root':list(root),'collar':list(center),'axis':list(normal),'name':obj.name,'row':item['row']}


def union(objects, voxel, ratio):
    select(objects)
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = 'longzhi_continuous_skin'
    reference = obj.copy()
    reference.data = obj.data.copy()
    reference.name = 'source_surface_for_texture_transfer'
    bpy.context.collection.objects.link(reference)
    reference.hide_render = True
    reference.hide_set(True)
    select([obj])
    remesh = obj.modifiers.new('continuous_anatomical_volume', 'REMESH')
    remesh.mode = 'VOXEL'
    remesh.voxel_size = voxel
    remesh.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    group = obj.vertex_groups.new(name='sculpted_root_transition')
    for vertex in obj.data.vertices:
        q = vertex.co
        front = smoothstep((q.z-.49)/.11)*(1-smoothstep((q.z-.72)/.15))*(1-smoothstep((q.y+.16)/.1))
        rear = smoothstep((q.z-.45)/.09)*(1-smoothstep((q.z-.76)/.1))*smoothstep((q.y-.21)/.10)
        weight = max(front, rear)
        if weight > .001:
            group.add([vertex.index], weight, 'REPLACE')
    smooth = obj.modifiers.new('muscular_root_relaxation', 'SMOOTH')
    smooth.vertex_group = group.name
    smooth.factor = 1.2
    smooth.iterations = 14
    bpy.ops.object.modifier_apply(modifier=smooth.name)
    decimate = obj.modifiers.new('surface_budget', 'DECIMATE')
    decimate.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=decimate.name)
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-7)
    bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
    for face in obj.data.polygons:
        face.use_smooth = True
    print('CONTINUOUS_SURFACE', len(obj.data.vertices), len(obj.data.polygons), flush=True)
    return obj, reference


def transfer(obj, reference):
    mesh = reference.data
    mesh.calc_loop_triangles()
    triangles = list(mesh.loop_triangles)
    coords = [v.co.copy() for v in mesh.vertices]
    tree = BVHTree.FromPolygons(coords, [list(t.vertices) for t in triangles], all_triangles=True)
    layer = mesh.uv_layers.active
    for uv in list(obj.data.uv_layers):
        obj.data.uv_layers.remove(uv)
    dest = obj.data.uv_layers.new(name='TransferredSourceAtlas')
    source_color=mesh.color_attributes.get('ContinuousConceptCoat') or (mesh.color_attributes[0] if mesh.color_attributes else None)
    target_color=obj.data.color_attributes.new(name='ContinuousConceptCoat',type='FLOAT_COLOR',domain='CORNER') if source_color else None
    obj.data.materials.clear()
    for material in mesh.materials:
        obj.data.materials.append(material)
    for face in obj.data.polygons:
        hit, normal, index, distance = tree.find_nearest(face.center)
        tri = triangles[index]
        face.material_index = tri.material_index
        p = [coords[i] for i in tri.vertices]
        uv = [Vector((*layer.data[i].uv, 0)) for i in tri.loops]
        for loop in face.loop_indices:
            q = obj.data.vertices[obj.data.loops[loop].vertex_index].co
            projected = barycentric_transform(q, *p, *uv)
            dest.data[loop].uv = projected.xy
            if source_color:
                values=[Vector(source_color.data[i].color[:3]) for i in tri.loops]
                color=barycentric_transform(q,*p,*values)
                target_color.data[loop].color=(*[max(0,min(1,value)) for value in color],1)
    # Source tangent maps are invalid on newly reconstructed UV triangles.
    # Neutral geometric normals remain valid; final normals are rebaked later.
    for material in obj.data.materials:
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type=='VERTEX_COLOR' and target_color:node.layer_name=target_color.name
            bsdf = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                for link in list(bsdf.inputs['Normal'].links):
                    material.node_tree.links.remove(link)
                for name in ['Roughness','Metallic']:
                    for link in list(bsdf.inputs[name].links):
                        material.node_tree.links.remove(link)
                bsdf.inputs['Roughness'].default_value = .86
                bsdf.inputs['Metallic'].default_value = 0
    return tree


def render(obj, out, size):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    world = bpy.data.worlds.new('studio')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.55,.57,.60,1)
    world.node_tree.nodes['Background'].inputs[1].default_value = .8
    scene.world = world
    for i,(pos,energy) in enumerate([((2,-3,4),240),((-3,1,2),210),((1,3,3),180)]):
        light = bpy.data.objects.new('softbox_'+str(i), bpy.data.lights.new('softbox_'+str(i),'AREA'))
        scene.collection.objects.link(light)
        light.location = pos
        light.rotation_euler = (Vector((0,0,.65))-light.location).to_track_quat('-Z','Y').to_euler()
        light.data.energy = energy
        light.data.size = 3
    points = [v.co for v in obj.data.vertices]
    lo = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (lo+hi)*.5
    extent = max(hi-lo)*1.13
    views = [('front',center,(0,-1,.08),extent),('side',center,(1,0,.08),extent),('back',center,(0,1,.08),extent),('34',center,(.8,-1,.32),extent),('shoulder',Vector((0,-.30,.77)),(.7,-1,.35),.73),('nape',Vector((0,-.21,.8)),(1,1,.4),.78),('rump',Vector((0,.35,.68)),(.8,1,.4),.74)]
    for name,target,direction,scale in views:
        camera = bpy.data.objects.new(name,bpy.data.cameras.new(name))
        scene.collection.objects.link(camera)
        camera.location = target+Vector(direction).normalized()*4
        camera.rotation_euler = (target-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type = 'ORTHO'
        camera.data.ortho_scale = scale
        scene.camera = camera
        scene.render.filepath = str(out/(name+'.png'))
        bpy.ops.render.render(write_still=True)
        print('VIEW',name,flush=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True,type=Path)
    ap.add_argument('--manifest',required=True,type=Path)
    ap.add_argument('--head-reference',type=Path)
    ap.add_argument('--output-dir',required=True,type=Path)
    ap.add_argument('--voxel',type=float,default=.0018)
    ap.add_argument('--ratio',type=float,default=.22)
    ap.add_argument('--render-size',type=int,default=1000)
    args=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    out=args.output_dir.resolve()
    out.mkdir(parents=True,exist_ok=False)
    before=hashlib.sha256(args.input.read_bytes()).hexdigest()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))
    manifest=json.loads(args.manifest.read_text())
    placement={item['name']:item for item in manifest['nodes']}
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    mother=None
    if args.head_reference:
        previous=set(bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(args.head_reference))
        mother=next(o for o in bpy.context.scene.objects if o not in previous and o.type=='MESH')
        select([mother]);bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
        mother.hide_render=True;mother.hide_set(True)
    coat=neck_coat()
    anatomy=[]
    for obj in meshes:
        obj.data = obj.data.copy()
        select([obj])
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
        item=placement.get(obj.name)
        if item and item['role']=='head':
            if mother:
                obj.data=mother.data.copy()
                rotation=Matrix(item['worldBlenderMatrix']).to_3x3().normalized()
                root=Vector(item['targetEmbeddedAnchor'])-Vector((0,0,.052))
                collar=.37;length=[.16,.26,.36][item['row']]
                for vertex in obj.data.vertices:
                    q=vertex.co.copy()
                    q.z=q.z*length/collar if q.z<collar else q.z-collar+length
                    vertex.co=root+rotation@q
                anatomy.append({'root':list(root),'collar':list(root+rotation@Vector((0,0,length))),'name':obj.name,'row':item['row']})
            else:
                anatomy.append(rebuild_neck(obj,item,coat))
        elif 'tail' in obj.name:
            # Posefix tail anchors are stored in actual glTF extras.
            anchor=obj.get('targetEmbeddedAnchor')
            if anchor is not None:
                roots(obj,Vector(anchor),'tail',0)
            else:
                # Original tail vertices converge at the negative local axis;
                # the nearest point to the rump is a reliable bounded root.
                anchor=min((v.co for v in obj.data.vertices),key=lambda q:(q-Vector((0,.32,.60))).length).copy()
                roots(obj,anchor,'tail',0)
    if mother:bpy.data.objects.remove(mother,do_unlink=True)
    for mesh in meshes:
        for index,material in enumerate(mesh.data.materials):
            if material:
                copied=material.copy();copied.name=mesh.name+'__'+str(index)
                mesh.data.materials[index]=copied
    (out/'anatomy.json').write_text(json.dumps(anatomy,indent=2)+'\n')
    obj,reference=union(meshes,args.voxel,args.ratio)
    transfer(obj,reference)
    select([obj])
    bpy.ops.export_scene.gltf(filepath=str(out/'candidate.glb'),export_format='GLB',use_selection=True,export_animations=False)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'candidate.blend'))
    bm=bmesh.new();bm.from_mesh(obj.data)
    audit={'input':str(args.input),'sourceSha256':before,'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons),'boundaryEdges':sum(e.is_boundary for e in bm.edges),'nonManifoldEdges':sum(not e.is_manifold for e in bm.edges),'voxel':args.voxel,'ratio':args.ratio,'paidCalls':0,'accepted':False,'note':'New derivative mesh; source TBN maps removed pending rebake; actual images require review.'}
    bm.free()
    (out/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    render(obj,out,args.render_size)
    assert hashlib.sha256(args.input.read_bytes()).hexdigest()==before

if __name__=='__main__':
    main()
