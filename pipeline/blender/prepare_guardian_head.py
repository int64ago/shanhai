"""Remove the generated collar from the shared Luwu/Kaiming human-head master."""
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
p.add_argument('--cut-height', type=float, default=.075)
p.add_argument('--length', type=float, default=.27)
p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
obj = load(a.input)
cap = bpy.data.materials.new('neck_cap')
cap.use_nodes = True
cap.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.52, .33, .20, 1)
obj.data.materials.append(cap)
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
cut = bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces), plane_co=(0, 0, a.cut_height), plane_no=(0, 0, -1), clear_outer=True, clear_inner=False, dist=1e-6)
edges = [e for e in cut['geom_cut'] if isinstance(e, bmesh.types.BMEdge) and e.is_boundary]
filled = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
for face in filled['faces']:
    face.material_index = len(obj.data.materials) - 1
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
bm.to_mesh(obj.data)
bm.free()
points = [v.co for v in obj.data.vertices]
lo = Vector(tuple(min(v[i] for v in points) for i in range(3)))
hi = Vector(tuple(max(v[i] for v in points) for i in range(3)))
obj.data.transform(Matrix.Translation((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)))
scale = a.length / max(hi.x - lo.x, hi.y - lo.y)
obj.data.transform(Matrix.Scale(scale, 4))
print('HEAD_CLEAN', 'cut', a.cut_height, 'scale', scale, 'height', (hi.z - lo.z) * scale)
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(obj, setup_render(1024), a.views, only_view=a.view)
