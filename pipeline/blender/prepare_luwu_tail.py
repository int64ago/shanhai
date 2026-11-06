"""Round Luwu's slab-shaped Stage 1 tail; preserve UVs and export root-to-tip +X."""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, setup_render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    parser.add_argument('--high', action='store_true', help='Inspect/reorient Stage 2; preserve an already round tail')
    parser.add_argument('--length', type=float)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(args.input)
    vertices = obj.data.vertices
    if args.high:
        dimensions = [max(v.co[i] for v in vertices) - min(v.co[i] for v in vertices) for i in range(3)]
        axis = max(range(3), key=lambda i: dimensions[i])
        if axis == 1:
            obj.data.transform(Matrix.Rotation(-math.pi / 2, 4, 'Z'))
        elif axis == 2:
            obj.data.transform(Matrix.Rotation(math.pi / 2, 4, 'Y'))
        xmin = min(v.co.x for v in vertices)
        span = max(v.co.x for v in vertices) - xmin
        def end_width(start, stop):
            points = [v.co for v in vertices if start <= (v.co.x - xmin) / span <= stop]
            return max(max(p[i] for p in points) - min(p[i] for p in points) for i in [1, 2])
        if end_width(0.80, 0.95) > end_width(0.05, 0.20):
            obj.data.transform(Matrix.Rotation(math.pi, 4, 'Z'))
        print('HIGH_LONG_AXIS', axis, 'ROOT', 'broader endpoint -> minimum X')
    if args.length:
        span = max(v.co.x for v in vertices) - min(v.co.x for v in vertices)
        obj.data.transform(Matrix.Scale(args.length / span, 4))
    lo = Vector(tuple(min(v.co[i] for v in vertices) for i in range(3)))
    hi = Vector(tuple(max(v.co[i] for v in vertices) for i in range(3)))
    size = hi - lo
    length = size.x
    radius = length / 24
    if min(size) <= 0:
        raise RuntimeError('Tail has a degenerate bounding box')
    print('INPUT_BOUNDS', tuple(lo), tuple(hi))
    aspect = max(size.y, size.z) / min(size.y, size.z)
    round_cross_section = not args.high or aspect > 1.6
    print('CROSS_SECTION_ASPECT', aspect, 'ROUNDING', round_cross_section)
    # The slab is slightly warped. Measure each longitudinal neighborhood so
    # upper/lower surfaces straddle the local center before radial projection.
    slices = [[] for _ in range(96)]
    for vertex in vertices:
        index = min(95, int((vertex.co.x - lo.x) / length * 96))
        slices[index].append(vertex.co.copy())
    section_bounds = []
    for index in range(96):
        points = [p for group in slices[max(0, index - 1):min(96, index + 2)] for p in group]
        section_bounds.append((min(p.y for p in points), max(p.y for p in points),
                               min(p.z for p in points), max(p.z for p in points)))
    for vertex in vertices:
        p = vertex.co
        t = max(0, min(1, (p.x - lo.x) / length))
        if not round_cross_section:
            p.x -= lo.x
            p.y -= (lo.y + hi.y) / 2
            p.z -= (lo.z + hi.z) / 2
            continue
        ymin, ymax, zmin, zmax = section_bounds[min(95, int(t * 96))]
        u = max(-1, min(1, 2 * (p.y - ymin) / max(1e-8, ymax - ymin) - 1))
        w = max(-1, min(1, 2 * (p.z - zmin) / max(1e-8, zmax - zmin) - 1))
        # Project the closed slab surface onto a circular cross-section.
        # Global thickness scaling alone preserves its broad flat upper face.
        # A narrow rounded root leaves room for nine attachments; the distal
        # half tapers smoothly to a closed tip.
        root = min(1, t / 0.14)
        root = (0.64 + 0.36 * root * root * (3 - 2 * root)) * math.sqrt(min(1, t / 0.025))
        tip = min(1, ((1 - t) / 0.5) ** 0.55)
        r = radius * root * tip
        angle = math.atan2(w, u)
        p.x = t * length
        p.y = math.cos(angle) * r
        p.z = math.sin(angle) * r
    obj.data.update()
    obj.name = 'luwu_tail'
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    # Imported glTF custom normals still describe the flat slab. Zero vectors
    # ask Blender to derive smooth normals from the corrected surface instead.
    obj.data.normals_split_custom_set([(0, 0, 0)] * len(obj.data.loops))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB',
                              use_selection=True, export_animations=False)
    diameter = max(max(v.co[i] for v in vertices) - min(v.co[i] for v in vertices) for i in [1, 2])
    print('TAIL_LENGTH', length, 'MAX_DIAMETER', diameter, 'RATIO', length / diameter)
    print('ROOT_X', min(v.co.x for v in vertices), 'TIP_X', max(v.co.x for v in vertices))
    print('VERTS', len(vertices), 'FACES', len(obj.data.polygons))

    # A tail has no facial front. Show four longitudinal surfaces rather than
    # nearly empty end-on images, so Stage 2 sees its taper and cylindrical form.
    cam = setup_render(1024)
    pts = [v.co for v in vertices]
    low = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    center = (low + high) / 2
    cam.data.ortho_scale = length * 1.15
    Path(args.views).mkdir(parents=True, exist_ok=True)
    for name, offset in [
        ('34', Vector((0.42, -1, 0.48))),
        ('side', Vector((0, -1, 0))),
        ('front', Vector((0, 0, 1))),
        ('back', Vector((0, 1, 0))),
    ]:
        shot = cam.copy()
        shot.data = cam.data.copy()
        bpy.context.scene.collection.objects.link(shot)
        location = center + offset * length * 3
        rotation = (center - location).to_track_quat('-Z', 'Y')
        shot.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1, 1, 1)))
        bpy.context.scene.camera = shot
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath = str(Path(args.views) / f'view_{name}.png')
        bpy.ops.render.render(write_still=True)
        print('VIEW', name)


main()
