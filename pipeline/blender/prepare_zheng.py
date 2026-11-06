"""Inspect/prepare Zheng torso and its separate straight feline-tail master."""
import argparse
import sys
from pathlib import Path
import bmesh
import bpy
import math
from mathutils import Matrix, Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input')
p.add_argument('output')
p.add_argument('views')
p.add_argument('--part', choices=['body', 'tail'], default='body')
p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
p.add_argument('--inspect', action='store_true')
p.add_argument('--cut-y', type=float, default=0.29)
p.add_argument('--round-tail', action='store_true')
p.add_argument('--opposite-side', action='store_true')
p.add_argument('--high-clean', action='store_true')
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
obj = load(a.input)
vs = [v.co for v in obj.data.vertices]
print('BOUNDS', [(min(v[i] for v in vs), max(v[i] for v in vs)) for i in range(3)])
for lo in [0.20,0.25,0.30,0.35,0.40,0.45]:
    pts = [v for v in vs if lo < v.y < lo+.05]
    if pts:
        print('REAR',lo,'x',min(v.x for v in pts),max(v.x for v in pts),'z',min(v.z for v in pts),max(v.z for v in pts))
if a.inspect and a.part == 'body':
    for z in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]:
        pts = [v for v in vs if abs(v.x) < 0.04 and z <= v.z < z+0.1]
        if pts:
            print('CENTER_REAR', z, max(v.y for v in pts))
if not a.inspect:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    if a.part == 'body' and a.high_clean:
        # Stage two copied the preview's cap into a tiny rump tab and one
        # hock bump. Project only those measured protrusions back into skin;
        # the broad rear legs must never be bisected with the preview plane.
        for v in bm.verts:
            p = v.co
            if abs(p.x) < 0.045 and 0.40 < p.z < 0.60 and p.y > 0.45:
                p.y = 0.45 + (p.y-0.45) * 0.08
            if abs(p.x) > 0.07 and 0.13 < p.z < 0.25 and p.y > 0.455:
                p.y = 0.455 + (p.y-0.455) * 0.08
    elif a.part == 'body':
        # A measured plane behind the rump removes only the tail; no limb
        # reaches this plane. Cap only the new cut, preserving UV seams.
        bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                              plane_co=(0,a.cut_y,0), plane_no=(0,1,0),
                              clear_outer=True, clear_inner=False, dist=1e-6)
        cut = [e for e in bm.edges if e.is_boundary and all(abs(v.co.y-a.cut_y)<1e-4 for v in e.verts)]
        bmesh.ops.holes_fill(bm, edges=cut, sides=0)
    elif a.round_tail:
        # The preview came back as a broad, rounded slab. Preserve its texture
        # and longitudinal detail while correcting its cross-section to a tail.
        lo = [min(v.co[i] for v in bm.verts) for i in range(3)]
        hi = [max(v.co[i] for v in bm.verts) for i in range(3)]
        length = hi[0] - lo[0]
        center_y = (lo[1] + hi[1]) / 2
        center_z = (lo[2] + hi[2]) / 2
        for v in bm.verts:
            t = (v.co.x - lo[0]) / length
            taper = (0.8 + 0.2 * min(t / 0.12, 1)) * max(0.12, (1 - t) ** 0.35)
            u = 2 * (v.co.y - center_y) / (hi[1]-lo[1])
            w = 2 * (v.co.z - center_z) / (hi[2]-lo[2])
            radius = length * 0.0375 * taper
            v.co.y = u * math.sqrt(max(0, 1-w*w/2)) * radius
            v.co.z = w * math.sqrt(max(0, 1-u*u/2)) * radius + length * 0.04
        # Render along the same longitudinal axis used by the quadruped views.
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.pi/2, 4, 'Z'), verts=list(bm.verts))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
Path(a.views).mkdir(parents=True, exist_ok=True)
if a.opposite_side:
    obj.data.transform(Matrix.Rotation(math.pi, 4, 'Z'))
    obj.data.update()
render_views(obj, setup_render(1024), a.views, only_view=a.view)
