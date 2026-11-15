"""Native High Kuafu: local wrist-domain replacement, protected body audit.

Blender --background --factory-startup --disable-autoexec --python-exit-code 1
 --python pipeline/blender/prepare_kuafu.py -- --body-in BODY --hand-in HAND --out-dir NEW
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector


def load(path, name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in set(bpy.data.objects) - before if o.type == 'MESH']
    assert len(meshes) == 1
    obj = meshes[0]
    transform = obj.matrix_world.copy()
    normal_matrix=transform.to_3x3().inverted().transposed()
    normals=[(normal_matrix@n.vector).normalized() for n in obj.data.corner_normals]
    obj.parent = None
    obj.matrix_world = Matrix.Identity(4)
    for vertex in obj.data.vertices:
        vertex.co = transform @ vertex.co
    points = [v.co for v in obj.data.vertices]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    center = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
    for vertex in obj.data.vertices:
        vertex.co = (vertex.co - center) / (high.z - low.z)
    obj.data.update()
    obj.data.normals_split_custom_set(normals)
    obj.name = name
    return obj


def protected(p):
    return p.z < .30 or abs(p.x) < .12 or (p.z > .72 and abs(p.x) < .18 and p.y > -.03)


def frozen_digest(mesh):
    # Position/UV triangle hashes survive index changes and seam-aware welding.
    records = []
    uv = mesh.uv_layers.active
    for poly in mesh.polygons:
        if all(protected(mesh.vertices[i].co) for i in poly.vertices):
            corners = [(tuple(mesh.vertices[mesh.loops[i].vertex_index].co), tuple(uv.data[i].uv))
                       for i in poly.loop_indices]
            records.append(min(tuple(corners[i:]+corners[:i]) for i in range(len(corners))))
    return len(records), hashlib.sha256(repr(sorted(records)).encode()).hexdigest()


def ordered_loop(edges):
    pending = set(edges)
    assert pending
    first = next(iter(pending))
    ordered = [first.verts[0]]
    edge, vertex = first, first.verts[0]
    while True:
        pending.remove(edge)
        vertex = edge.other_vert(vertex)
        if vertex is ordered[0]:
            break
        ordered.append(vertex)
        options = [e for e in vertex.link_edges if e in pending]
        assert len(options) == 1, ('not a single ring', len(options), len(pending))
        edge = options[0]
    assert not pending, ('multiple boundary rings', len(pending))
    return ordered


def cut_wrist(obj, sign):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=[v for v in bm.verts if not protected(v.co)], dist=1e-7)
    center = Vector((sign * .195, .030, .626))
    axis = Vector((sign * .55, -.835, .02)).normalized()
    def near(p):
        d = p - center
        return d.length < .105 and abs(d.dot(axis)) < .045
    faces = [f for f in bm.faces if any(near(v.co) for v in f.verts)]
    vertices = {v for f in faces for v in f.verts}
    edges = {e for f in faces for e in f.edges}
    result = bmesh.ops.bisect_plane(bm, geom=list(vertices) + list(edges) + faces,
                                  plane_co=center, plane_no=axis, dist=1e-7,
                                  clear_outer=False, clear_inner=False)
    cut_edges = {e for e in result['geom_cut'] if isinstance(e, bmesh.types.BMEdge)}
    seed = min(bm.faces, key=lambda f: (f.calc_center_median() - Vector((sign * .24, -.10, .65))).length)
    selected, stack = {seed}, [seed]
    while stack:
        face = stack.pop()
        for edge in face.edges:
            if edge in cut_edges:
                continue
            for other in edge.link_faces:
                if other not in selected:
                    selected.add(other)
                    stack.append(other)
    assert 500 < len(selected) < 12000, ('unexpected hand domain', len(selected))
    assert not any(protected(v.co) for f in selected for v in f.verts), 'Cut touches frozen torso/legs'
    boundary = [e for e in cut_edges if any(f in selected for f in e.link_faces)
                and any(f not in selected for f in e.link_faces)]
    ring = ordered_loop(boundary)
    # Keep the actual old hand/snake domain for independent separation review.
    removed = obj.copy()
    removed.data = obj.data.copy()
    removed.name = f'old_hand_snake_{sign}'
    bpy.context.collection.objects.link(removed)
    bm.faces.index_update()
    chosen = {f.index for f in selected}
    rbm = bm.copy()
    rbm.faces.ensure_lookup_table()
    bmesh.ops.delete(rbm, geom=[f for f in rbm.faces if f.index not in chosen], context='FACES')
    rbm.to_mesh(removed.data)
    rbm.free()
    removed.hide_render = True
    removed.hide_set(True)
    removed['native_removed_faces'] = len(selected)
    bmesh.ops.delete(bm, geom=list(selected), context='FACES')
    # Clean orphaned native hand vertices, but retain boundary vertices.
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    ring = [v for v in ring if v.is_valid]
    assert len(ring) >= 12
    positions = [v.co.copy() for v in ring]
    bm.to_mesh(obj.data)
    bm.free()
    return dict(center=center, axis=axis, positions=positions, removed=removed)


def diffuse_image(obj):
    material = obj.data.materials[0]
    shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    return shader.inputs['Base Color'].links[0].from_node.image


def sample_colors(obj, points):
    image = diffuse_image(obj)
    width, height = image.size
    values = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(values)
    values = values.reshape(height, width, 4)
    uv = obj.data.uv_layers.active
    coordinates = {tuple(round(c, 6) for c in p) for p in points}
    colors = {key:[] for key in coordinates}
    for loop in obj.data.loops:
        p = obj.data.vertices[loop.vertex_index].co
        key=tuple(round(c,6)for c in p)
        if key in coordinates:
            u, v = uv.data[loop.index].uv
            colors[key].append(values[min(height-1, max(0, int(v*height))),
                                      min(width-1, max(0, int(u*width))), :3])
    assert all(colors.values())
    return np.array([np.mean(colors[tuple(round(c,6)for c in p)],axis=0)for p in points])


def sample_color(obj,points):
    return np.median(sample_colors(obj,points),axis=0)


def tint_hand(obj, target, root_points, out_dir):
    original = sample_color(obj, root_points)
    image = diffuse_image(obj)
    width, height = image.size
    values = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(values)
    pixels = values.reshape(height, width, 4)
    ratio = target / np.maximum(original, .05)
    pixels[..., :3] = np.clip(pixels[..., :3] * ratio, 0, 1)
    image.pixels.foreach_set(values)
    image.update()
    path = out_dir / (obj.name + '-matched-skin.png')
    image.filepath_raw, image.file_format = str(path.resolve()), 'PNG'
    image.save()
    replacement = bpy.data.images.load(str(path.resolve()), check_existing=False)
    replacement.pack()
    for node in obj.data.materials[0].node_tree.nodes:
        if getattr(node, 'image', None) is image:
            node.image = replacement
    return list(map(float, ratio))


def gradient_material(name,colors_a,angles_a,colors_b,angles_b,out_dir):
    width,height=256,64
    theta=np.arange(width)/width*math.tau
    def periodic(colors,angles):
        angles=np.array(angles)
        return np.stack([np.interp(theta,np.r_[angles[-1]-math.tau,angles,angles[0]+math.tau],
                                  np.r_[colors[-1,c],colors[:,c],colors[0,c]])for c in range(3)],axis=1)
    a,b=periodic(colors_a,angles_a),periodic(colors_b,angles_b)
    t=np.linspace(0,1,height)[:,None,None]
    pixels=np.ones((height,width,4),np.float32);pixels[...,:3]=a[None]*(1-t)+b[None]*t
    image=bpy.data.images.new(name+'-gradient',width=width,height=height)
    image.colorspace_settings.name='sRGB';image.pixels.foreach_set(pixels.ravel());image.update()
    path=(out_dir/(name+'-gradient.png')).resolve();image.filepath_raw=str(path);image.file_format='PNG';image.save()
    packed=bpy.data.images.load(str(path),check_existing=False);packed.pack()
    material=bpy.data.materials.new(name);material.use_nodes=True
    texture=material.node_tree.nodes.new('ShaderNodeTexImage');texture.image=packed
    shader=material.node_tree.nodes.get('Principled BSDF')
    material.node_tree.links.new(texture.outputs['Color'],shader.inputs['Base Color'])
    shader.inputs['Roughness'].default_value=.68
    return material


def bridge_uv(mesh,rings,angles):
    values=[(theta/math.tau,k/(len(rings)-1))for k,aa in enumerate(angles)for theta in aa]
    uv=mesh.uv_layers.new(name='UVMap')
    for polygon in mesh.polygons:
        coords=[values[mesh.loops[i].vertex_index]for i in polygon.loop_indices]
        wrap=max(p[0]for p in coords)-min(p[0]for p in coords)>.5
        for i,(u,v)in zip(polygon.loop_indices,coords):uv.data[i].uv=(u+1 if wrap and u<.5 else u,v)


def zipper(faces, start_a, count_a, angles_a, start_b, count_b, angles_b):
    i=j=0
    while i<count_a or j<count_b:
        ni=angles_a[(i+1)%count_a]+(math.tau if i+1>=count_a else 0) if i<count_a else float('inf')
        nj=angles_b[(j+1)%count_b]+(math.tau if j+1>=count_b else 0) if j<count_b else float('inf')
        ai=start_a+i%count_a; bj=start_b+j%count_b
        if ni<nj:
            faces.append((ai,start_a+(i+1)%count_a,bj));i+=1
        else:
            faces.append((ai,start_b+(j+1)%count_b,bj));j+=1


def add_hand(body, source, result, sign, out_dir):
    hand = load(source, f'kuafu_hand_{sign}')
    bm = bmesh.new()
    bm.from_mesh(hand.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
    bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                          plane_co=(0,0,.18), plane_no=(0,0,1), dist=1e-7,
                          clear_inner=True, clear_outer=False)
    boundary = [e for e in bm.edges if e.is_boundary and all(abs(v.co.z-.18)<1e-5 for v in e.verts)]
    local_root = ordered_loop(boundary)
    local_center = sum((v.co for v in local_root), Vector())/len(local_root)
    hand_root_points = [v.co.copy() for v in local_root]
    bm.to_mesh(hand.data)
    body_ring = result['positions']
    center = sum(body_ring, Vector()) / len(body_ring)
    color = sample_color(body, body_ring)
    ratio = tint_hand(hand, color, hand_root_points, out_dir)
    axis = result['axis']
    a = Vector((0,0,-1))
    a = (a - axis*a.dot(axis)).normalized()
    # Mirror the left hand's actual geometry and winding, never a negative scale.
    b = Vector((.835*sign,.55,0)).normalized()
    b = (b-axis*b.dot(axis)-a*b.dot(a)).normalized()
    length, scale = .028, .145
    destination = center + axis*length
    transformed_root = []
    for v in bm.verts:
        p = (v.co-local_center)*scale
        v.co = destination + a*p.x + b*p.y + axis*p.z
    if sign < 0:
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    transformed_root = [v.co.copy() for v in local_root]
    bm.to_mesh(hand.data)
    bm.free()

    def angle(p, origin):
        d=p-origin
        return math.atan2(d.dot(b), d.dot(a)) % math.tau
    body_ring.sort(key=lambda p: angle(p, center))
    transformed_root.sort(key=lambda p: angle(p, destination))
    ha=[angle(p,destination) for p in transformed_root]
    ba=[angle(p,center) for p in body_ring]
    def radial(theta):
        k=next((i for i,t in enumerate(ha) if t>theta),len(ha))
        i,j=(k-1)%len(ha),k%len(ha)
        t0,t1=ha[i],ha[j]
        if j==0:t1+=math.tau
        if theta<t0:theta+=math.tau
        f=(theta-t0)/max(1e-8,t1-t0)
        return (transformed_root[i]-destination).lerp(transformed_root[j]-destination,f)
    rings=[body_ring]
    for step in range(1,4):
        t=step/4
        rings.append([center+axis*(length*t)+(p-center)*(1-t)+radial(theta)*t
                      for p,theta in zip(body_ring,ba)])
    rings.append(transformed_root)
    points=[tuple(p) for ring in rings for p in ring]
    faces=[]
    offsets=[sum(len(r) for r in rings[:k]) for k in range(len(rings))]
    for k in range(len(rings)-1):
        n,m=len(rings[k]),len(rings[k+1])
        aa=ba
        bb=ha if k==len(rings)-2 else ba
        i=j=0
        # Zipper unequal loops in polar order; no cap, overlap or detached sleeve.
        while i<n or j<m:
            ni=aa[(i+1)%n]+(math.tau if i+1>=n else 0) if i<n else float('inf')
            nj=bb[(j+1)%m]+(math.tau if j+1>=m else 0) if j<m else float('inf')
            ai=offsets[k]+i%n; bj=offsets[k+1]+j%m
            if ni<nj:
                faces.append((ai,offsets[k]+(i+1)%n,bj));i+=1
            else:
                faces.append((ai,offsets[k+1]+(j+1)%m,bj));j+=1
    mesh=bpy.data.meshes.new(f'wrist_bridge_{sign}')
    if sign<0:faces=[tuple(reversed(f))for f in faces]
    mesh.from_pydata(points,[],faces)
    mesh.update()
    bridge=bpy.data.objects.new(f'kuafu_wrist_bridge_{sign}',mesh)
    bpy.context.collection.objects.link(bridge)
    bridge_uv(mesh,rings,[ba,ba,ba,ba,ha])
    material=gradient_material(f'matched_wrist_skin_{sign}',sample_colors(body,body_ring),ba,
                               sample_colors(hand,transformed_root),ha,out_dir)
    mesh.materials.append(material)
    for p in mesh.polygons:p.use_smooth=True
    return hand,bridge,dict(side=sign,scale=scale,bridgeLength=length,handRootVertices=len(ha),
                            skinMultiplier=ratio,support=list(destination+axis*.080+b*(-.10*scale)))


def recover_held_snake(removed, sign, support, out_dir):
    parts, roots = [], []
    for label,z,keep_low in [('lower',.575,True),('upper',.735,False)]:
        obj=bpy.data.objects.new(f'kuafu_held_{sign}_{label}',removed.data.copy())
        bpy.context.collection.objects.link(obj)
        bm=bmesh.new();bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-7)
        bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                              plane_co=(0,0,z),plane_no=(0,0,1),dist=1e-7,
                              clear_inner=not keep_low,clear_outer=keep_low)
        boundary=[e for e in bm.edges if e.is_boundary and all(abs(v.co.z-z)<1e-5 for v in e.verts)]
        root=[v.co.copy() for v in ordered_loop(boundary)]
        bm.to_mesh(obj.data);bm.free()
        parts.append(obj);roots.append(root)
    centers=[sum(root,Vector())/len(root) for root in roots]
    angles=[]
    for root,center in zip(roots,centers):
        root.sort(key=lambda p: math.atan2(p.y-center.y,p.x-center.x)%math.tau)
        angles.append([math.atan2(p.y-center.y,p.x-center.x)%math.tau for p in root])
    radius=[sum((p-center).length for p in root)/len(root) for root,center in zip(roots,centers)]
    support=Vector(support)
    # The old fused hand/skin/snake region is entirely discarded. Only clean
    # native distal snake surfaces remain, joined by a new yellow middle tube.
    tangents=[]
    for obj,center,direction in zip(parts,centers,[-1,1]):
        nearby=[v.co for v in obj.data.vertices if abs(v.co.z-(center.z+direction*.015))<.003]
        assert nearby
        neighbor=sum(nearby,Vector())/len(nearby)
        tangent=(neighbor-center)/(neighbor.z-center.z)
        tangent.x=max(-2,min(2,tangent.x));tangent.y=max(-2,min(2,tangent.y))
        tangents.append(tangent)
    middle_tangent=(centers[1]-centers[0])/(centers[1].z-centers[0].z)
    def path(z):
        low,high=centers
        if z<support.z:p,q,dp,dq=low,support,tangents[0],middle_tangent
        else:p,q,dp,dq=support,high,middle_tangent,tangents[1]
        dz=q.z-p.z;t=(z-p.z)/dz
        return p*(2*t**3-3*t*t+1)+dp*(dz*(t**3-2*t*t+t))+q*(-2*t**3+3*t*t)+dq*(dz*(t**3-t*t))
    rings=[roots[0]]
    for step in range(1,24):
        t=step/24;z=centers[0].z*(1-t)+centers[1].z*t
        center=path(z)
        r=radius[0]*(1-t)+radius[1]*t
        r*=1-.10*math.sin(t*math.pi)
        rings.append([center+Vector((r*math.cos(j*math.tau/64),r*math.sin(j*math.tau/64),0)) for j in range(64)])
    rings.append(roots[1])
    vertices=[tuple(p) for ring in rings for p in ring];faces=[]
    offsets=[sum(len(r) for r in rings[:k]) for k in range(len(rings))]
    for k in range(len(rings)-1):
        aa=angles[0] if k==0 else [j*math.tau/64 for j in range(64)]
        bb=angles[1] if k==len(rings)-2 else [j*math.tau/64 for j in range(64)]
        zipper(faces,offsets[k],len(rings[k]),aa,offsets[k+1],len(rings[k+1]),bb)
    mesh=bpy.data.meshes.new(f'held_snake_repaired_middle_{sign}')
    mesh.from_pydata(vertices,[],faces);mesh.update()
    middle=bpy.data.objects.new(f'held_snake_repaired_middle_{sign}',mesh)
    bpy.context.collection.objects.link(middle)
    colors=[sample_colors(obj,root) for obj,root in zip(parts,roots)]
    bridge_uv(mesh,rings,[angles[0]]+[[j*math.tau/64 for j in range(64)]for _ in rings[1:-1]]+[angles[1]])
    mesh.materials.append(gradient_material(f'held_snake_clean_yellow_{sign}',colors[0],angles[0],colors[1],angles[1],out_dir))
    for p in mesh.polygons:p.use_smooth=True
    bpy.ops.object.select_all(action='DESELECT')
    for obj in parts+[middle]:obj.select_set(True)
    bpy.context.view_layer.objects.active=parts[0]
    bpy.ops.object.join()
    snake=parts[0]
    snake.name=f'kuafu_held_snake_{"l" if sign>0 else "r"}'
    bm=bmesh.new();bm.from_mesh(snake.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-7)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    # Logical surface must be closed at both native-to-rebuilt boundaries.
    assert not any(e.is_boundary for e in bm.edges), 'Open recovered snake surface'
    bm.to_mesh(snake.data);bm.free()
    snake['support']=list(support)
    snake['native_distal_preserved']=True
    snake['fused_region_removed']=[.575,.735]
    return snake,dict(side=sign,radii=radius,support=list(support),nativeDistalPreserved=True,
                      removedFusionHeightRange=[.575,.735])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--body-in', type=Path, required=True)
    parser.add_argument('--hand-in', type=Path, required=True)
    parser.add_argument('--ear-in', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body = load(args.body_in, 'kuafu_native_body')
    frozen = frozen_digest(body.data)
    uv=body.data.uv_layers.active
    native_normals={(tuple(body.data.vertices[loop.vertex_index].co),tuple(uv.data[loop.index].uv)):normal.vector.copy()
                    for loop,normal in zip(body.data.loops,body.data.corner_normals)}
    reports, cuts = [], []
    for sign in (1, -1):
        result = cut_wrist(body, sign)
        ring = result['positions']
        cuts.append((sign,result))
        reports.append(dict(side=sign, ringVertices=len(ring),
                            center=list(sum(ring, Vector()) / len(ring)),
                            axis=list(result['axis']), removedFaces=result['removed']['native_removed_faces']))
    assert frozen == frozen_digest(body.data), 'Frozen original body/feet changed'
    additions, hand_reports = [], []
    for sign,result in cuts:
        hand,bridge,record=add_hand(body,args.hand_in,result,sign,args.out_dir)
        additions += [hand,bridge]
        hand_reports.append(record)
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    for obj in additions:obj.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    bm=bmesh.new();bm.from_mesh(body.data)
    bmesh.ops.remove_doubles(bm,verts=[v for v in bm.verts if not protected(v.co)],dist=1e-7)
    wrist_edges=[e for e in bm.edges if any(((e.verts[0].co+e.verts[1].co)*.5-Vector(record['center'])).length<.055 for record in reports)]
    wrist_boundary=sum(e.is_boundary for e in wrist_edges)
    wrist_nonmanifold=sum(not e.is_manifold for e in wrist_edges)
    assert wrist_boundary==0 and wrist_nonmanifold==0, ('Wrist is not continuous',wrist_boundary,wrist_nonmanifold)
    bm.to_mesh(body.data);bm.free()
    assert frozen == frozen_digest(body.data), 'Merged hands changed frozen body/feet'
    body.data.normals_split_custom_set([(0.,0.,0.)]*len(body.data.loops))
    body.data.update()
    uv=body.data.uv_layers.active
    normals=[]
    for loop in body.data.loops:
        p=body.data.vertices[loop.vertex_index].co
        key=(tuple(p),tuple(uv.data[loop.index].uv))
        near_root=any((p-Vector(record['center'])).length<.085 for record in reports)
        normals.append(native_normals[key] if key in native_normals and not near_root else body.data.vertices[loop.vertex_index].normal.copy())
    body.data.normals_split_custom_set(normals)
    snakes,snake_reports=[],[]
    for (sign,result),record in zip(cuts,hand_reports):
        snake,snake_report=recover_held_snake(result['removed'],sign,record['support'],args.out_dir)
        snakes.append(snake);snake_reports.append(snake_report)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in [body]+snakes:obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(args.out_dir/'body_norm.glb'), export_format='GLB', use_selection=True,export_extras=True)
    report = dict(frozenTriangles=frozen[0], frozenSha256=frozen[1], frozenUnchanged=True,
                  frozenAudit='positions, per-corner UV and cyclic face winding',
                  wristBoundaryEdges=wrist_boundary,wristNonManifoldEdges=wrist_nonmanifold,
                  wrists=reports,hands=hand_reports,heldSnakes=snake_reports)
    mother=load(args.hand_in,'kuafu_hand_mother')
    bpy.ops.object.select_all(action='DESELECT');mother.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(args.out_dir/'hand_norm.glb'),export_format='GLB',use_selection=True)
    if args.ear_in:
        ear=load(args.ear_in,'kuafu_ear_snake_mother')
        image=diffuse_image(ear)
        values=np.empty(image.size[0]*image.size[1]*4,np.float32);image.pixels.foreach_get(values)
        pixels=values.reshape(-1,4);pixels[:,:3]*=np.array([1.,.84,.42])
        image.pixels.foreach_set(values);image.update()
        texture=args.out_dir/'ear-golden-diffuse.png'
        image.filepath_raw=str(texture.resolve());image.file_format='PNG';image.save()
        replacement=bpy.data.images.load(str(texture.resolve()),check_existing=False);replacement.pack()
        for node in ear.data.materials[0].node_tree.nodes:
            if getattr(node,'image',None) is image:node.image=replacement
        bpy.ops.object.select_all(action='DESELECT');ear.select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(args.out_dir/'ear_norm.glb'),export_format='GLB',use_selection=True)
        report['earTintMultiplier']=[1.,.84,.42]
    report['sourceSha256']={label:hashlib.sha256(path.read_bytes()).hexdigest()for label,path in [('body',args.body_in),('hand',args.hand_in)]+([('ear',args.ear_in)]if args.ear_in else [])}
    (args.out_dir/'cut-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.out_dir.name.startswith('.build.'):
        (args.out_dir.parent/'prepare-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print('KUAFU_CUT_AUDIT '+json.dumps(report),flush=True)


if __name__ == '__main__':
    main()
