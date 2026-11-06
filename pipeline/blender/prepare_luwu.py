"""Prepare the measured Luwu Stage-1 tiger for separate human head/nine tails.

Input: normalized .85m raw/_build/luwu/body_v1_norm.glb.
Remove its native head and isolate the hanging tail by mesh connectivity;
keep all four paws intact, then normalize the remaining torso to .85m.
"""
import argparse
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input')
p.add_argument('output')
p.add_argument('views')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
obj = load(a.input)
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
cap = bpy.data.materials.new('luwu_neck_and_rump_caps')
cap.use_nodes = True
cap.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.58, .30, .10, 1)
obj.data.materials.append(cap)
cap_index = len(obj.data.materials) - 1

# Below z=.30, the welded hanging tail is a separate connected component
# from both hind legs. Split at that height without cutting away leg faces.
bmesh.ops.bisect_plane(
    bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
    plane_co=(0, 0, .30), plane_no=(0, 0, 1), dist=1e-6,
)
remaining = {v for v in bm.verts if v.co.z <= .300001}
islands = []
while remaining:
    stack = [remaining.pop()]
    island = []
    while stack:
        vertex = stack.pop()
        island.append(vertex)
        for edge in vertex.link_edges:
            neighbor = edge.other_vert(vertex)
            if neighbor in remaining:
                remaining.remove(neighbor)
                stack.append(neighbor)
    islands.append(island)
tails = []
for island in islands:
    center = sum((v.co for v in island), Vector()) / len(island)
    if center.y > .32 and abs(center.x) < .04 and len(island) > 100:
        tails.append(island)
if len(tails) != 1:
    raise RuntimeError(f'Expected one isolated hanging tail, found {len(tails)}')
tail = tails[0]
print('LUWU_TAIL_COMPONENT', len(tail), 'verts')
# The cut ring belongs to the retained rump and is capped below.
bmesh.ops.delete(bm, geom=[v for v in tail if v.co.z < .299999], context='VERTS')

# The tail's fused upper ridge protrudes behind the natural rump. Bring it
# onto the surrounding rump contour, measured at x=+/- .035..065. This only
# changes the central patch above the tail cut; no paw/leg is in this zone.
original = [v.co.copy() for v in bm.verts]
changed = 0
for vertex in bm.verts:
    q = vertex.co
    if abs(q.x) < .035 and q.z >= .299999 and q.y > .29:
        neighbors = [v.y for v in original
                     if .035 <= abs(v.x) <= .065 and abs(v.z - q.z) < .018 and v.y > .2]
        if neighbors:
            limit = max(neighbors)
            if q.y > limit:
                q.y = limit + (q.y - limit) * .02
                changed += 1
print('LUWU_RUMP_RIDGE', changed, 'verts')

# Oblique neck cut preserves the chest/front legs and removes the complete
# tiger face/ears: y=-.20 + .65*(z-.48), removing its forward/upper side.
result = bmesh.ops.bisect_plane(
    bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
    plane_co=(0, -.20, .48), plane_no=(0, -1, .65),
    clear_outer=True, clear_inner=False, dist=1e-6,
)
for edge_set in ([e for e in result['geom_cut'] if isinstance(e, bmesh.types.BMEdge) and e.is_boundary],
                 [e for e in bm.edges if e.is_boundary and all(abs(v.co.z - .30) < 1e-5 for v in e.verts)]):
    filled = bmesh.ops.holes_fill(bm, edges=edge_set, sides=0)
    for face in filled['faces']:
        face.material_index = cap_index
loose = [v for v in bm.verts if not v.link_faces]
bmesh.ops.delete(bm, geom=loose, context='VERTS')
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
bm.to_mesh(obj.data)
bm.free()

points = [v.co for v in obj.data.vertices]
lo = Vector(tuple(min(v[i] for v in points) for i in range(3)))
hi = Vector(tuple(max(v[i] for v in points) for i in range(3)))
scale = .85 / max(hi.x - lo.x, hi.y - lo.y)
obj.data.transform(Matrix.Scale(scale, 4) @ Matrix.Translation((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)))
print('LUWU_TORSO_SCALE', scale)
print('LUWU_TORSO_DIMENSIONS', tuple(round((hi[i] - lo[i]) * scale, 6) for i in range(3)))
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(obj, setup_render(1024), a.views)
