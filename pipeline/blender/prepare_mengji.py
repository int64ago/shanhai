"""Inspect/prepare the Mengji torso and render Stage 2 reference views."""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def connected_islands(bm):
    seen, islands = set(), []
    for start in bm.verts:
        if start in seen:
            continue
        seen.add(start)
        island, stack = [], [start]
        while stack:
            v = stack.pop()
            island.append(v)
            for e in v.link_edges:
                other = e.other_vert(v)
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        islands.append(island)
    return islands


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input')
p.add_argument('output')
p.add_argument('views')
p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
p.add_argument('--inspect', action='store_true')
p.add_argument('--cut-y', type=float, help='Remove everything behind this plane and cap the new cut')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])

obj = load(a.input)
vs = [v.co for v in obj.data.vertices]
print('BOUNDS', [(round(min(v[i] for v in vs), 4), round(max(v[i] for v in vs), 4)) for i in range(3)])
hi = max(v.y for v in vs)
for lo in [hi - 0.25 + 0.05 * i for i in range(5)]:
    pts = [v for v in vs if lo < v.y < lo + 0.05]
    if pts:
        print('REAR', round(lo, 3), 'x', round(min(v.x for v in pts), 3), round(max(v.x for v in pts), 3),
              'z', round(min(v.z for v in pts), 3), round(max(v.z for v in pts), 3))

if not a.inspect:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # Weld UV-seam duplicates first so the cut cannot leave open slivers.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    if a.cut_y is not None:
        bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                               plane_co=(0, a.cut_y, 0), plane_no=(0, 1, 0),
                               clear_outer=True, clear_inner=False, dist=1e-6)
        # The tail hugged the thigh, so the plane leaves a detached remnant behind.
        islands = connected_islands(bm)
        print('ISLANDS', sorted((len(i) for i in islands), reverse=True)[:6])
        keep = max(islands, key=len)
        bmesh.ops.delete(bm, geom=[v for i in islands if i is not keep for v in i], context='VERTS')
        cut = [e for e in bm.edges if e.is_boundary and all(abs(v.co.y - a.cut_y) < 1e-4 for v in e.verts)]
        cap = bmesh.ops.holes_fill(bm, edges=cut, sides=0)['faces']
        print('CAP faces', len(cap), 'open edges left', sum(e.is_boundary for e in bm.edges))
        # Interpolated cap UVs cross unrelated texture islands; pin them to plain back fur.
        uv = bm.loops.layers.uv.active
        back = max((v for v in bm.verts if abs(v.co.x) < 0.02 and 0.15 < v.co.y < 0.25), key=lambda v: v.co.z)
        white = back.link_loops[0][uv].uv.copy()
        for face in cap:
            for loop in face.loops:
                loop[uv].uv = white
        # Round the truncated rump so the reference silhouette is not a flat wall.
        for v in bm.verts:
            if v.co.y > a.cut_y - 0.09:
                t = min(1.0, (v.co.y - (a.cut_y - 0.09)) / 0.09)
                r = min(1.0, math.hypot(v.co.x, v.co.z - 0.43) / 0.2)
                v.co.y -= 0.045 * r * r * t * t
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)

Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(obj, setup_render(1024), a.views, only_view=a.view)
