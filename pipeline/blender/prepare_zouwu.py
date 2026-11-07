"""Offline HIGH reuse for Zouwu; no generation or network requests.

Body input: Zheng body_high_fixed.glb from the Extreme-High zheng-body-max
master. The historical tail input is retained for CLI compatibility but its
stretched geometry is discarded. Keep the original dense body and UV fur detail.
Flatten the measured forehead horn, paint five-colour fur, and locally rebuild
a round tail at 2.4 body lengths, matching the existing narrated design.
The classical text specifies only 尾長于身; the ratio is an artistic choice.
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
    """Local round, tapered replacement; the stretched flat master is discarded.

    Dense longitudinal rings give every joint continuous neighbouring weights.
    Analytic surface normals avoid recomputing the old AI mesh's degenerate faces.
    The rest mesh is straight for skin binding; gravity curvature lives in the rig.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rings, sides = 144, 24
    tail_length = length * 2.4
    vertices, faces, normals = [], [], []
    for i in range(rings + 1):
        t = i / rings
        radius = .004 + .045 * (1-t)**.75
        slope = -.045*.75*max(1-t, 1/rings)**(-.25)/tail_length
        for j in range(sides + 1):
            theta = j/sides*math.tau
            vertices.append((tail_length*t, radius*math.cos(theta), radius*math.sin(theta)))
            normals.append(Vector((-slope, math.cos(theta), math.sin(theta))).normalized())
    for i in range(rings):
        for j in range(sides):
            a = i*(sides+1)+j
            faces.append((a, a+1, a+sides+2, a+sides+1))
    # Small rounded end rather than the inherited pointed blade.
    vertices.append((tail_length+.004, 0, 0)); normals.append(Vector((1,0,0)))
    end = len(vertices)-1
    for j in range(sides): faces.append((rings*(sides+1)+j, rings*(sides+1)+j+1, end))
    mesh = bpy.data.meshes.new('zouwu_round_tapered_tail')
    mesh.from_pydata(vertices, [], faces); mesh.update()
    obj = bpy.data.objects.new('zouwu_tail', mesh); bpy.context.collection.objects.link(obj)
    uv = mesh.uv_layers.new(name='tail_coat')
    for polygon in mesh.polygons:
        polygon.use_smooth = True
        for loop_index in polygon.loop_indices:
            index = mesh.loops[loop_index].vertex_index
            uv.data[loop_index].uv = (min(index//(sides+1)/rings,1), (index%(sides+1))/sides)
    mesh.normals_split_custom_set([normals[loop.vertex_index] for loop in mesh.loops])
    # Paint deterministic ochre fur with broken ink rings and a green root that
    # meets the existing malachite rump. No network or texture generation API.
    width, height = 1024, 256
    u, v = np.meshgrid(np.linspace(0,1,width), np.linspace(0,1,height))
    root = np.clip(u/.22,0,1)[...,None]
    colour = np.array([.10,.36,.29])*(1-root)+np.array([.69,.43,.17])*root
    wave = u*11 + .09*np.sin(v*math.tau*3) + .035*np.sin(u*91+v*math.tau*7)
    ring = np.exp(-((np.sin(wave*math.pi))/.26)**2)
    broken = .65+.35*np.sin(v*math.tau*4+u*23)**2
    ink = np.clip(ring*broken*.9 + np.clip((u-.94)/.06,0,1)*.75,0,.92)[...,None]
    fur = (.94+.04*np.sin(u*1800+v*37)+.02*np.sin(v*490+u*57))[...,None]
    pixels = np.ones((height,width,4),dtype=np.float32)
    pixels[:,:,:3] = (colour*(1-ink)+np.array([.065,.055,.042])*ink)*fur
    image = bpy.data.images.new('zouwu_local_tail_coat',width=width,height=height)
    image.pixels.foreach_set(pixels.ravel()); image.pack()
    material = bpy.data.materials.new('zouwu_local_tail'); material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF'); shader.inputs['Roughness'].default_value=.85
    texture = material.node_tree.nodes.new('ShaderNodeTexImage'); texture.image=image
    material.node_tree.links.new(texture.outputs['Color'],shader.inputs['Base Color'])
    mesh.materials.append(material)
    obj.select_set(True); bpy.context.view_layer.objects.active=obj
    bpy.ops.export_scene.gltf(filepath=str(args.work/'tail_prepared.glb'), export_format='GLB', use_selection=True, export_animations=False)
    info = {'bodyLength':length,'tailLength':tail_length+.004,'tailBodyRatio':(tail_length+.004)/length,
            'tailVertices':len(vertices),'tailTriangles':rings*sides*2+sides,'segments':36}
    (args.work/'measurements.json').write_text(json.dumps(info,indent=2))
    print('ZOUWU_TAIL',info)


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('body')
p.add_argument('tail')
p.add_argument('work', type=Path)
p.add_argument('views', type=Path)
p.add_argument('--tail-only-body-length', type=float, help='Rebuild just the local tail, retaining the existing body asset')
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
a.work.mkdir(parents=True, exist_ok=True)
tail(a, a.tail_only_body_length if a.tail_only_body_length is not None else body(a))
