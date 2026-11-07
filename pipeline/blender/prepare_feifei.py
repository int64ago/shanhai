"""Correct the Feifei preview for Stage 2: drop the ochre tail, grow a nape mane; render views."""
import argparse
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render

# Measured on the normalized preview: body midline and the rump closing dome.
MID_X = -0.07
RUMP_Z, RUMP_RX, RUMP_RZ = 0.42, 0.15, 0.2
RUMP_TIP_Y, RUMP_RIM_Y = 0.35, 0.285


def cut_tail(bm, cut_y):
    """Remove everything behind the rump plane; no limb reaches it. Cap only the new cut."""
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                           plane_co=(0, cut_y, 0), plane_no=(0, 1, 0),
                           clear_outer=True, clear_inner=False, dist=1e-6)
    cut = [e for e in bm.edges if e.is_boundary and all(abs(v.co.y - cut_y) < 1e-4 for v in e.verts)]
    made = bmesh.ops.holes_fill(bm, edges=cut, sides=0)
    # The new cap has no paint: borrow the rump fur colour from the loop around it.
    uv = bm.loops.layers.uv.active
    edge_uv = [l[uv].uv.copy() for e in cut for f in e.link_faces if f not in made['faces'] for l in f.loops]
    mean = sum(edge_uv, Vector((0, 0))) / len(edge_uv)
    # Give the cap interior vertices, then close the rear onto one smooth dome.
    poked = bmesh.ops.poke(bm, faces=made['faces'])
    inner = list({e for f in poked['faces'] for e in f.edges
                  if all(g in poked['faces'] for g in e.link_faces)})
    bmesh.ops.subdivide_edges(bm, edges=inner, cuts=4, use_grid_fill=True)
    cap = [f for f in bm.faces if all(abs(v.co.y - cut_y) < 1e-4 for v in f.verts)]
    for f in cap:
        for l in f.loops:
            l[uv].uv = mean
    for v in bm.verts:
        r2 = ((v.co.x - MID_X) / RUMP_RX) ** 2 + ((v.co.z - RUMP_Z) / RUMP_RZ) ** 2
        # Past the rim the limit climbs away again, leaving thighs and hocks alone.
        surface = (RUMP_TIP_Y - (RUMP_TIP_Y - RUMP_RIM_Y) * r2 if r2 < 1
                   else RUMP_RIM_Y + (r2 - 1) * 0.3)
        k = max(0.0, min(1.0, (v.co.z - 0.24) / 0.08))
        if v.co.y > surface:
            v.co.y += (surface - v.co.y) * k * k * (3 - 2 * k)


def blade(root, direction, normal, length, width, rings=7, sides=6):
    """One flattened tuft of mane hair whose tip settles back toward the skin."""
    vertices, faces = [], []
    side = direction.cross(normal).normalized()
    across = side.cross(direction).normalized()
    for j in range(rings + 1):
        t = j / rings
        center = root + direction * (length * t) - normal * (0.22 * length * t * t)
        r = width * (1 - t) ** 0.8 + 0.0006
        for k in range(sides):
            a = k * math.tau / sides
            vertices.append(tuple(center + side * (r * math.cos(a)) + across * (0.45 * r * math.sin(a))))
    for j in range(rings):
        for k in range(sides):
            n = (k + 1) % sides
            faces.append((j * sides + k, j * sides + n, (j + 1) * sides + n, (j + 1) * sides + k))
    faces.append(tuple(reversed(range(sides))))
    faces.append(tuple(rings * sides + k for k in range(sides)))
    return vertices, faces


def paint(name, rgb):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*rgb, 1)
    material.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.9
    return material


def grow_mane(obj):
    rng = random.Random(7)
    dark = paint('Feifei mane umber', (0.075, 0.045, 0.03))
    warm = paint('Feifei mane sepia', (0.14, 0.085, 0.052))
    vertices, faces, shade = [], [], []
    tree = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())
    stations = 30
    for i in range(stations):
        t = i / (stations - 1)
        y = -0.305 + 0.25 * t
        fade = 1 - 0.55 * t ** 2  # Ridge shortens into the withers.
        reach = 0.1 * (1 - 0.45 * t)
        for k in range(-5, 6):
            lateral = reach * k / 5
            x = MID_X + lateral + rng.uniform(-0.005, 0.005)
            hit, normal, _, _ = tree.ray_cast(Vector((x, y + rng.uniform(-0.005, 0.005), 1.2)), Vector((0, 0, -1)))
            if hit is None:
                continue
            flow = Vector((0, 1, 0))
            flow = (flow - normal * flow.dot(normal)).normalized()
            out = Vector((math.copysign(1, lateral) if k else 0, 0, -0.5 if k else 0)) * abs(k) / 5
            direction = (flow + normal * (0.42 - 0.05 * abs(k)) + out * 0.7).normalized()
            vs, fs = blade(hit - normal * 0.004, direction, normal,
                           rng.uniform(0.06, 0.092) * fade, rng.uniform(0.015, 0.021))
            base = len(vertices)
            vertices.extend(vs)
            faces.extend(tuple(base + q for q in f) for f in fs)
            shade.extend([rng.random() < 0.3] * len(fs))
    mesh = bpy.data.meshes.new('nape mane')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(dark)
    mesh.materials.append(warm)
    for polygon, light in zip(mesh.polygons, shade):
        polygon.use_smooth = True
        polygon.material_index = 1 if light else 0
    mane = bpy.data.objects.new('nape mane', mesh)
    bpy.context.scene.collection.objects.link(mane)
    bpy.ops.object.select_all(action='DESELECT')
    mane.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()


def finish_tail(obj):
    """Reprofile the normalized +X tail offline: round shaft, narrow rounded tip.

    Rodin widened the distal end into a paddle. Preserve its UVs and fur topology,
    straighten the drifting centerline, and taper the last three quarters instead.
    """
    vertices = obj.data.vertices
    lo = min(v.co.x for v in vertices)
    length = max(v.co.x for v in vertices) - lo
    steps = 28
    centers = []
    for i in range(steps + 1):
        x = lo + length * i / steps
        section = [v.co for v in vertices if abs(v.co.x - x) < length / steps]
        centers.append(Vector((0,
            (min(p.y for p in section) + max(p.y for p in section)) / 2,
            (min(p.z for p in section) + max(p.z for p in section)) / 2)))
    for v in vertices:
        u = (v.co.x - lo) / length
        s = min(u * steps, steps - 1e-6)
        i = int(s)
        center = centers[i].lerp(centers[i + 1], s - i)
        t = max(0.0, min(1.0, (u - 0.22) / 0.78))
        taper = 1 - 0.76 * t * t * (3 - 2 * t)
        v.co.y = (v.co.y - center.y) * 0.73 * taper
        v.co.z = (v.co.z - center.z) * taper
    obj.data.update()
    print('TAIL_PROFILE rounded shaft and tapered tip; UVs and topology preserved')


def tail_views(obj, out_dir):
    """White fur on the pale backdrop loses its silhouette, so matte it onto mid-grey."""
    obj.data.transform(Matrix.Rotation(math.pi / 2, 4, 'Z'))
    obj.data.update()
    cam = setup_render(1024)
    bpy.context.scene.render.film_transparent = True
    bpy.context.scene.render.image_settings.color_mode = 'RGBA'
    render_views(obj, cam, out_dir)
    for name in ['34', 'side', 'front', 'back']:
        path = f'{out_dir}/view_{name}.png'
        image = bpy.data.images.load(path)
        px = [0.0] * (image.size[0] * image.size[1] * 4)
        image.pixels.foreach_get(px)
        for i in range(0, len(px), 4):
            alpha = px[i + 3]
            for c in range(3):
                px[i + c] = px[i + c] * alpha + 0.22 * (1 - alpha)
            px[i + 3] = 1.0
        image.pixels.foreach_set(px)
        image.filepath_raw = path
        image.file_format = 'PNG'
        image.save()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('views')
    p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--part', choices=['body', 'tail'], default='body')
    p.add_argument('--cut-y', type=float, default=0.352)
    p.add_argument('--finish-tail', action='store_true', help='Reprofile a normalized final tail before compression')
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(a.input)
    if a.part == 'tail':
        if a.finish_tail:
            finish_tail(obj)
            Path(a.output).parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
        Path(a.views).mkdir(parents=True, exist_ok=True)
        tail_views(obj, a.views)
        return
    if not a.inspect:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        cut_tail(bm, a.cut_y)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        grow_mane(obj)
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(a.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), a.views, only_view=a.view)


if __name__ == '__main__':
    main()
