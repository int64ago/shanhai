"""Measured Stage 1 Lushu repair, preserving the source UVs and material.

Blender --background --factory-startup --python pipeline/blender/prepare_lushu.py -- \
  raw/_build/lushu/v1_raw.glb raw/_build/lushu/v1_fixed.glb concept/lushu
Use --inspect to render the untouched source and print anatomical measurements.
Coordinates below are Blender metres, head facing -Y, Z up.
"""
import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'Expected one normalized mesh, got {len(meshes)}')
    obj = meshes[0]
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for other in list(bpy.context.scene.objects):
        if other is not obj:
            bpy.data.objects.remove(other, do_unlink=True)
    return obj


def measure(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.000001)
    for height in [0.06, 0.18, 0.30, 0.40, 0.50, 0.60]:
        allowed = {v for v in bm.verts if v.co.z < height}
        groups = []
        while allowed:
            seed = allowed.pop()
            group, stack = [seed], [seed]
            while stack:
                for edge in stack.pop().link_edges:
                    # Walk only through the current low-height component.
                    for neighbor in edge.verts:
                        if neighbor in allowed:
                            allowed.remove(neighbor)
                            stack.append(neighbor)
                            group.append(neighbor)
            if len(group) > 15:
                groups.append(group)
        print('SLICE', height, [
            (len(g), tuple(tuple(round(fn(v.co[i] for v in g), 4)
                                for fn in (min, max)) for i in range(3)))
            for g in sorted(groups, key=len, reverse=True)])
    bm.free()


def low_components(bm, height):
    allowed = {v for v in bm.verts if v.co.z < height}
    groups = []
    while allowed:
        seed = allowed.pop()
        group, stack = {seed}, [seed]
        while stack:
            current = stack.pop()
            for edge in current.link_edges:
                neighbor = edge.other_vert(current)
                if neighbor in allowed:
                    allowed.remove(neighbor)
                    group.add(neighbor)
                    stack.append(neighbor)
        groups.append(group)
    return groups


def smoothstep(a, b, value):
    t = max(0, min(1, (value - a) / (b - a)))
    return t * t * (3 - 2 * t)


def repair(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # Weld positions only. BMesh retains the original per-corner UV seams.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.000001)
    original_head = [v.co.copy() for v in bm.verts if v.co.y < -0.29]

    # Below z=.57 the tail is disconnected from the body. Its lowest hair is
    # z=.138, y=.44-.50, distinct from both hoof-bearing hind-limb components.
    tail = next(g for g in low_components(bm, 0.57)
                if max(v.co.y for v in g) > 0.49
                and min(v.co.z for v in g) > 0.12)
    print('REMOVE tail branch vertices', len(tail))
    bmesh.ops.delete(bm, geom=list(tail), context='VERTS')
    # Close the tail cut; compress only its remaining high root into the rump.
    # A global rear-plane cut would clip the crossed hind leg at y=.42.
    boundary = [e for e in bm.edges if e.is_boundary
                and all(v.co.y > 0.38 and v.co.z > 0.55 for v in e.verts)]
    if boundary:
        caps = bmesh.ops.holes_fill(bm, edges=boundary, sides=0)['faces']
        uv_layer = bm.loops.layers.uv.active
        for face in caps:
            face.smooth = True
            for loop in face.loops:
                other_uvs = [other[uv_layer].uv.copy()
                             for other in loop.vert.link_loops
                             if other.face is not face] if uv_layer else []
                if other_uvs:
                    loop[uv_layer].uv = sum(other_uvs, Vector((0, 0))) / len(other_uvs)

    for v in bm.verts:
        if v.co.z > 0.55 and v.co.y > 0.35:
            weight = smoothstep(0.55, 0.58, v.co.z)
            v.co.y -= (v.co.y - 0.35) * 0.94 * weight

    # Capture only the crossed hind limb below the belly. At z=.34 all four
    # legs are separate; its hoof centroid is x=.036,y=.373. The good hind
    # limb is x=.097,y=.257. No head or torso symmetry operation is used.
    groups = low_components(bm, 0.34)
    crossed = next(g for g in groups
                   if min(v.co.z for v in g) < 0.001
                   and max(v.co.y for v in g) > 0.35)
    # Measured centreline offsets keep the whole shank upright, rather than
    # moving only the hoof and introducing an inward kink at the hock.
    offsets = [(0, .13, .035), (.08, .133, .058), (.14, .129, .062),
               (.20, .122, .068), (.26, .102, .055), (.32, .074, .020),
               (.36, .035, .005), (.42, 0, 0)]
    upper = {v for v in bm.verts if .34 <= v.co.z < .42
             and v.co.y > .20 and v.co.x < .04}
    for v in crossed | upper:
        for a, b in zip(offsets, offsets[1:]):
            if a[0] <= v.co.z <= b[0]:
                t = (v.co.z - a[0]) / (b[0] - a[0])
                blend = 1 if v in crossed else 1 - smoothstep(0, .04, v.co.x)
                v.co.x -= (a[1] * (1 - t) + b[1] * t) * blend
                v.co.y -= (a[2] * (1 - t) + b[2] * t) * blend
                break
    print('STRAIGHTEN existing hind limb vertices', len(crossed))
    # Ensure the four soles share the source ground plane.
    for v in bm.verts:
        if v.co.z < 0.0065:
            v.co.z = 0
    after_head = [v.co.copy() for v in bm.verts if v.co.y < -0.29]
    assert original_head == after_head, 'Head geometry must remain untouched'
    feet = [g for g in low_components(bm, 0.06) if len(g) > 30]
    assert len(feet) == 4, f'Expected exactly four hoof components, got {len(feet)}'
    print('FOUR HOOVES', [tuple(round(sum(v.co[i] for v in g) / len(g), 4)
                                for i in range(3)) for g in feet])
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def render(obj, out_dir, size):
    out_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new('Lushu inspection world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.92, 0.92, 0.92, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 1
    scene.world = world
    light = bpy.data.objects.new('soft sun', bpy.data.lights.new('soft sun', 'SUN'))
    light.data.energy = 1.2
    light.data.angle = math.radians(30)
    light.rotation_euler = (math.radians(25), 0, math.radians(20))
    scene.collection.objects.link(light)
    cam = bpy.data.objects.new('turnaround camera', bpy.data.cameras.new('turnaround camera'))
    cam.data.type = 'ORTHO'
    scene.collection.objects.link(cam)
    scene.camera = cam
    pts = [v.co for v in obj.data.vertices]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    center = (lo + hi) / 2
    extent = max(hi - lo)
    cam.data.ortho_scale = extent * 1.15
    distance = extent * 3
    views = [('34', (0.62, -0.72, 0.30)), ('side', (1, 0, 0)),
             ('front', (0, -1, 0)), ('back', (0, 1, 0))]
    for name, direction in views:
        # A fresh camera per view avoids stale evaluated camera transforms in
        # repeated background EEVEE renders on Blender 5.2/macOS.
        shot_cam = cam.copy()
        shot_cam.data = cam.data.copy()
        scene.collection.objects.link(shot_cam)
        location = center + Vector(direction) * distance
        rotation = (center - location).to_track_quat('-Z', 'Y')
        shot_cam.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1, 1, 1)))
        scene.camera = shot_cam
        bpy.context.view_layer.update()
        scene.render.filepath = str(out_dir / f'view_{name}.png')
        bpy.ops.render.render(write_still=True)


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('views', type=Path)
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--size', type=int, default=1024)
    args = parser.parse_args(argv)
    obj = load(args.input)
    measure(obj)
    if not args.inspect:
        repair(obj)
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        args.output.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=str(args.output), export_format='GLB',
                                  use_selection=True, export_animations=False)
    render(obj, args.views, args.size)


if __name__ == '__main__':
    main()
