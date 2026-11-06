"""Remove the preview's incorrect goat head/hooves before modular replacements."""
import argparse
import math
import sys
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render

p = argparse.ArgumentParser()
p.add_argument('input')
p.add_argument('output')
p.add_argument('views')
p.add_argument('--inspect', action='store_true')
p.add_argument('--part', choices=['body', 'hand'], default='body')
p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
obj = load(a.input)
for y in [-.5,-.4,-.3,-.2,-.1,0,.1,.2,.3,.4]:
    pts = [v.co for v in obj.data.vertices if y <= v.co.y < y+.1]
    if pts:
        print('SLICE', y, 'x', min(v.x for v in pts), max(v.x for v in pts), 'z', min(v.z for v in pts), max(v.z for v in pts))
if not a.inspect:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    if a.part == 'body':
        cap = bpy.data.materials.new('neck_and_ankle_caps')
        cap.use_nodes = True
        cap.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.34,.22,.135,1)
        obj.data.materials.append(cap)
        cap_index = len(obj.data.materials)-1
        # Initial-preview dimensions are measured in the emitted slices.
        for coordinate, normal in [((0,-.25,.30),(0,-1,.43)), ((0,0,.075),(0,0,-1))]:
            result = bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces), plane_co=coordinate, plane_no=normal, clear_outer=True, clear_inner=False, dist=1e-6)
            edges = [e for e in result['geom_cut'] if isinstance(e,bmesh.types.BMEdge) and e.is_boundary]
            filled = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
            for face in filled['faces']:
                face.material_index = cap_index
    else:
        # The generated hand has four fingers and two thumbs. Remove the
        # supernumerary +X thumb outside the measured palm boundary.
        remove = [v for v in bm.verts if v.co.x > .045 and v.co.z > .075]
        bmesh.ops.delete(bm, geom=remove, context='VERTS')
        edges = [e for e in bm.edges if e.is_boundary and any(v.co.x > .04 and v.co.z > .07 for v in e.verts)]
        cap = bpy.data.materials.new('palm_cap')
        cap.use_nodes = True
        cap.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.52,.32,.18,1)
        obj.data.materials.append(cap)
        filled = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        for face in filled['faces']:
            face.material_index = len(obj.data.materials)-1
        remaining = set(bm.faces)
        islands = []
        while remaining:
            stack = [remaining.pop()]
            island = []
            while stack:
                face = stack.pop()
                island.append(face)
                for edge in face.edges:
                    for neighbor in edge.link_faces:
                        if neighbor in remaining:
                            remaining.remove(neighbor)
                            stack.append(neighbor)
            islands.append(island)
        largest = max(islands, key=len)
        bmesh.ops.delete(bm, geom=[f for island in islands if island is not largest for f in island], context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(-math.pi/2, 4, 'X'), verts=list(bm.verts))
        lo = min(v.co.z for v in bm.verts)
        span = max(v.co.z for v in bm.verts)-lo
        for v in bm.verts:
            v.co.z = (v.co.z-lo) * .055 / span
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(obj, setup_render(1024), a.views, only_view=a.view)
