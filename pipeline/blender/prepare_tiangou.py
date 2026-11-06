"""Inspect/prepare Tiangou: detach the draft's native hanging tail and render reference views."""
import argparse
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


CUT_Y = 0.305


def clusters(values, gap=0.012):
    values = sorted(values)
    out = [[values[0], values[0]]]
    for v in values[1:]:
        if v - out[-1][1] > gap:
            out.append([v, v])
        out[-1][1] = v
    return [(round(a, 3), round(b, 3)) for a, b in out]


def inspect(vs):
    print('BOUNDS', [(round(min(v[i] for v in vs), 3), round(max(v[i] for v in vs), 3)) for i in range(3)])
    for z in [i * 0.03 for i in range(2, 17)]:
        pts = [v for v in vs if z <= v.z < z + 0.03 and v.y > 0.15]
        if pts:
            print('REAR_Z', round(z, 2), 'x', clusters([v.x for v in pts]), 'y', clusters([v.y for v in pts]))
    for z in [i * 0.03 for i in range(3, 17)]:
        for y0 in [0.22, 0.25, 0.28, 0.31]:
            pts = [v for v in vs if z <= v.z < z + 0.03 and y0 <= v.y < y0 + 0.03]
            if pts:
                print('TAILSEC z', round(z, 2), 'y', y0, 'x', clusters([v.x for v in pts], 0.008))
    for z in [0.0, 0.03, 0.06, 0.09, 0.12, 0.15]:
        pts = [v for v in vs if z <= v.z < z + 0.03 and v.y < -0.1]
        if pts:
            print('FRONT_Z', z, 'x', clusters([v.x for v in pts]), 'y', clusters([v.y for v in pts]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('views')
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(a.input)
    inspect([v.co for v in obj.data.vertices])
    if a.inspect:
        return
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    uv = bm.loops.layers.uv.active
    # Measured on the v2 draft: hocks end at y=0.30, so this plane only meets
    # the rump cap and the tail tube hanging behind it.
    bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                           plane_co=(0, CUT_Y, 0), plane_no=(0, 1, 0),
                           clear_outer=True, clear_inner=False, dist=1e-6)
    # The tail's walls run between the hind legs in front of that plane: narrow
    # enough below the crotch to spare the legs, wider where they join the rump.
    wall = [v for v in bm.verts if v.co.y > 0.245 and (
        (0.145 < v.co.z < 0.265 and -0.035 < v.co.x < 0.041)
        or (0.265 <= v.co.z < 0.30 and v.co.y > 0.255 and -0.046 < v.co.x < 0.05))]
    bmesh.ops.delete(bm, geom=wall, context='VERTS')
    # Carpal nubs behind both front paws read as stray stubs at this scale.
    for v in bm.verts:
        p = v.co
        if p.y < -0.1 and 0.045 < p.z < 0.09 and p.y > -0.258:
            p.y = -0.258 + (p.y + 0.258) * 0.1
    # Drop slivers the wall cut left behind, then cap only the new rear openings.
    bm.verts.ensure_lookup_table()
    islands, seen = [], set()
    for start in bm.verts:
        if start in seen:
            continue
        stack, island = [start], []
        seen.add(start)
        while stack:
            v = stack.pop()
            island.append(v)
            for e in v.link_edges:
                o = e.other_vert(v)
                if o not in seen:
                    seen.add(o)
                    stack.append(o)
        islands.append(island)
    islands.sort(key=len, reverse=True)
    print('ISLANDS', [len(i) for i in islands[:6]])
    for island in islands[1:]:
        bmesh.ops.delete(bm, geom=island, context='VERTS')
    # One flat rump colour: interpolating UVs across a large cap smears stripes.
    rump = min((f for f in bm.faces if f.calc_center_median().z > 0.46),
               key=lambda f: (f.calc_center_median() - Vector((0, 0.27, 0.48))).length)
    rump_uv = rump.loops[0][uv].uv.copy()
    cut = [e for e in bm.edges if e.is_boundary and all(v.co.y > 0.2 for v in e.verts)]
    print('OPEN_EDGES rear', len(cut), 'elsewhere', sum(e.is_boundary for e in bm.edges) - len(cut))
    filled = bmesh.ops.holes_fill(bm, edges=cut, sides=0)['faces']
    print('CAP_FACES', len(filled), 'open_left', sum(e.is_boundary for e in bm.edges))
    cap = set(bmesh.ops.triangulate(bm, faces=filled)['faces'])
    made = bmesh.ops.subdivide_edges(bm, edges=list({e for f in cap for e in f.edges}), cuts=3, use_grid_fill=True)
    cap |= {f for f in made['geom'] if isinstance(f, bmesh.types.BMFace)}
    inner = {v for f in cap for v in f.verts}
    cap |= {f for f in bm.faces if all(v in inner for v in f.verts)}
    for face in cap:
        for loop in face.loops:
            loop[uv].uv = rump_uv
    near = [v for v in bm.verts if v.co.y > 0.235 and 0.235 < v.co.z < 0.47 and abs(v.co.x) < 0.09]
    for _ in range(20):
        bmesh.ops.smooth_vert(bm, verts=near, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(a.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), a.views, only_view=a.view)


if __name__ == '__main__':
    main()
