"""Correct the Lili Stage-1 draft and render the Stage-2 reference views.

The draft had a yawed head, two thin tail strands rooted off-centre, a nub under
the belly, and a hide paler than the ochre palette. Spurs are deliberately absent
here: assemble_lili.py adds them after Stage 2 so image-to-3D cannot melt them.

Usage:
  blender --background --factory-startup --python pipeline/blender/prepare_lili.py -- \
      raw/_build/lili/v1_norm.glb concept/lili
"""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render, smoothstep

HEAD_YAW = math.radians(20)
HEAD_PIVOT_Y = -0.2
TAIL_THICKNESS = 0.035
HIDE_TINT = np.array([0.93, 0.72, 0.5], dtype=np.float32)


def straighten_head(obj):
    for v in obj.data.vertices:
        w = smoothstep(-0.08, -0.26, v.co.y) if v.co.y < -0.08 else 0
        if w <= 0:
            continue
        a = HEAD_YAW * w
        x, y = v.co.x, v.co.y - HEAD_PIVOT_Y
        v.co.x = x * math.cos(a) - y * math.sin(a)
        v.co.y = x * math.sin(a) + y * math.cos(a) + HEAD_PIVOT_Y
    obj.data.update()


def remove_tail_strands(obj):
    """Flood from strand seeds through thin rear geometry, never reaching the legs."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bm.normal_update()
    bm.verts.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)

    def thin(v):
        hit = tree.ray_cast(v.co - v.normal * 1e-4, -v.normal, 0.5)
        return hit[0] is not None and hit[3] < TAIL_THICKNESS

    region = {v for v in bm.verts if v.co.y > 0.33 and v.co.z > 0.09 and v.co.x > 0 and thin(v)}
    seeds = [v for v in region if v.co.y > 0.42 or v.co.z > 0.33]
    picked = set(seeds)
    stack = list(seeds)
    while stack:
        vertex = stack.pop()
        for edge in vertex.link_edges:
            other = edge.other_vert(vertex)
            if other in region and other not in picked:
                picked.add(other)
                stack.append(other)
    # Two rings catch the strand roots, which are thicker where they meet the rump.
    for _ in range(2):
        picked |= {e.other_vert(v) for v in list(picked) for e in v.link_edges}
    print('LILI tail verts removed', len(picked))
    bmesh.ops.delete(bm, geom=list(picked), context='VERTS')
    holes = [e for e in bm.edges if e.is_boundary and all(v.co.y > 0.3 and v.co.z > 0.09 for v in e.verts)]
    print('LILI cap edges', len(holes))
    rim = {v for e in holes for v in e.verts}
    caps = bmesh.ops.holes_fill(bm, edges=holes, sides=0)['faces']
    caps = bmesh.ops.triangulate(bm, faces=caps)['faces']
    # Fill faces have no meaningful UVs; borrow each rim vertex's surrounding hide.
    uv = bm.loops.layers.uv.active
    cap_set = set(caps)
    for face in caps:
        for loop in face.loops:
            source = next((l for l in loop.vert.link_loops if l.face not in cap_set), None)
            if source:
                loop[uv].uv = source[uv].uv
    # Relaxing the scar keeps its jagged rim out of the Stage-2 references.
    scar = set(rim)
    for ring in range(4):
        scar |= {e.other_vert(v) for v in list(scar) for e in v.link_edges}
        if ring == 0:
            neighbours = set(scar)
    # Rim faces still carry the removed strand's pale texels; give them plain hide.
    # Rump triangles are large, so only faces touching the rim may change.
    center = sum((v.co for v in rim), Vector()) / len(rim)
    anchor = min((v for v in scar - neighbours), key=lambda v: (v.co - center).length)
    hide_uv = anchor.link_loops[0][uv].uv.copy()
    for vertex in rim:
        for loop in vertex.link_loops:
            for corner in loop.face.loops:
                corner[uv].uv = hide_uv
    for _ in range(24):
        bmesh.ops.smooth_vert(bm, verts=list(scar), factor=0.6, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()


def flatten_belly_nub(obj):
    for v in obj.data.vertices:
        if abs(v.co.x) < 0.03 and 0.17 < v.co.y < 0.27 and v.co.z < 0.185:
            v.co.z = 0.185
    obj.data.update()


def add_short_tail(obj):
    """One thick, centred tail survives image-to-3D better than a thin curl."""
    rear = max((v.co for v in obj.data.vertices if abs(v.co.x) < 0.03 and abs(v.co.z - 0.43) < 0.02), key=lambda c: c.y)
    root = Vector((0, rear.y - 0.015, 0.43))
    rings, sides = 18, 10
    vertices, faces = [], []
    for j in range(rings + 1):
        t = j / rings
        center = root + Vector((0.028 * math.sin(t * math.tau), 0.085 * t, 0.045 * math.sin(t * math.pi) - 0.05 * t))
        r = 0.022 * (1 - t) ** 0.8 + 0.008
        vertices += [tuple(center + Vector((r * math.cos(k * math.tau / sides), 0, r * math.sin(k * math.tau / sides)))) for k in range(sides)]
    for j in range(rings):
        for k in range(sides):
            n = (k + 1) % sides
            faces.append((j * sides + k, (j + 1) * sides + k, (j + 1) * sides + n, j * sides + n))
    faces.append(tuple(rings * sides + k for k in range(sides)))
    mesh = bpy.data.meshes.new('short tail')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    material = bpy.data.materials.new('tail ochre')
    material.use_nodes = True
    material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.3, 0.11, 0.03, 1)
    mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    tail = bpy.data.objects.new('tail', mesh)
    bpy.context.scene.collection.objects.link(tail)
    bpy.ops.object.select_all(action='DESELECT')
    tail.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()


def warm_hide():
    image = bpy.data.images['diffuse']
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(-1, 4)
    pixels[:, :3] *= HIDE_TINT
    image.pixels.foreach_set(pixels.ravel())
    image.update()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('views')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(args.input)
    straighten_head(obj)
    remove_tail_strands(obj)
    flatten_belly_nub(obj)
    add_short_tail(obj)
    warm_hide()
    Path(args.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), args.views)


main()
