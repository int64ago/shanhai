"""Prepare Xixiyu (鳛鳛鱼) modular assets from Rodin outputs:
1. body_norm.glb: legless magpie-fish core retaining two native folded wings (1.45 m long, beak at -Y).
2. wing_norm.glb: a complete single scaled-feather wing, or one extracted from a paired raw mesh,
   aligned along +X (dorsal +Z, chord in XY) as `wing_l` plus properly-wound mirror `wing_r`.

Usage:
  Blender --background --factory-startup --python-exit-code 1 --python pipeline/blender/prepare_xixiyu.py -- \
      --body-in <core.glb> --wing-in <wing.glb> --out-dir <dir> [--preview-dir <dir>]
      [--wing-mode single --single-root-axis=-y]
"""
import argparse
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--body-in', required=True)
    p.add_argument('--wing-in', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--preview-dir')
    p.add_argument('--body-length', type=float, default=1.45)
    p.add_argument('--wing-span', type=float, default=0.58)
    p.add_argument('--wing-mode', choices=('paired', 'single'), default='paired',
                   help='paired preserves the historical Medium extraction; single retains the complete High wing')
    p.add_argument('--single-root-axis', choices=('-x', '+x', '-y', '+y'), default='-x',
                   help='reviewed native root direction for single mode; use = for negative values')
    return p.parse_args(argv)


def import_single(path, name):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError(f'No mesh in {path}')
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.context.scene.objects):
        if o is not obj:
            bpy.data.objects.remove(o, do_unlink=True)
    obj.name = name
    return obj


def keep_largest_island(bm):
    seen = set()
    islands = []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, isl = [f], []
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            isl.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        islands.append(isl)
    if len(islands) > 1:
        largest = max(islands, key=len)
        drop = [f for isl in islands if isl is not largest for f in isl]
        bmesh.ops.delete(bm, geom=drop, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    return len(islands)


def shrink_textures(limit):
    for img in bpy.data.images:
        w, h = img.size
        if w > 0 and h > 0 and max(w, h) > limit:
            k = limit / max(w, h)
            img.scale(round(w * k), round(h * k))
            print(f'TEXTURE {img.name} {w}x{h} -> {img.size[0]}x{img.size[1]}')


def bounds(obj):
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def add_native_tip_scales(obj):
    """Hand-model silver fish scales only on the native folded flight-feather ends.

    Coordinates are reviewed on the 1.45 m normalized high core. Ray casting
    conforms each scale to its feather surface; no body-wide scale pattern.
    Shape, silver colour and staggered rows are explicitly artistic inference.
    """
    verts, faces = [], []
    for side in (1, -1):
        # The two visible long feather tips of each folded wing, lower/upper.
        for start_y, start_z in ((0.062, 0.390), (0.092, 0.455)):
            for row in range(4):
                for col in range(3):
                    y = start_y + row * 0.010
                    z = start_z + col * 0.010 + (row % 2) * 0.004
                    hit, point, normal, _ = obj.ray_cast(Vector((side * 0.40, y, z)), Vector((-side, 0, 0)))
                    if not hit or side * normal.x < 0.30:
                        continue
                    normal.normalize()
                    along = Vector((0, 1, 0))
                    along = (along - normal * along.dot(normal)).normalized()
                    across = normal.cross(along).normalized()
                    base = len(verts)
                    center = point + normal * 0.0012
                    verts.append(center + normal * 0.0022)
                    # A convex rounded scale with a tapered distal edge.
                    for j in range(10):
                        a = math.tau * j / 10
                        forward = math.cos(a)
                        width = 0.0068 * (0.80 if forward > 0 else 1.0)
                        verts.append(center + along * (0.008 * forward) + across * (width * math.sin(a)))
                    for j in range(10):
                        faces.append((base, base + 1 + j, base + 1 + (j + 1) % 10))
    if len(verts) < 40 * 11:
        raise RuntimeError(f'Native feather-tip scale placement missed the reviewed surface: {len(verts) // 11}')
    mesh = bpy.data.meshes.new('native_feather_tip_scales')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    scales = bpy.data.objects.new('native_feather_tip_scales', mesh)
    bpy.context.scene.collection.objects.link(scales)
    material = bpy.data.materials.new('silver_native_feather_tip_scales')
    material.diffuse_color = (0.35, 0.43, 0.46, 1)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = material.diffuse_color
    bsdf.inputs['Roughness'].default_value = 0.78
    scales.data.materials.append(material)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    scales.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()
    print(f'NATIVE_TIP_SCALES count={len(verts) // 11} surface=two_native_folded_wings')


def prepare_body(path, out_path, length):
    obj = import_single(path, 'xixiyu_body')
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    n_isl = keep_largest_island(bm)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()

    lo, hi = bounds(obj)
    scale = length / (hi.y - lo.y)
    cx = (lo.x + hi.x) / 2
    cy = (lo.y + hi.y) / 2
    obj.data.transform(Matrix.Translation((0, 0, 0.30)) @ Matrix.Scale(scale, 4) @ Matrix.Translation((-cx, -cy, -lo.z)))
    obj.data.update()

    # Preserve the high source's two complete native folded wings. Runtime adds
    # eight wings, not ten; squeezing the native pair destroys their feather tips.
    add_native_tip_scales(obj)

    lo2, hi2 = bounds(obj)
    obj.data.calc_loop_triangles()
    print(f'BODY islands={n_isl} verts={len(obj.data.vertices)} tris={len(obj.data.loop_triangles)} '
          f'lo={tuple(round(v, 3) for v in lo2)} hi={tuple(round(v, 3) for v in hi2)}')
    shrink_textures(2048)
    bpy.ops.export_scene.gltf(filepath=out_path, export_format='GLB', use_selection=False)
    print('EXPORTED', out_path)
    return obj


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def prepare_wing(path, out_path, span):
    wing_l = import_single(path, 'wing_l')
    bm = bmesh.new()
    bm.from_mesh(wing_l.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)

    # Cut cleanly along x = 0.205 to remove the central white neck lump and the -X wing.
    cut_x = 0.205
    res = bmesh.ops.bisect_plane(
        bm,
        geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
        plane_co=(cut_x, 0.0, 0.0),
        plane_no=(1.0, 0.0, 0.0),
        clear_inner=True,
        clear_outer=False,
        dist=1e-6,
    )
    boundary = [g for g in res['geom_cut'] if isinstance(g, bmesh.types.BMEdge) and g.is_boundary]
    if boundary:
        bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
    keep_largest_island(bm)

    # Compute root center near the cut plane and taper the cut cap into a rounded plug.
    root_pts = [v.co.copy() for v in bm.verts if v.co.x < cut_x + 0.05]
    root_c = sum(root_pts, Vector()) / max(1, len(root_pts))
    root_c.x = cut_x

    tip_pts = [v.co.copy() for v in bm.verts if v.co.x > 0.80]
    tip_c = sum(tip_pts, Vector()) / max(1, len(tip_pts))

    # Taper vertices within 0.07 of cut_x smoothly toward root_c so root hides inside flank.
    for v in bm.verts:
        if v.co.x < cut_x + 0.07:
            k = 0.35 + 0.65 * smoothstep(cut_x, cut_x + 0.07, v.co.x)
            v.co.y = root_c.y + (v.co.y - root_c.y) * k
            v.co.z = root_c.z + (v.co.z - root_c.z) * k
            if v.co.x <= cut_x + 0.002:
                v.co.x = cut_x - 0.03 * (1.0 - (v.co - root_c).length / 0.25)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(wing_l.data)
    bm.free()

    # Rotate so span vector (root_c -> tip_c) points strictly along +X,
    # and chord plane lies near horizontal XY with dorsal facing +Z and leading edge -Y.
    span_vec = (tip_c - root_c).normalized()
    align_q = span_vec.rotation_difference(Vector((1.0, 0.0, 0.0)))
    wing_l.data.transform(align_q.to_matrix().to_4x4() @ Matrix.Translation(-root_c))

    # Measure chord tilt around X axis using mid-wing leading vs trailing edge.
    mid_pts = [v.co for v in wing_l.data.vertices if 0.25 < v.co.x < 0.90]
    lead = min(mid_pts, key=lambda p: p.y)
    trail = max(mid_pts, key=lambda p: p.y)
    chord_yz = Vector((0.0, trail.y - lead.y, trail.z - lead.z))
    roll_ang = -math.atan2(chord_yz.z, chord_yz.y)
    wing_l.data.transform(Matrix.Rotation(roll_ang, 4, 'X'))

    # Scale uniformly so total span along +X from x=0 to max x equals `span`.
    pts = [v.co for v in wing_l.data.vertices]
    cur_span = max(p.x for p in pts)
    s = span / max(cur_span, 1e-4)
    wing_l.data.transform(Matrix.Scale(s, 4))
    wing_l.data.update()

    return export_wing_pair(wing_l, out_path)


def prepare_single_wing(path, out_path, span, root_axis):
    """Retain the complete reviewed single wing; never apply the paired cut.

    The reviewed root axis is explicit because independent generations may use
    different orientations. Only rigid alignment and uniform scaling are applied.
    No simplification, welding or island deletion may remove native tip scales.
    """
    wing_l = import_single(path, 'wing_l')
    axis = 0 if root_axis[-1] == 'x' else 1
    direction = 1 if root_axis[0] == '-' else -1
    pts = [v.co.copy() for v in wing_l.data.vertices]
    lo = min(direction * p[axis] for p in pts)
    hi = max(direction * p[axis] for p in pts)
    raw_span = hi - lo
    if not math.isfinite(raw_span) or raw_span <= 0 or not math.isfinite(span) or span <= 0:
        raise RuntimeError('Single-wing source and target must have a positive finite span')
    root_pts = [p for p in pts if direction * p[axis] < lo + raw_span * 0.08]
    tip_pts = [p for p in pts if direction * p[axis] > hi - raw_span * 0.08]
    root_c = sum(root_pts, Vector()) / len(root_pts)
    root_c[axis] = direction * (lo + raw_span * 0.02)
    tip_c = sum(tip_pts, Vector()) / len(tip_pts)
    align_q = (tip_c - root_c).normalized().rotation_difference(Vector((1, 0, 0)))
    wing_l.data.transform(align_q.to_matrix().to_4x4() @ Matrix.Translation(-root_c))
    along = max(v.co.x for v in wing_l.data.vertices)
    mid_pts = [v.co.copy() for v in wing_l.data.vertices if along * 0.20 < v.co.x < along * 0.75]
    if along <= 0 or len(mid_pts) < 2:
        raise RuntimeError('Single-wing alignment produced no positive span or mid-wing chord')
    lead, trail = min(mid_pts, key=lambda p: p.y), max(mid_pts, key=lambda p: p.y)
    roll = -math.atan2(trail.z - lead.z, trail.y - lead.y)
    wing_l.data.transform(Matrix.Rotation(roll, 4, 'X'))
    wing_l.data.transform(Matrix.Scale(span / along, 4))
    wing_l.data.update()
    wing_l.data.calc_loop_triangles()
    print(f'SINGLE_WING source_tris={len(wing_l.data.loop_triangles)} root={root_axis} simplification=none')
    return export_wing_pair(wing_l, out_path)


def export_wing_pair(wing_l, out_path):
    # Build mirrored wing_r in Blender with proper outward face winding (no negative runtime scale).
    wing_r_data = wing_l.data.copy()
    wing_r_data.name = 'wing_r'
    wing_r = bpy.data.objects.new('wing_r', wing_r_data)
    bpy.context.scene.collection.objects.link(wing_r)
    bm_r = bmesh.new()
    bm_r.from_mesh(wing_r.data)
    for v in bm_r.verts:
        v.co.x = -v.co.x
    bmesh.ops.reverse_faces(bm_r, faces=bm_r.faces)
    bmesh.ops.recalc_face_normals(bm_r, faces=bm_r.faces)
    bm_r.to_mesh(wing_r.data)
    bm_r.free()
    wing_r.data.update()

    for w in (wing_l, wing_r):
        lo, hi = bounds(w)
        w.data.calc_loop_triangles()
        print(f'WING {w.name} verts={len(w.data.vertices)} tris={len(w.data.loop_triangles)} '
              f'lo={tuple(round(v, 3) for v in lo)} hi={tuple(round(v, 3) for v in hi)}')

    shrink_textures(1024)
    bpy.ops.export_scene.gltf(filepath=out_path, export_format='GLB', use_selection=False)
    print('EXPORTED', out_path)
    return wing_l, wing_r


def render_4views(objs, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 640
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs[0].default_value = (0.90, 0.89, 0.86, 1)
    bg.inputs[1].default_value = 1.0
    scene.world = world
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 2.0
    sun.rotation_euler = (math.radians(35), 0, math.radians(25))
    scene.collection.objects.link(sun)

    pts = [v.co for o in objs for v in o.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (lo + hi) / 2
    extent = max(hi - lo) * 1.25
    d = extent * 3.0
    views = [
        ('front', Vector((0, -d, 0)), Vector((0, 0, 1))),
        ('side', Vector((d, 0, 0)), Vector((0, 0, 1))),
        ('top', Vector((0, 0, d)), Vector((0, -1, 0))),
        ('34', Vector((d * 0.65, -d * 0.72, d * 0.40)), Vector((0, 0, 1))),
    ]
    for name, offset, up in views:
        cam = bpy.data.objects.new(f'cam_{name}', bpy.data.cameras.new(f'cam_{name}'))
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = extent
        scene.collection.objects.link(cam)
        loc = center + offset
        forward = (center - loc).normalized()
        right = forward.cross(up).normalized()
        true_up = right.cross(forward).normalized()
        rot = Matrix((right, true_up, -forward)).transposed().to_4x4()
        cam.matrix_world = Matrix.Translation(loc) @ rot
        scene.camera = cam
        bpy.context.view_layer.update()
        scene.render.filepath = os.path.join(out_dir, f'{prefix}_{name}.png')
        bpy.ops.render.render(write_still=True)


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    body_out = os.path.join(args.out_dir, 'body_norm.glb')
    wing_out = os.path.join(args.out_dir, 'wing_norm.glb')
    body = prepare_body(args.body_in, body_out, args.body_length)
    if args.preview_dir:
        render_4views([body], args.preview_dir, 'body')
    if args.wing_mode == 'single':
        wing_l, wing_r = prepare_single_wing(args.wing_in, wing_out, args.wing_span, args.single_root_axis)
    else:
        wing_l, wing_r = prepare_wing(args.wing_in, wing_out, args.wing_span)
    if args.preview_dir:
        render_4views([wing_l, wing_r], args.preview_dir, 'wing_pair')
        wing_r.hide_render = True
        render_4views([wing_l], args.preview_dir, 'wing_single')


if __name__ == '__main__':
    main()
