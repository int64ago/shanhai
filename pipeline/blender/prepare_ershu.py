"""Offline Ershu: verified 50,000-triangle HIGH deer master + sculpted hare head.

No generation requests. Input: fuzhu-body-max/base_basic_pbr.glb normalized
with normalize.py --length 1.05. HIGH provenance is recorded in asset-credits.
The primary text says 菟首麋身; it specifies flight by tail, not tail shape.
Only the original skull/antlers and short deer tail are removed. Four legs,
cloven hooves, chest, flank and rump retain the original HIGH topology.
"""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (*color, 1)
    mat.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value = 0.84
    return mat


def ellipsoid(name, center, size, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=40, ring_count=24, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
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
    obj.select_set(True)
    bpy.ops.object.convert(target='MESH')
    obj.select_set(False)
    return obj


def ear(side, inner, mat):
    verts, faces = [], []
    rings, around = 40, 24
    for i in range(rings + 1):
        u = i / rings
        t = 0.12 + 0.80 * u if inner else u
        width = 0.052 * max(0.003, math.sin(math.pi * t)) ** 0.70
        thickness = 0.014 * max(0.008, math.sin(math.pi * t)) ** 0.60
        center = Vector((side * (0.055 + 0.068 * t), -0.302 + 0.055 * t * t, 0.812 + (0.32 if side == 1 else 0.30) * t))
        if inner:
            width *= 0.70
            center.y -= thickness * 0.95
            thickness = 0.0025 * math.sin(math.pi * u) + 0.0002
            width *= max(0.005, math.sin(math.pi * u)) ** 0.38
        for j in range(around):
            a = math.tau * j / around
            verts.append(tuple(center + Vector((width * math.cos(a), thickness * math.sin(a), -side * width * math.cos(a) * 0.18))))
    for i in range(rings):
        for j in range(around):
            k = (j + 1) % around
            faces.append((i * around + j, i * around + k, (i + 1) * around + k, (i + 1) * around + j))
    faces += [tuple(reversed(range(around))), tuple(rings * around + j for j in range(around))]
    mesh = bpy.data.meshes.new('hare ear surface')
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(f'ershu_ear_{side}_{"inner" if inner else "outer"}', mesh)
    bpy.context.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    return obj


def tail_center(t):
    return Vector((0.045 * math.sin(t * math.pi), 0.400 + 0.82 * t, 0.612 + 0.06 * t + 0.20 * t * t))


def make_tail(mat):
    verts, faces = [], []
    rings, around = 100, 24
    for i in range(rings + 1):
        t = i / rings
        center = tail_center(t)
        tangent = (tail_center(min(1, t + 0.001)) - tail_center(max(0, t - 0.001))).normalized()
        xaxis = Vector((1, 0, 0))
        yaxis = tangent.cross(xaxis).normalized()
        radius = 0.040 * (1 - t) ** 0.75 + 0.0018
        # Fine annular ridges suggest a rodent tail, not feathers or a fox brush.
        radius *= 1 + 0.045 * math.cos(t * math.tau * 32)
        for j in range(around):
            a = math.tau * j / around
            verts.append(tuple(center + radius * (xaxis * math.cos(a) + yaxis * math.sin(a))))
    for i in range(rings):
        for j in range(around):
            k = (j + 1) % around
            faces.append((i * around + j, i * around + k, (i + 1) * around + k, (i + 1) * around + j))
    faces += [tuple(reversed(range(around))), tuple(rings * around + j for j in range(around))]
    mesh = bpy.data.meshes.new('single continuous tapering tail')
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new('ershu_tail', mesh)
    bpy.context.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    parser.add_argument('--view', choices=['34', 'side', 'front', 'back', 'left'])
    parser.add_argument('--render-only', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.render_only:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=args.input)
        body = next(o for o in bpy.context.scene.objects if o.name == 'ershu_high_deer_body')
    else:
        body = load(args.input)
    if not args.render_only:
        bm = bmesh.new()
        bm.from_mesh(body.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        # The skull, antlers and small deer ears are all above the neck plane.
        old_head = [v for v in bm.verts if (v.co.z > 0.655 and v.co.y < -0.19) or (v.co.y < -0.405 and v.co.z > 0.54)]
        # Short native deer tail lies behind rump center, clear of both hindlegs.
        old_tail = [v for v in bm.verts if v.co.y > 0.428 and v.co.z > 0.49 and abs(v.co.x) < 0.067]
        bmesh.ops.delete(bm, geom=list(set(old_head + old_tail)), context='VERTS')
        boundaries = [e for e in bm.edges if e.is_boundary]
        bmesh.ops.holes_fill(bm, edges=boundaries, sides=0)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(body.data)
        bm.free()
        body.name = 'ershu_high_deer_body'
        # Preserve the HIGH texture's fur and dark hooves beneath an earth wash.
        import numpy as np
        shader = body.data.materials[0].node_tree.nodes.get('Principled BSDF')
        image = shader.inputs['Base Color'].links[0].from_node.image
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba = pixels.reshape(-1, 4)
        rgba[:, :3] *= np.array([0.83, 0.76, 0.64])
        image.pixels.foreach_set(pixels)
        image.update()
        image.pack()
        print('ERSHU_HIGH retained body triangles', sum(len(p.vertices) - 2 for p in body.data.polygons))

        fur = material('ershu_hare_fur', (0.66, 0.58, 0.43))
        muzzle = material('ershu_muzzle', (0.80, 0.75, 0.64))
        inner = material('ershu_inner_ear', (0.49, 0.29, 0.24))
        dark = material('ershu_eye_nose_mouth', (0.025, 0.019, 0.014))
        whisker = material('ershu_whisker', (0.29, 0.24, 0.19))
        tailmat = material('ershu_tail_skin', (0.48, 0.37, 0.29))
        # Voxel-union only the new head masses; original HIGH body is untouched.
        masses = [
            ellipsoid('hare skull', (0, -0.304, 0.745), (0.099, 0.111, 0.108), fur),
            ellipsoid('hare brow', (0, -0.358, 0.762), (0.082, 0.090, 0.071), fur),
            ellipsoid('short hare nasal bridge', (0, -0.407, 0.738), (0.062, 0.066, 0.049), fur),
            ellipsoid('hare jaw', (0, -0.363, 0.697), (0.073, 0.071, 0.047), fur),
        ]
        bpy.ops.object.select_all(action='DESELECT')
        for obj in masses:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = masses[0]
        bpy.ops.object.join()
        head = masses[0]
        head.name = 'ershu_hare_head'
        mod = head.modifiers.new('unified hare sculpt', 'REMESH')
        mod.mode = 'VOXEL'
        mod.voxel_size = 0.0035
        bpy.ops.object.modifier_apply(modifier=mod.name)
        mod = head.modifiers.new('soft sculpt transition', 'SMOOTH')
        mod.factor = 1.0
        mod.iterations = 5
        bpy.ops.object.modifier_apply(modifier=mod.name)
        for p in head.data.polygons:
            p.use_smooth = True
        for side in (-1, 1):
            ellipsoid(f'ershu_hare_muzzle_{side}', (side * 0.030, -0.441, 0.711), (0.038, 0.037, 0.029), muzzle)
            ellipsoid(f'ershu_eye_{side}', (side * 0.083, -0.366, 0.774), (0.012, 0.016, 0.016), dark)
            ear(side, False, fur)
            ear(side, True, inner)
            for index in range(3):
                curve(f'ershu_whisker_{side}_{index}', [(side * 0.043, -0.461, 0.715), (side * 0.096, -0.465, 0.710 + (index - 1) * 0.012), (side * (0.15 + 0.01 * index), -0.438 + 0.014 * index, 0.704 + (index - 1) * 0.023)], 0.00075, whisker)
        nose = ellipsoid('ershu_hare_nose', (0, -0.474, 0.729), (0.017, 0.009, 0.011), dark)
        # Rabbit's small triangular nose and split upper lip are unlike a canine muzzle.
        for vertex in nose.data.vertices:
            if vertex.co.z < 0:
                vertex.co.x *= 0.55
        curve('ershu_split_lip', [(0, -0.474, 0.723), (0, -0.477, 0.710), (-0.020, -0.474, 0.700)], 0.0011, dark)
        curve('ershu_split_lip_right', [(0, -0.477, 0.710), (0.020, -0.474, 0.700)], 0.0011, dark)
        make_tail(tailmat)
        bpy.ops.object.select_all(action='SELECT')
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(args.views).mkdir(parents=True, exist_ok=True)
    # Bounds must include the whole assembly, not just its retained deer torso.
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    cam = setup_render(1024)
    if args.view == 'left':
        from mathutils import Matrix
        pts = [v.co for v in body.data.vertices]
        lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
        center = (lo + hi) / 2
        cam.data.ortho_scale = max(hi - lo) * 1.15
        location = center + Vector((-max(hi - lo) * 3, 0, 0))
        cam.matrix_world = Matrix.LocRotScale(location, (center - location).to_track_quat('-Z', 'Y'), Vector((1, 1, 1)))
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath = f'{args.views}/view_left.png'
        bpy.ops.render.render(write_still=True)
    else:
        render_views(body, cam, args.views, only_view=args.view)


if __name__ == '__main__':
    main()
