"""Offline Ershu sculpt from the cached fuzhu deer donor.

The receipt identifies the donor task; counts are measured, never inferred from
its filename. Preserve donor anatomy/UV by nearest-surface transfer after joining
the new rabbit skull, jaw and cervical tissue into the chest. Concave pinnae and
a curved tapering tail are separate deformable organs, with embedded roots.
No network, generation, or paid service is used.
"""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = 0.84
    return mat


def ellipsoid(name, center, size, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.data.materials.append(mat)
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def curve(name, points, radius, mat):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.bevel_depth = radius
    data.bevel_resolution = 3
    spline = data.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    for point, co in zip(spline.bezier_points, points):
        point.co = co
        point.handle_left_type = point.handle_right_type = 'AUTO'
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.convert(target='MESH')
    obj.select_set(False)
    return obj


def ear(side, fur, inner):
    # A closed pinna with one recessed front surface, a rounded rim and a convex
    # back. Inner color belongs to the same surface: no inset floating pad.
    verts, faces, indices = [], [], []
    rings, around = 64, 48
    for i in range(rings + 1):
        t = i / rings
        width = .047 * max(.002, math.sin(math.pi * t)) ** .66
        thickness = .010 * max(.003, math.sin(math.pi * t)) ** .65
        cup = .022 * math.sin(math.pi * t) ** .7
        center = Vector((side * (.048 + (.087 if side == 1 else .117) * t + .012 * math.sin(math.pi * t)), -.285 + .014 * t + .075 * t * t, .794 + (.310 if side == 1 else .282) * t))
        for j in range(around):
            a = math.tau * j / around
            u, s = math.cos(a), math.sin(a)
            depth = thickness * s if s >= 0 else -thickness * .45 + cup * (1 - u*u)
            # The back lies behind even the deepest part of the concavity.
            if s >= 0:
                depth += cup * .98 * s
            verts.append(tuple(center + Vector((width * u, depth, -side * .28 * width * u))))
    for i in range(rings):
        for j in range(around):
            k = (j + 1) % around
            faces.append((i*around+j, i*around+k, (i+1)*around+k, (i+1)*around+j))
            indices.append(1 if around//2+3 <= j < around-3 and 6 < i < rings-5 else 0)
    faces += [tuple(reversed(range(around))), tuple(rings*around+j for j in range(around))]
    indices += [0, 0]
    mesh = bpy.data.meshes.new('concave rabbit pinna')
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(fur)
    mesh.materials.append(inner)
    mesh.update()
    obj = bpy.data.objects.new(f'ershu_ear_{side}', mesh)
    bpy.context.collection.objects.link(obj)
    for p, index in zip(mesh.polygons, indices):
        p.material_index = index
        p.use_smooth = True
    return obj


def tail_center(t):
    # Deliberate S-shaped line of action, with a downward soft root and a
    # relaxed upward tip. Original text supplies no tail shape.
    return Vector((.075*math.sin(t*math.tau*.85), .387 + .79*t, .610 - .22*math.sin(math.pi*t*.92) + .13*t*t))


def make_tail(mat):
    verts, faces = [], []
    rings, around = 140, 32
    for i in range(rings+1):
        t = i/rings
        center = tail_center(t)
        tangent = (tail_center(min(1,t+.0001))-tail_center(max(0,t-.0001))).normalized()
        xaxis = Vector((1,0,0))
        yaxis = tangent.cross(xaxis).normalized()
        radius = .030*(1-t)**1.12 + .00065
        radius *= 1 + .018*math.cos(t*math.tau*38)
        for j in range(around):
            a = math.tau*j/around
            verts.append(tuple(center + radius*(xaxis*math.cos(a)+yaxis*math.sin(a))))
    for i in range(rings):
        for j in range(around):
            k=(j+1)%around
            faces.append((i*around+j,i*around+k,(i+1)*around+k,(i+1)*around+j))
    faces += [tuple(reversed(range(around))), tuple(rings*around+j for j in range(around))]
    mesh=bpy.data.meshes.new('curved continuous tapering tail')
    mesh.from_pydata(verts,[],faces)
    mesh.materials.append(mat)
    mesh.update()
    obj=bpy.data.objects.new('ershu_tail',mesh)
    bpy.context.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth=True
    return obj


def unified_sculpt(body, masses):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in masses:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=masses[0]
    bpy.ops.object.join()
    head=masses[0]
    mod=head.modifiers.new('continuous rabbit tissue','REMESH')
    mod.mode='VOXEL';mod.voxel_size=.0022;mod.use_remove_disconnected=False
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mod=head.modifiers.new('soft tissue','SMOOTH')
    mod.factor=1.0;mod.iterations=20
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bm=bmesh.new();bm.from_mesh(head.data)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.normal_update()
    if bm.calc_volume(signed=True)<0:
        bmesh.ops.reverse_faces(bm,faces=list(bm.faces));bm.normal_update()
    print('HEAD_VOLUME',bm.calc_volume(signed=True))
    bm.to_mesh(head.data);bm.free()
    bpy.context.view_layer.objects.active=body
    mod=body.modifiers.new('exact neck chest union','BOOLEAN')
    mod.operation='UNION';mod.solver='EXACT';mod.use_hole_tolerant=True;mod.object=head
    mod.material_mode='TRANSFER'
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(head,do_unlink=True)
    # Rebuild the sculpt's normals after the topology operation. The donor's
    # imported custom normals are invalid at newly created union boundaries.
    bpy.ops.object.select_all(action='DESELECT');body.select_set(True)
    if body.data.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    bm=bmesh.new();bm.from_mesh(body.data)
    tissue=[v for v in bm.verts if .51<v.co.z<.70 and v.co.y<-.16]
    for _ in range(8):
        bmesh.ops.smooth_vert(bm,verts=tissue,factor=.5,use_axis_x=True,use_axis_y=True,use_axis_z=True)
    bm.to_mesh(body.data);bm.free()
    source=body.data.copy();source.calc_loop_triangles()
    coords=[v.co.copy() for v in source.vertices]
    triangles=list(source.loop_triangles)
    tree=BVHTree.FromPolygons(coords,[tuple(t.vertices) for t in triangles],all_triangles=True)
    uvsource=source.uv_layers.active
    mod=body.modifiers.new('final continuous tissue','REMESH')
    mod.mode='VOXEL';mod.voxel_size=.0028
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mod=body.modifiers.new('relax union seam','SMOOTH')
    mod.factor=.7;mod.iterations=3
    bpy.ops.object.modifier_apply(modifier=mod.name)
    # Remove the donor's hanging central breast shield by returning its front
    # surface to a rounded sternum envelope. Keep the lateral pectoral/scapular
    # volumes; this deforms the existing continuous surface rather than adding
    # an external patch.
    def eased(a,b,x):
        t=max(0,min(1,(x-a)/(b-a)))
        return t*t*(3-2*t)
    for vertex in body.data.vertices:
        x,y,z=vertex.co
        if .37<z<.66 and abs(x)<.115 and y<-.20:
            # Fair both the recessed midline and projecting twin shield lobes
            # into one curved sternum that rises smoothly into the throat.
            envelope=-.228-.113*eased(.40,.66,z)+.065*(x/.105)**2
            weight=(1-eased(.050,.115,abs(x)))*eased(.37,.41,z)*(1-eased(.60,.66,z))*(1-eased(-.235,-.20,y))
            vertex.co.y+=(envelope-y)*weight
        if .46<z<.66 and abs(x)<.11 and y>.35:
            # The native-tail cut left a planar recess. Fair the existing
            # croup surface across it, retaining the donor's lateral haunches.
            envelope=.285+.15*math.sqrt(max(0,1-(x/.16)**2-((z-.52)/.17)**2))
            weight=(1-eased(.045,.11,abs(x)))*eased(.46,.49,z)*(1-eased(.61,.66,z))*eased(.35,.40,y)
            vertex.co.y+=(envelope-y)*weight
    bm=bmesh.new();bm.from_mesh(body.data)
    tissue=[v for v in bm.verts if .58<v.co.z<.70 and v.co.y<-.16]
    for _ in range(50):
        bmesh.ops.smooth_vert(bm,verts=tissue,factor=.85,use_axis_x=True,use_axis_y=True,use_axis_z=True)
    nape=[v for v in bm.verts if .67<v.co.z<.80 and -.31<v.co.y<-.12]
    for _ in range(45):
        bmesh.ops.smooth_vert(bm,verts=nape,factor=.65,use_axis_x=True,use_axis_y=True,use_axis_z=True)
    # Remove tiny detached voxel specks; they are not anatomical organs.
    unseen=set(bm.verts)
    while unseen:
        seed=unseen.pop();island={seed};stack=[seed]
        while stack:
            vertex=stack.pop()
            for edge in vertex.link_edges:
                other=edge.other_vert(vertex)
                if other in unseen:
                    unseen.remove(other);island.add(other);stack.append(other)
        if len(island)<32:bmesh.ops.delete(bm,geom=list(island),context='VERTS')
    bm.to_mesh(body.data);bm.free()
    # Graded Laplacian fairing extends past the coordinate corrections. A
    # smooth zero derivative at the perimeter preserves surrounding tangents;
    # a hard selected-vertex boundary would pin a visible shield/cap outline.
    import numpy as np
    count=len(body.data.vertices)
    positions=np.empty(count*3,dtype=np.float64)
    body.data.vertices.foreach_get('co',positions)
    positions=positions.reshape(-1,3)
    edges=np.empty(len(body.data.edges)*2,dtype=np.int32)
    body.data.edges.foreach_get('vertices',edges)
    edges=edges.reshape(-1,2)
    receivers=np.concatenate((edges[:,0],edges[:,1]))
    neighbors=np.concatenate((edges[:,1],edges[:,0]))
    degree=np.maximum(1,np.bincount(receivers,minlength=count))
    x,y,z=positions.T
    def falloff(a,b,values):
        t=np.clip((values-a)/(b-a),0,1)
        return t*t*(3-2*t)
    chest_weight=(1-falloff(.035,.14,np.abs(x)))*falloff(.33,.40,z)*(1-falloff(.60,.69,z))*(1-falloff(-.18,-.10,y))
    croup_weight=(1-falloff(.035,.15,np.abs(x)))*falloff(.40,.48,z)*(1-falloff(.62,.73,z))*falloff(.27,.39,y)
    weights=np.maximum(.55*chest_weight,.70*croup_weight)
    for _ in range(180):
        average=np.column_stack([np.bincount(receivers,weights=positions[neighbors,axis],minlength=count)/degree for axis in range(3)])
        positions+=(average-positions)*weights[:,None]
    body.data.vertices.foreach_set('co',positions.ravel())
    body.data.update()
    # Reconstruct the faired surface before transferring UVs. This also drops
    # the pre-deformation split normals and prevents a false hard patch edge.
    mod=body.modifiers.new('continuous faired surface','REMESH')
    mod.mode='VOXEL';mod.voxel_size=.0028
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mod=body.modifiers.new('relax fairing boundaries','SMOOTH')
    mod.factor=.8;mod.iterations=12
    bpy.ops.object.modifier_apply(modifier=mod.name)
    uv=body.data.uv_layers.active or body.data.uv_layers.new(name='UVMap')
    for polygon in body.data.polygons:
        _,_,nearest,_=tree.find_nearest(polygon.center)
        polygon.material_index=source.polygons[triangles[nearest].polygon_index].material_index
        for loop_index in polygon.loop_indices:
            co=body.data.vertices[body.data.loops[loop_index].vertex_index].co
            point,_,idx,_=tree.find_nearest(co);tri=triangles[idx]
            if uvsource:
                uvs=[Vector((*uvsource.data[k].uv,0)) for k in tri.loops]
                projected=barycentric_transform(point,*(coords[k] for k in tri.vertices),*uvs)
                uv.data[loop_index].uv=projected.xy
    bpy.data.meshes.remove(source)
    # Orbit and lids are deformations of the actual skull surface, not glued
    # rings. The eye is recessed behind the rim so only an almond is exposed.
    for vertex in body.data.vertices:
        x,y,z=vertex.co
        if abs(x)<.042:continue
        dy=(y+.352)/.020;dz=(z-.779)/.014
        radial=math.sqrt(dy*dy+dz*dz)
        if radial>1.6:continue
        socket=-.0035*math.exp(-radial*radial/.45)
        lid=.0012*math.exp(-((radial-1)/.20)**2)*(.65+.35*max(-1,min(1,dz)))
        vertex.co.x+=(1 if x>0 else -1)*(socket+lid)
    # Three or more real, noncollinear sole vertices are flat in bind pose.
    # Rigging rigidly weights the hoof, so this plane survives articulation.
    for vertex in body.data.vertices:
        if vertex.co.z<.008:vertex.co.z=0
    if body.data.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    body.data.update()
    for polygon in body.data.polygons:polygon.use_smooth=True
    body.name='ershu_cervid_rabbit_sculpt'
    print('ERSHU_SCULPT vertices',len(body.data.vertices),'triangles',sum(len(p.vertices)-2 for p in body.data.polygons))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input');parser.add_argument('output');parser.add_argument('views')
    parser.add_argument('--render-only',action='store_true')
    parser.add_argument('--gray',action='store_true')
    parser.add_argument('--view',choices=['34','side','front','back'])
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.render_only:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=args.input)
        body=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.startswith('ershu_cervid'))
    else:
        body=load(args.input)
        print('ERSHU_DONOR vertices',len(body.data.vertices),'triangles',sum(len(p.vertices)-2 for p in body.data.polygons))
        bm=bmesh.new();bm.from_mesh(body.data)
        bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-5)
        old=[v for v in bm.verts if (v.co.z>.655 and v.co.y<-.19) or (v.co.y<-.34 and v.co.z>.51) or (v.co.y>.428 and v.co.z>.49 and abs(v.co.x)<.067)]
        bmesh.ops.delete(bm,geom=old,context='VERTS')
        bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
        # holes_fill skips the nonplanar 125-edge neck opening. Build its cap
        # explicitly; an open donor makes exact Boolean classify all space as
        # interior and cut away remote parts of the rabbit skull.
        remaining=set(e for e in bm.edges if e.is_boundary)
        while remaining:
            edge=remaining.pop();loop={edge};stack=list(edge.verts)
            while stack:
                vertex=stack.pop()
                for neighbor in vertex.link_edges:
                    if neighbor in remaining:
                        remaining.remove(neighbor);loop.add(neighbor)
                        stack.extend(neighbor.verts)
            bmesh.ops.contextual_create(bm,geom=list(loop))
        assert not any(e.is_boundary for e in bm.edges), 'donor must be closed before union'
        bmesh.ops.triangulate(bm,faces=[f for f in bm.faces if len(f.verts)>4])
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.normal_update()
        print('DONOR_VOLUME before',bm.calc_volume(signed=True),'boundaries',sum(e.is_boundary for e in bm.edges))
        if bm.calc_volume(signed=True) < 0:
            bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
            bm.normal_update()
        print('DONOR_VOLUME after',bm.calc_volume(signed=True))
        bm.to_mesh(body.data);bm.free()
        print('ERSHU_TRIMMED triangles',sum(len(p.vertices)-2 for p in body.data.polygons))
        # Spatial sculpt fields retain the donor's tendons and hooves while
        # deepening the chest, separating the waist and rounding the haunches.
        for v in body.data.vertices:
            x,y,z=v.co
            torso=max(0,min(1,(z-.28)/.17))
            shoulder=math.exp(-((y+.23)/.12)**2)
            waist=math.exp(-((y-.06)/.13)**2)
            haunch=math.exp(-((y-.30)/.11)**2)
            v.co.x*=1+torso*(.14*shoulder-.17*waist+.14*haunch)
            v.co.z+=torso*(-.018*shoulder+.035*waist*max(0,(.62-z)/.25)+.012*haunch)
        import numpy as np
        shader=body.data.materials[0].node_tree.nodes.get('Principled BSDF')
        image=shader.inputs['Base Color'].links[0].from_node.image
        pixels=np.empty(len(image.pixels),dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba=pixels.reshape(-1,4)
        # Suppress donor photographic shadow/color boundaries. Retain a fine
        # coat grain, then use the same map on the joined rabbit tissue.
        grain=.985+.015*rgba[:,:3].mean(axis=1,keepdims=True)
        rgba[:,:3]=grain*np.array([.76,.67,.55])
        rgba[:,3]=1
        image.pixels.foreach_set(pixels);image.update();image.pack()
        fur=material('ershu_hare_fur',(.50,.40,.28))
        inner=material('ershu_pinna_inner',(.37,.22,.18))
        dark=material('ershu_eye_nose_lip',(.021,.015,.011))
        whisker=material('ershu_whisker',(.22,.18,.13))
        # Overlapping sculpt volumes are voxel-unioned, never exported as
        # intersecting primitives. Smaller nasal and cheek masses establish a
        # sloping rabbit profile rather than a spherical toy head.
        masses=[
            ellipsoid('cervical tissue',(0,-.250,.645),(.063,.084,.102),fur),
            ellipsoid('throat',(0,-.292,.681),(.056,.074,.085),fur),
            ellipsoid('occipital skull',(0,-.293,.766),(.073,.091,.083),fur),
            ellipsoid('frontal skull',(0,-.344,.777),(.061,.086,.059),fur),
            ellipsoid('nasal bridge',(0,-.401,.752),(.042,.069,.043),fur),
            ellipsoid('lower jaw',(0,-.347,.704),(.054,.079,.037),fur),
            ellipsoid('nuchal tissue bridge',(0,-.237,.735),(.058,.065,.071),fur),
        ]
        for side in (-1,1):
            masses.extend([
                ellipsoid('zygomatic cheek',(side*.044,-.333,.733),(.035,.054,.048),fur),
                ellipsoid('continuous muzzle',(side*.023,-.433,.723),(.030,.039,.026),fur),
                ellipsoid('ear root tissue',(side*.045,-.282,.813),(.035,.038,.039),fur),
            ])
        unified_sculpt(body,masses)
        body.data.materials.append(material('ershu_cloven_hooves',(.035,.027,.020)))
        hoof_index=len(body.data.materials)-1
        for polygon in body.data.polygons:
            polygon.material_index=hoof_index if polygon.center.z<.035 else 0
        for side in (-1,1):
            # Almond eye follows the lateral skull plane and sits under a brow.
            eye=ellipsoid(f'ershu_eye_{side}',(side*.0575,-.352,.779),(.0035,.018,.0115),dark)
            ear(side,fur,inner)
            for index in range(3):
                curve(f'ershu_whisker_{side}_{index}',[(side*.033,-.457,.728),(side*.077,-.464,.722+(index-1)*.010),(side*(.118+.012*index),-.441+.012*index,.715+(index-1)*.019)],.00048,whisker)
        nose=ellipsoid('ershu_hare_nose',(0,-.466,.739),(.011,.006,.008),dark)
        for v in nose.data.vertices:
            if v.co.z<.739:v.co.x*=.55
        curve('ershu_split_lip',[(0,-.468,.734),(0,-.470,.721),(-.015,-.466,.712)],.0008,dark)
        curve('ershu_split_lip_right',[(0,-.470,.721),(.015,-.466,.712)],.0008,dark)
        make_tail(material('ershu_tail_skin',(.36,.27,.20)))
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.export_scene.gltf(filepath=args.output,export_format='GLB',use_selection=True,export_animations=False)
        print('ERSHU_TOTAL triangles',sum(len(p.vertices)-2 for o in bpy.context.scene.objects if o.type=='MESH' for p in o.data.polygons))
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if args.gray:
        gray=material('neutral gray',(.45,.45,.45))
        for obj in meshes:
            obj.data.materials.clear();obj.data.materials.append(gray)
            for p in obj.data.polygons:p.material_index=0
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:obj.select_set(True)
    bpy.context.view_layer.objects.active=body
    bpy.ops.object.join()
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    Path(args.views).mkdir(parents=True,exist_ok=True)
    cam=setup_render(1024)
    bpy.context.scene.world.node_tree.nodes['Background'].inputs[1].default_value=.5
    bpy.data.objects['sun'].data.energy=2.0
    render_views(body,cam,args.views,only_view=args.view)


if __name__=='__main__':main()
