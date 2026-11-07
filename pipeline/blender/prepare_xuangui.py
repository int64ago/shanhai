"""Correct fresh Rodin turtle anatomy for four-view refinement and final assembly.
All surfaces are generated; no primitive replacement shell, neck or tail.
"""
import sys, math
from pathlib import Path
import bpy, bmesh
from mathutils import Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import turnaround


def body_correction(obj):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    # Native turtle head and tail must not survive as duplicate organs. These
    # central cuts keep the lateral shoulders, hind legs and shell bridges.
    dead = [f for f in bm.faces if (abs(f.calc_center_median().x) < .15 and f.calc_center_median().y < -.48)
            or (abs(f.calc_center_median().x) < .09 and f.calc_center_median().y > .60 and f.calc_center_median().z < .43)]
    bmesh.ops.delete(bm, geom=dead, context='FACES')
    # Remove disconnected slivers left by the anatomical cuts.
    seen = set(); islands = []
    for face in bm.faces:
        if face in seen: continue
        stack = [face]; island = []; seen.add(face)
        while stack:
            current = stack.pop(); island.append(current)
            for edge in current.edges:
                for adjacent in edge.link_faces:
                    if adjacent not in seen: seen.add(adjacent); stack.append(adjacent)
        islands.append(island)
    largest = max(len(island) for island in islands)
    bmesh.ops.delete(bm, geom=[f for island in islands if len(island) < largest * .01 for f in island], context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    for v in bm.verts:
        z = v.co.z
        # Low, broad turtle rather than a mammal supporting a hemisphere.
        v.co.z = z * .68 if z < .4 else .272 + (z - .4) * .73
    bm.to_mesh(obj.data); bm.free(); obj.data.update()


def main():
    source, output, views, part = sys.argv[sys.argv.index('--') + 1:]
    obj = turnaround.load(source)
    if part == 'body': body_correction(obj)
    obj.name = 'xuangui_' + part
    bpy.ops.export_scene.gltf(filepath=output, export_format='GLB')
    cam = turnaround.setup_render(1024)
    Path(views).mkdir(parents=True, exist_ok=True)
    turnaround.render_views(obj, cam, views)
    pts = [v.co for v in obj.data.vertices]
    print('XUANGUI_BOUNDS', part, [[round(fn(p[i] for p in pts), 5) for i in range(3)] for fn in (min, max)])

if __name__ == '__main__': main()
