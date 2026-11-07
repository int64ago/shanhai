"""Boyi: offline HIGH sheep torso, eye-free ovine head, 4 ears, 9 tails, dorsal eyes.

Master: taotie-body-max/base_basic_pbr.glb (logged Extreme-High, 50,000 tris),
normalized to length .9. No generation. Source gives no horn/eye count/color.
The hornless head, two dorsal eyes and woolly sheep tails are stated inferences.
"""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, setup_render, render_views
from prepare_ershu import material, ellipsoid, curve

TAILS = 9
EARS = [(side, pair) for side in (-1, 1) for pair in (0, 1)]
FOOT_POINTS = {f'{fb}_{side}': Vector((sign * (.13 if fb == 'front' else .19), -.265 if fb == 'front' else .24, 0)) for fb in ('front','back') for side,sign in [('l',1),('r',-1)]}


def lower_leg(name, foot, mat):
    vertices, faces = [], []
    rings, sides = 24, 20
    for i in range(rings+1):
        t = i/rings
        z = .055 + .32*t
        radius = .028 + .060*t*t
        target_y = -.245 if name.startswith('front') else .16
        center = foot + Vector((0,(target_y-foot.y)*t*t + .012*math.sin(math.pi*t),z))
        for j in range(sides):
            a = math.tau*j/sides
            vertices.append(tuple(center + Vector((radius*math.cos(a),radius*.85*math.sin(a),0))))
    for i in range(rings):
        for j in range(sides):
            k=(j+1)%sides
            faces.append((i*sides+j,i*sides+k,(i+1)*sides+k,(i+1)*sides+j))
    faces += [tuple(reversed(range(sides))),tuple(rings*sides+j for j in range(sides))]
    mesh=bpy.data.meshes.new('anatomical sheep lower leg')
    mesh.from_pydata(vertices,[],faces)
    mesh.materials.append(mat)
    uv=mesh.uv_layers.new(name='UVMap')
    for polygon in mesh.polygons:
        polygon.use_smooth=True
        for loop in polygon.loop_indices:
            index=mesh.loops[loop].vertex_index
            uv.data[loop].uv=(index%sides/sides,index//sides/rings)
    mesh.update()
    obj=bpy.data.objects.new(f'boyi_lower_leg_{name}',mesh)
    bpy.context.collection.objects.link(obj)


def tail_center(index, t):
    fan = (index - 4) / 4
    return Vector((0.12 * fan + 0.35 * fan * t,
                   0.305 + (0.35 - 0.10 * abs(fan)) * t,
                   0.580 + (0.04 if index % 2 else -0.01) * math.sin(math.pi * t) - 0.23 * t*t))


def tail(index, mat):
    vertices, faces = [], []
    rings, sides = 48, 20
    for i in range(rings + 1):
        t = i / rings
        point = tail_center(index, t)
        tangent = (tail_center(index, min(1, t+.001)) - tail_center(index, max(0, t-.001))).normalized()
        u = tangent.cross(Vector((0, 0, 1))).normalized()
        v = tangent.cross(u).normalized()
        radius = 0.024 * (1-t) ** .65 + .004
        for j in range(sides):
            a = math.tau * j / sides
            # Small uneven fleece ridges retain a soft sheep-tail silhouette.
            r = radius * (1 + .06 * math.sin(t*42 + j*2.3))
            vertices.append(tuple(point + r * (u*math.cos(a) + v*math.sin(a))))
    for i in range(rings):
        for j in range(sides):
            k = (j+1) % sides
            faces.append((i*sides+j, i*sides+k, (i+1)*sides+k, (i+1)*sides+j))
    faces += [tuple(reversed(range(sides))), tuple(rings*sides+j for j in range(sides))]
    mesh = bpy.data.meshes.new('woolly sheep tail')
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(f'boyi_tail_{index:02}', mesh)
    bpy.context.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def ear_root(side, pair):
    return Vector((side*(.055 if pair == 0 else .045), -.397 if pair == 0 else -.315, .775 if pair == 0 else .833))


def ear(side, pair, inner, mat):
    vertices, faces = [], []
    rings, around = 30, 20
    root = ear_root(side, pair)
    axis = Vector((side * .21, -.07 if pair == 0 else .075, -.065 if pair == 0 else -.045))
    for i in range(rings + 1):
        u = i / rings
        t = .12 + .78*u if inner else u
        center = root + axis*t + Vector((0, 0, .028*math.sin(math.pi*t)))
        width = .051 * max(.003, math.sin(math.pi*t)) ** .7
        depth = .012 * max(.008, math.sin(math.pi*t)) ** .6
        if inner:
            center.z += depth*.90
            width *= .72 * max(.005, math.sin(math.pi*u)) ** .35
            depth = .0016*math.sin(math.pi*u) + .0002
        for j in range(around):
            a = math.tau*j/around
            vertices.append(tuple(center + Vector((0, width*math.cos(a), depth*math.sin(a)))))
    for i in range(rings):
        for j in range(around):
            k = (j+1) % around
            faces.append((i*around+j, i*around+k, (i+1)*around+k, (i+1)*around+j))
    faces += [tuple(reversed(range(around))), tuple(rings*around+j for j in range(around))]
    mesh = bpy.data.meshes.new('ovine leaf ear')
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(f'boyi_ear_{side}_{pair}_{"inner" if inner else "outer"}', mesh)
    bpy.context.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth = True


def hoof(name, center, mat):
    halves = []
    for sign in (-1, 1):
        x, y = center.x + sign*.022, center.y
        vertices = [(x+dx, y+dy, z) for z, width, front in [(0, .021, -.058), (.085, .017, -.030)] for dx, dy in [(-width,front), (width,front), (width,.036), (-width,.036)]]
        faces = [(3,2,1,0), (4,5,6,7), (0,1,5,4), (1,2,6,5), (2,3,7,6), (3,0,4,7)]
        mesh = bpy.data.meshes.new('cloven hoof half')
        mesh.from_pydata(vertices, [], faces)
        mesh.materials.append(mat)
        mesh.update()
        obj = bpy.data.objects.new('hoof half', mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        bevel = obj.modifiers.new('rounded horn edges', 'BEVEL')
        bevel.width, bevel.segments = .006, 3
        bpy.ops.object.modifier_apply(modifier=bevel.name)
        halves.append(obj)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in halves:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = halves[0]
    bpy.ops.object.join()
    halves[0].name = f'boyi_hoof_{name}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    parser.add_argument('--view', choices=['34','side','front','back','left'])
    parser.add_argument('--render-only', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.render_only:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=args.input)
        body = bpy.data.objects['boyi_high_sheep_body']
    else:
        body = load(args.input)
        bm = bmesh.new()
        bm.from_mesh(body.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        remove = [v for v in bm.verts if (v.co.y > .315 and abs(v.co.x) < .095) or v.co.y < -.31 or v.co.z < .24]
        bmesh.ops.delete(bm, geom=remove, context='VERTS')
        # Keep only the connected torso; trimming must not leave tail fragments.
        remaining, islands = set(bm.faces), []
        while remaining:
            stack, island = [remaining.pop()], []
            while stack:
                face = stack.pop()
                island.append(face)
                for edge in face.edges:
                    for neighbor in edge.link_faces:
                        if neighbor in remaining:
                            remaining.remove(neighbor)
                            stack.append(neighbor)
            islands.append(island)
        largest = max(islands, key=len)
        bmesh.ops.delete(bm, geom=[f for island in islands if island is not largest for f in island], context='FACES')
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
        cap = material('boyi_trim_caps', (.68,.62,.50))
        body.data.materials.append(cap)
        filled = bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
        for face in filled['faces']:
            face.material_index = len(body.data.materials)-1
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(body.data)
        bm.free()
        for vertex in body.data.vertices:
            vertex.co.z += .045
        body.name = 'boyi_high_sheep_body'
        print('BOYI retained HIGH body triangles', sum(len(p.vertices)-2 for p in body.data.polygons))
        shader = body.data.materials[0].node_tree.nodes.get('Principled BSDF')
        image = shader.inputs['Base Color'].links[0].from_node.image
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba = pixels.reshape(-1,4)
        lum = rgba[:,:3] @ np.array([.2126,.7152,.0722])
        rgba[:,:3] = (.48 + .39*lum[:,None]) * np.array([.92,.86,.74])
        image.pixels.foreach_set(pixels)
        image.update()
        image.pack()
        fleece = material('boyi_fleece', (.46,.42,.34))
        face = material('boyi_ovine_face', (.38,.34,.27))
        pink = material('boyi_ear_inner', (.47,.32,.28))
        horn = material('boyi_hoof_horn', (.075,.065,.052))
        nose = material('boyi_nose_lips', (.10,.085,.068))
        rim = material('boyi_dorsal_socket', (.34,.28,.20))
        sclera = material('boyi_dorsal_sclera', (.83,.76,.58))
        iris = material('boyi_dorsal_iris', (.55,.35,.12))
        pupil = material('boyi_dorsal_pupil', (.014,.012,.009))
        breast = ellipsoid('boyi_breast', (0,-.285,.505), (.190,.115,.205), body.data.materials[0])
        for vertex in breast.data.vertices:
            p = vertex.co
            p *= 1 + .018*math.sin(p.x*170)*math.sin(p.z*155)*math.cos(p.y*120)
        masses = [
            ellipsoid('ovine neck', (0,-.290,.645), (.130,.125,.153), fleece),
            ellipsoid('ovine skull', (0,-.355,.780), (.088,.105,.112), face),
            ellipsoid('long roman nose', (0,-.429,.696), (.069,.113,.112), face),
            ellipsoid('sheep nasal bridge', (0,-.481,.645), (.059,.090,.087), face),
            ellipsoid('sheep jaw', (0,-.405,.636), (.074,.092,.063), face),
        ]
        bpy.ops.object.select_all(action='DESELECT')
        for obj in masses:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = masses[0]
        bpy.ops.object.join()
        head = masses[0]
        head.name = 'boyi_ovine_head'
        mod = head.modifiers.new('unified sheep sculpt', 'REMESH')
        mod.mode, mod.voxel_size = 'VOXEL', .0035
        bpy.ops.object.modifier_apply(modifier=mod.name)
        mod = head.modifiers.new('sculpt smoothing', 'SMOOTH')
        mod.factor, mod.iterations = 1.0, 5
        bpy.ops.object.modifier_apply(modifier=mod.name)
        for polygon in head.data.polygons:
            polygon.use_smooth = True
        ellipsoid('boyi_nose_pad', (0,-.556,.618), (.044,.022,.025), nose)
        for side in (-1,1):
            curve(f'boyi_nostril_{side}', [(side*.025,-.572,.628),(side*.032,-.575,.619),(side*.023,-.574,.612)], .0025, pupil)
        curve('boyi_mouth', [(-.036,-.535,.589),(0,-.550,.582),(.036,-.535,.589)], .0015, nose)
        for side, pair in EARS:
            ear(side,pair,False,fleece)
            ear(side,pair,True,pink)
        for index in range(TAILS):
            tail(index,fleece)
        bpy.context.view_layer.update()
        for side in (-1,1):
            x = side*.105
            hit, location, _, _ = body.ray_cast(Vector((x,.005,1.2)),Vector((0,0,-1)))
            if not hit:
                raise RuntimeError('No dorsal surface for Boyi eye')
            surface = location.z
            print('BOYI dorsal eye surface',side,surface)
            for name, dz, size, mat in [
                ('socket',-.010,(.066,.086,.024),rim),
                ('sclera',.006,(.054,.073,.022),sclera),
                ('iris',.025,(.034,.042,.012),iris),
                ('pupil',.034,(.028,.008,.006),pupil),
            ]:
                ellipsoid(f'boyi_dorsal_{side}_{name}', (x,.005,surface+dz),size,mat)
        # The HIGH master ends in flattened ankle stumps, not hooves. Replace
        # the low distorted portion with four anatomical tapering shanks, then
        # fit paired hoof halves at their exact supports; no extra stump remains.
        for name, foot in FOOT_POINTS.items():
            lower_leg(name,foot,body.data.materials[0])
            hoof(name,foot,horn)
        # Voxel-union the new shanks/breast into the retained HIGH surface so
        # joins have continuous skin. Project the original HIGH UVs back from
        # an owned temporary proxy; this is offline sculpting, no simplification.
        body_material = body.data.materials[0]
        bpy.ops.object.select_all(action='DESELECT')
        for obj in bpy.context.scene.objects:
            if obj is body or obj.name == 'boyi_breast' or obj.name.startswith('boyi_lower_leg_'):
                obj.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.join()
        proxy = body.copy()
        proxy.data = body.data.copy()
        proxy.hide_render = True
        bpy.context.collection.objects.link(proxy)
        mod = body.modifiers.new('continuous offline sheep sculpt', 'REMESH')
        mod.mode, mod.voxel_size = 'VOXEL', .0035
        mod.use_smooth_shade = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        mod = body.modifiers.new('soft wool joins', 'SMOOTH')
        mod.factor, mod.iterations = .6, 3
        bpy.ops.object.modifier_apply(modifier=mod.name)
        transfer = body.modifiers.new('project HIGH fur UV', 'DATA_TRANSFER')
        transfer.object = proxy
        transfer.use_loop_data = True
        transfer.data_types_loops = {'UV'}
        transfer.loop_mapping = 'POLYINTERP_NEAREST'
        bpy.ops.object.datalayout_transfer(modifier=transfer.name)
        bpy.ops.object.modifier_apply(modifier=transfer.name)
        bpy.data.objects.remove(proxy,do_unlink=True)
        body.data.materials.clear()
        body.data.materials.append(body_material)
        for polygon in body.data.polygons:
            polygon.material_index=0
            polygon.use_smooth=True
        print('BOYI continuous body triangles',sum(len(p.vertices)-2 for p in body.data.polygons))
        bpy.ops.object.select_all(action='SELECT')
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=args.output,export_format='GLB',use_selection=True,export_animations=False)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            obj.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    Path(args.views).mkdir(parents=True,exist_ok=True)
    cam = setup_render(1024)
    if args.view == 'left':
        points = [v.co for v in body.data.vertices]
        lo, hi = [Vector(tuple(fn(p[i] for p in points) for i in range(3))) for fn in (min,max)]
        center = (lo+hi)/2
        cam.data.ortho_scale = max(hi-lo)*1.15
        location = center + Vector((-max(hi-lo)*3,0,0))
        cam.matrix_world = Matrix.LocRotScale(location,(center-location).to_track_quat('-Z','Y'),Vector((1,1,1)))
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath = f'{args.views}/view_left.png'
        bpy.ops.render.render(write_still=True)
    else:
        render_views(body,cam,args.views,only_view=args.view)


if __name__ == '__main__':
    main()
