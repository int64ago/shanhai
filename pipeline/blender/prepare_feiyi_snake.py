"""Feiyi snake: inspect/correct newly generated anatomical masters and assemble HIGHs.
Source fixes one snake, six legs and four wings; placement and feathering are inferred.
"""
import argparse
import math
import sys
from pathlib import Path
import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import setup_render, render_views


def load(path, name):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o not in before and o.type == 'MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = name
    return obj


def inspect(obj):
    pts = np.array([v.co[:] for v in obj.data.vertices])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    print('BOUNDS', obj.name, lo.tolist(), hi.tolist())
    for f in np.linspace(0, 1, 11):
        z = lo[2] + (hi[2] - lo[2]) * f
        section = pts[abs(pts[:, 2] - z) < (hi[2] - lo[2]) * .025]
        if len(section):
            print('SLICE', round(float(z), 4), np.quantile(section, [.02, .5, .98], axis=0).round(4).tolist())


def views(objects, directory, size=1024):
    pts = [o.matrix_world @ v.co for o in objects for v in o.data.vertices]
    lo, hi = [Vector(tuple(fn(q[i] for q in pts) for i in range(3))) for fn in (min, max)]
    mesh = bpy.data.meshes.new('render bounds')
    mesh.from_pydata([(x, y, z) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)], [], [])
    bounds = bpy.data.objects.new('render bounds', mesh)
    bpy.context.collection.objects.link(bounds)
    Path(directory).mkdir(parents=True, exist_ok=True)
    render_views(bounds, setup_render(size), directory)
    bpy.data.objects.remove(bounds, do_unlink=True)


LEG_ROWS = [-.66, -.06, .48]
WING_ROWS = [-.72, .10]
BODY_LIFT = .29


def assemble(body, leg_path, wing_path):
    # Retain the generated head, belly and full taper. Broaden the muscular
    # trunk modestly without replacing its organic surface by a tube.
    for v in body.data.vertices:
        q = v.co
        trunk = math.exp(-((q.y + .20) / .80) ** 4)
        q.x *= 1 + .30 * trunk
        q.z = q.z * (1 + .15 * trunk) + BODY_LIFT
    body.name = 'feiyi_snake_body'
    meshes = [body]
    leg = load(leg_path, 'leg_master')
    coords = [v.co.copy() for v in leg.data.vertices]
    height = max(q.z for q in coords)
    root = sum((q for q in coords if q.z > height * .90), Vector()) / sum(q.z > height * .90 for q in coords)
    factor = .375 / height
    for row, y in enumerate(LEG_ROWS):
        for side, label in [(1, 'l'), (-1, 'r')]:
            obj = leg.copy()
            obj.data = leg.data.copy()
            bpy.context.collection.objects.link(obj)
            obj.name = f'feiyi_leg_{row}_{label}'
            for v, q in zip(obj.data.vertices, coords):
                z = q.z * factor
                v.co = (side * (.045 + (.375 - z) * .43 + (q.x - root.x) * factor), y + (q.y - root.y) * factor, z)
            bm = bmesh.new(); bm.from_mesh(obj.data)
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces)); bm.to_mesh(obj.data); bm.free()
            meshes.append(obj)
    bpy.data.objects.remove(leg, do_unlink=True)
    wing = load(wing_path, 'wing_master')
    coords = [v.co.copy() for v in wing.data.vertices]
    y_min = min(q.y for q in coords)
    proximal = [q for q in coords if q.y < y_min + .055]
    root = sum(proximal, Vector()) / len(proximal)
    print('WING_MASTER_ROOT', tuple(root))
    for row, y in enumerate(WING_ROWS):
        for side, label in [(1, 'l'), (-1, 'r')]:
            obj = wing.copy(); obj.data = wing.data.copy(); bpy.context.collection.objects.link(obj)
            obj.name = f'feiyi_wing_{row}_{label}'
            factor = 1 if row == 0 else .80
            for v, q in zip(obj.data.vertices, coords):
                span = (q.y - root.y) * factor
                chord = (q.x - root.x) * factor
                v.co = (side * (.045 + span), y + chord * .55 + span * .14,
                        .395 + (q.z - root.z) * .30 * factor + span * .44 + chord * .60)
            bm = bmesh.new(); bm.from_mesh(obj.data)
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces)); bm.to_mesh(obj.data); bm.free()
            meshes.append(obj)
    bpy.data.objects.remove(wing, do_unlink=True)
    return meshes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('views')
    p.add_argument('--part', choices=['inspect', 'body', 'leg', 'wing'], default='inspect')
    p.add_argument('--leg')
    p.add_argument('--wing')
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    obj = load(a.input, 'feiyi_' + a.part)
    inspect(obj)
    if a.part == 'leg':
        # Measured v1 root artifact projects to +X beyond the upper haunch.
        # Preserve the watertight surface and UVs: compress the artificial
        # side peg into the haunch rather than leaving a cut boundary.
        for v in obj.data.vertices:
            q = v.co
            if q.x > .095 and q.z > .50:
                q.x = .095 + (q.x - .095) * .035
            t = max(0, min(1, (q.z - .57) / .21))
            t = t * t * (3 - 2 * t)
            q.x = .035 + (q.x - .035) * (1 - .37 * t)
            q.y = .035 + (q.y - .035) * (1 - .37 * t)
            # Level the toe pads, keeping their volume above the plantar plane.
            weight = 1 - max(0, min(1, (q.z - .10) / .10))
            q.z = max(0, q.z - .055 * weight)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        upper = [v for v in bm.verts if v.co.z > .52]
        for _ in range(24):
            bmesh.ops.smooth_vert(bm, verts=upper, factor=.65, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
    meshes = assemble(obj, a.leg, a.wing) if a.leg and a.wing else [obj]
    bpy.ops.object.select_all(action='DESELECT')
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = obj
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
    views(meshes, a.views)


if __name__ == '__main__':
    main()
