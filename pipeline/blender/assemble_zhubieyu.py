"""Assemble the two NEW Zhubieyu HIGH masters, six copies of its own limb.
Eyes, nacre pearl and embedded mantle rim are original authored geometry.
Input meshes must be normalized, +Z up and -Y forward.
"""
import argparse
import math
import os
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_screen_peng import transform
from prepare_zhubieyu import render_views
from turnaround import setup_render

ROWS = [('front', -.46), ('middle', .015), ('back', .48)]
FEET = {f'{row}_{label}': Vector((side * .70, y + .025, .055)) for row, y in ROWS for side, label in [(1, 'l'), (-1, 'r')]}
HIPS = {f'{row}_{label}': Vector((side * .34, y + (.17 if row == 'front' else -.06 if row == 'back' else .01), .655)) for row, y in ROWS for side, label in [(1, 'l'), (-1, 'r')]}
KNEES = {key: (hip + FEET[key]) / 2 + Vector((0, .075, .015)) for key, hip in HIPS.items()}


def load(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objects = set(bpy.data.objects) - before
    meshes = [o for o in objects if o.type == 'MESH']
    assert len(meshes) == 1
    obj = meshes[0]
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in objects:
        if o is not obj:
            bpy.data.objects.remove(o)
    obj.data.calc_loop_triangles()
    print('NEW_HIGH_INPUT', path, len(obj.data.loop_triangles))
    return obj


def material(name, rgb, roughness=.65):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1)
    m.use_nodes = True
    shader = m.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*rgb, 1)
    shader.inputs['Roughness'].default_value = roughness
    return m


def ellipsoid(name, center, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.scale = radius
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.data.materials.append(mat)
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def tube(name, points, radii, mat, sections=10):
    vertices = []
    n = len(points)
    for i, p in enumerate(points):
        tangent = (points[(i + 1) % n] - points[(i - 1) % n]).normalized()
        normal = tangent.cross(Vector((0, 1, 0))).normalized()
        binormal = tangent.cross(normal).normalized()
        for j in range(sections):
            angle = math.tau * j / sections
            vertices.append(p + radii[i] * (normal * math.cos(angle) + binormal * math.sin(angle)))
    faces = []
    for i in range(n):
        for j in range(sections):
            faces.append((i * sections + j, i * sections + (j + 1) % sections, ((i + 1) % n) * sections + (j + 1) % sections, ((i + 1) % n) * sections + j))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    mesh.materials.append(mat)
    for p in mesh.polygons:
        p.use_smooth = True
    return obj


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--body', required=True)
    p.add_argument('--leg', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--concept', required=True)
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body = load(a.body)
    body.name = 'zhubieyu_lung_mantle'
    # Standardize to the corrected horizontal proportions even if Rodin returns
    # a slight aspect shift. Existing normals are transformed by the matrix.
    co = np.array([v.co[:] for v in body.data.vertices])
    lo, hi = co.min(0), co.max(0)
    target = np.array([1.36, 1.55, .62])
    scale = target / (hi - lo)
    body.data.transform(Matrix.Diagonal((*scale, 1)))
    co = np.array([v.co[:] for v in body.data.vertices])
    lo, hi = co.min(0), co.max(0)
    body.data.transform(Matrix.Translation(Vector((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, .27 - lo[2]))))
    body.data.update()

    master = load(a.leg)
    co = np.array([v.co[:] for v in master.data.vertices])
    lo, hi = co.min(0), co.max(0)
    # Orient the longest low toe projection toward -Y. HIGH normalized output
    # retains the multiview orientation, checked in its own four views.
    ankle_points = co[(co[:, 2] > lo[2] + .18 * (hi[2] - lo[2])) & (co[:, 2] < lo[2] + .30 * (hi[2] - lo[2]))]
    ankle_xy = np.median(ankle_points[:, :2], axis=0)
    sole = co[co[:, 2] < lo[2] + .08 * (hi[2] - lo[2])]
    direction = sole[:, :2].mean(0) - ankle_xy
    yaw = -math.pi / 2 - math.atan2(direction[1], direction[0])
    master.data.transform(Matrix.Rotation(yaw, 4, 'Z'))
    co = np.array([v.co[:] for v in master.data.vertices])
    lo, hi = co.min(0), co.max(0)
    scale = np.array([.22, .25, .47]) / (hi - lo)
    master.data.transform(Matrix.Diagonal((*scale, 1)))
    co = np.array([v.co[:] for v in master.data.vertices])
    lo, hi = co.min(0), co.max(0)
    ankle_points = co[(co[:, 2] > lo[2] + .07) & (co[:, 2] < lo[2] + .12)]
    xy = np.median(ankle_points[:, :2], axis=0)
    master.data.transform(Matrix.Translation(Vector((-xy[0], -xy[1], -lo[2]))))
    # Give the actual high mesh a planar, multi-vertex sole and a gently splayed
    # upper limb, with a finite normal transform through the nonlinear mapping.
    for key, foot in FEET.items():
        obj = master.copy()
        obj.data = master.data.copy()
        bpy.context.collection.objects.link(obj)
        obj.name = 'zhubieyu_leg_' + key
        hip = HIPS[key]
        dx, dy = hip.x - foot.x, hip.y - foot.y
        def mapping(p):
            q = p.copy()
            u = np.clip((p[:, 2] - .10) / .37, 0, 1)
            w = u * u * (3 - 2 * u)
            q[:, 0] = p[:, 0] * (1 + .35 * w) + foot.x + dx * w
            q[:, 1] += foot.y + dy * w
            # Nearly flat generated soles are leveled without changing the
            # silhouette or rebuilding normals from degenerate triangles.
            q[:, 2] = np.where(p[:, 2] < .018, p[:, 2] * .001, p[:, 2] - .017982 * np.clip((.045 - p[:, 2]) / .027, 0, 1))
            q[:, 2] += .50 * np.maximum(p[:, 2] - .10, 0)
            return q
        transform(obj, mapping)
    bpy.data.objects.remove(master, do_unlink=True)

    skin = material('authored mantle rim, grey pink', (.64, .69, .65))
    iris = material('olive bronze iris', (.18, .15, .075), .33)
    dark = material('deep ink pupil', (.007, .011, .010), .28)
    light = material('small reflected light', (.83, .85, .73), .32)
    # Locate the eyes in the generated anterior surface, never attach a whole
    # guessed head. Two eyes and all locations are explicitly inferred.
    for side, label in [(1, 'l'), (-1, 'r')]:
        hit, point, normal, _ = body.ray_cast(Vector((side * .38, -2, .58)), Vector((0, 1, 0)))
        assert hit, 'anterior eye must intersect the HIGH mantle'
        center = point + Vector((0, -.015, .003))
        ellipsoid('zhubieyu_eye_' + label, center, (.052, .026, .033), iris)
        ellipsoid('zhubieyu_pupil_' + label, center + Vector((0, -.024, 0)), (.020, .009, .027), dark)
        ellipsoid('zhubieyu_glint_' + label, center + Vector((-.011, -.032, .014)), (.004, .003, .004), light)
        points, radii = [], []
        for i in range(80):
            angle = math.tau * i / 80
            points.append(center + Vector((.055 * math.cos(angle), .006, .034 * math.sin(angle))))
            radii.append(.009 + .003 * max(0, math.sin(angle)))
        tube('zhubieyu_eyelid_' + label, points, radii, skin)

    hit, point, normal, _ = body.ray_cast(Vector((-.25, .04, 2)), Vector((0, 0, -1)))
    assert hit, 'pearl is embedded in the central mantle bridge'
    pearl_mat = material('nacre pale celadon', (.72, .80, .69), .25)
    pearl = ellipsoid('zhubieyu_pearl', point + Vector((0, 0, .045)), (.105, .14, .12), pearl_mat)
    # Delicate nacre growth waves, not a pile of primitive balls.
    def nacre(p):
        q = p.copy()
        relative = p - np.array(point + Vector((0, 0, .045)))
        wave = .00035 * np.sin(relative[:, 2] * 230 + np.sin(relative[:, 1] * 40))
        radial = relative / np.maximum(np.linalg.norm(relative, axis=1), 1e-8)[:, None]
        return q + radial * wave[:, None]
    transform(pearl, nacre)
    points, radii = [], []
    for i in range(96):
        angle = math.tau * i / 96
        x, y = point.x + .114 * math.cos(angle), point.y + .145 * math.sin(angle)
        rim_hit, rim_point, _, _ = body.ray_cast(Vector((x, y, 2)), Vector((0, 0, -1)))
        assert rim_hit, 'mantle fold must rest on the HIGH skin'
        points.append(Vector((x, y, rim_point.z + .005)))
        radii.append(.010 + .002 * math.cos(angle * 3))
    tube('zhubieyu_pearl_mantle_fold', points, radii, skin)
    os.makedirs(os.path.dirname(a.output), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', export_animations=False)
    # Multi-mesh assembly gets a non-exported bounding object for the renderer.
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    vertices = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
    bound_mesh = bpy.data.meshes.new('bounds')
    bound_mesh.from_pydata(vertices, [], [])
    bounds = bpy.data.objects.new('bounds', bound_mesh)
    bpy.context.collection.objects.link(bounds)
    os.makedirs(a.concept, exist_ok=True)
    render_views(bounds, setup_render(1024), a.concept)
    print('ZHUBIEYU_ASSEMBLED', len(meshes), 'surfaces, six own HIGH feet, 2 inferred eyes, 1 embedded nacre pearl')


if __name__ == '__main__':
    main()
