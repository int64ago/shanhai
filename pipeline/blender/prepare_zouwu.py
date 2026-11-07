"""Offline HIGH reuse for Zouwu; no generation or network requests.

Inputs: Zheng body_high_fixed.glb and tail_high_norm.glb, derived from the
Extreme-High zheng-body-max / zheng-tail-max masters. Keep the original dense
geometry and UV fur detail. Flatten only the measured forehead horn, paint
five-colour fur, and extend one tail to exactly 2.4 nose-to-rump lengths.
The classical text specifies only 尾長于身; 2.4 is an artistic choice.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def recolour(obj):
    shader = next(n for n in obj.data.materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    image = shader.inputs['Base Color'].links[0].from_node.image
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    rgba = pixels.reshape(height, width, 4)
    original = rgba.copy()
    uv = obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    # Cinnabar shoulders, ochre flank, malachite rump; original white and ink
    # spots complete the five colours. Preserve eyes, nose, muzzle and shading.
    colours = np.array([[0.73, 0.20, 0.13], [0.77, 0.49, 0.13], [0.08, 0.38, 0.34]])
    for tri in obj.data.loop_triangles:
        coords = np.array([(uv[i].uv.x * (width - 1), uv[i].uv.y * (height - 1)) for i in tri.loops])
        lo = np.maximum(np.floor(coords.min(axis=0)).astype(int) - 1, 0)
        hi = np.minimum(np.ceil(coords.max(axis=0)).astype(int) + 1, [width - 1, height - 1])
        xx, yy = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        a, b, c = coords
        den = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
        if abs(den) < 1e-8:
            continue
        u = ((b[1]-c[1])*(xx-c[0]) + (c[0]-b[0])*(yy-c[1])) / den
        v = ((c[1]-a[1])*(xx-c[0]) + (a[0]-c[0])*(yy-c[1])) / den
        points = np.array([obj.data.vertices[i].co[:] for i in tri.vertices])
        y = u*points[0, 1] + v*points[1, 1] + (1-u-v)*points[2, 1]
        t = np.clip((y + 0.25) / 0.65 * 2, 0, 2)
        i = np.minimum(t.astype(int), 1)
        f = (t-i)[..., None]
        colour = colours[i]*(1-f) + colours[i+1]*f
        src = original[lo[1]:hi[1]+1, lo[0]:hi[0]+1, :3]
        red = (src[..., 0] > src[..., 1]*1.25) & (src[..., 0] > src[..., 2]*1.3)
        mask = (u >= -0.02) & (v >= -0.02) & (u+v <= 1.02) & red
        # Paint the now-flat horn surface into the forehead coat as well.
        px = u*points[0, 0] + v*points[1, 0] + (1-u-v)*points[2, 0]
        pz = u*points[0, 2] + v*points[1, 2] + (1-u-v)*points[2, 2]
        horn = (abs(px) < .044) & (y < -.39) & (pz > .855) & (abs(src[..., 0]-src[..., 1]) < .08) & (src[..., 0] < .42)
        inside = (u >= -.02) & (v >= -.02) & (u+v <= 1.02)
        shade = np.clip(src[..., 0:1] / 0.68, 0.15, 1.25)
        dst = rgba[lo[1]:hi[1]+1, lo[0]:hi[0]+1, :3]
        dst[mask] = np.clip(colour*shade, 0, 1)[mask]
        dst[horn & inside] = (colour * .78)[horn & inside]
    image.pixels.foreach_set(rgba.ravel())
    image.update()
    image.file_format = 'PNG'
    image.pack()


def body(args):
    obj = load(args.body)
    # Preserve authored normals and transform the small flattened horn patch
    # analytically. No vertex-normal recomputation on degenerate AI triangles.
    normals = [n.vector.copy() for n in obj.data.corner_normals]
    changed = set()
    hocks = set()
    for vertex in obj.data.vertices:
        p = vertex.co
        roof = 0.902 + 0.50*(p.y + 0.4) - 3*p.x*p.x
        if abs(p.x) < 0.044 and p.y < -0.39 and p.z > roof:
            p.z = roof + (p.z-roof)*0.015
            changed.add(vertex.index)
        # The inherited high master has a small spurious hock tab behind each
        # hind leg. Compress only that measured band; keep all paw geometry.
        if .13 < p.z < .25 and p.y > .455:
            p.y = .455 + (p.y-.455)*.02
            hocks.add(vertex.index)
    for loop, normal in zip(obj.data.loops, normals):
        if loop.vertex_index in changed:
            p = obj.data.vertices[loop.vertex_index].co
            # J^-T for z'=0.015z + .985*roof(x,y).
            normal.x += 6*p.x*.985*normal.z/.015
            normal.y -= .50*.985*normal.z/.015
            normal.z /= .015
            if normal.length > 1e-8:
                normal.normalize()
        if loop.vertex_index in hocks:
            normal.y /= .02
            if normal.length > 1e-8:
                normal.normalize()
    obj.data.normals_split_custom_set(normals)
    obj.data.update()
    recolour(obj)
    length = max(v.co.y for v in obj.data.vertices) - min(v.co.y for v in obj.data.vertices)
    bpy.ops.export_scene.gltf(filepath=str(args.work/'body_prepared.glb'), export_format='GLB', use_selection=True, export_animations=False)
    args.views.mkdir(parents=True, exist_ok=True)
    cam = setup_render(1024)
    render_views(obj, cam, str(args.views))
    # Additional opposite side confirms the tiny original rump cap has not
    # damaged either hind leg. No new tail-trimming plane is used.
    from mathutils import Matrix
    obj.data.transform(Matrix.Rotation(math.pi, 4, 'Z'))
    left = args.views/'left'
    left.mkdir(exist_ok=True)
    render_views(obj, cam, str(left), only_view='side')
    print('ZOUWU_BODY', len(obj.data.vertices), len(obj.data.polygons), 'horn vertices', len(changed), 'length', length)
    return length


def tail(args, length):
    obj = load(args.tail)
    pts = [v.co.copy() for v in obj.data.vertices]
    spans = [max(p[i] for p in pts)-min(p[i] for p in pts) for i in range(3)]
    axis = max(range(3), key=lambda i: spans[i])
    if axis != 0:
        raise ValueError(f'Expected +X tail master, got spans {spans}')
    lo, hi = min(p.x for p in pts), max(p.x for p in pts)
    cy = (min(p.y for p in pts)+max(p.y for p in pts))/2
    cz = (min(p.z for p in pts)+max(p.z for p in pts))/2
    sx, sy, sz = length*2.4/(hi-lo), .075/spans[1], .075/spans[2]
    normals = [n.vector.copy() for n in obj.data.corner_normals]
    transforms = []
    for vertex in obj.data.vertices:
        p = vertex.co
        u, w = 2*(p.y-cy)/spans[1], 2*(p.z-cz)/spans[2]
        fy, fz = math.sqrt(max(.01, 1-w*w/2)), math.sqrt(max(.01, 1-u*u/2))
        # Map the rectangular master cross-section to a rounded tail while
        # retaining its original UVs and dense surface; use J^-T for normals.
        transforms.append(Matrix(((sx, 0, 0), (0, sy*fy, -.0375*u*w/(2*fy)*2/spans[2]), (0, -.0375*w*u/(2*fz)*2/spans[1], sz*fz))).inverted_safe().transposed())
        p.x = (p.x-lo)*sx
        p.y = .0375*u*fy
        p.z = .0375*w*fz
    for loop, n in zip(obj.data.loops, normals):
        n[:] = transforms[loop.vertex_index] @ n
        if n.length > 1e-8:
            n.normalize()
        else:
            n[:] = (0, 0, 1)
    obj.data.normals_split_custom_set(normals)
    obj.data.update()
    bpy.ops.export_scene.gltf(filepath=str(args.work/'tail_prepared.glb'), export_format='GLB', use_selection=True, export_animations=False)
    info = {'bodyLength': length, 'tailLength': length*2.4, 'tailBodyRatio': 2.4, 'tailVertices': len(obj.data.vertices), 'tailTriangles': len(obj.data.polygons)}
    (args.work/'measurements.json').write_text(json.dumps(info, indent=2))
    print('ZOUWU_TAIL', info)


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('body')
p.add_argument('tail')
p.add_argument('work', type=Path)
p.add_argument('views', type=Path)
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
a.work.mkdir(parents=True, exist_ok=True)
tail(a, body(a))
