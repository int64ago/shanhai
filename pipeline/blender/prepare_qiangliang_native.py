"""Bounded native High terminal smoothing; no remeshing or UV edits.

Blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python pipeline/blender/prepare_qiangliang_native.py -- SOURCE OUTPUT
"""
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ramp(a, b, value):
    t = max(0.0, min(1.0, (value - a) / (b - a)))
    return t * t * (3 - 2 * t)


def mask(p):
    x, y, z = p
    if abs(x) > .235:
        # Final local correction extends above the wrist pit, below the elbow.
        w = ramp(.435, .460, z) * (1 - ramp(.565, .595, z))
        w *= ramp(.235, .265, abs(x))
        if y > .028 and z < .470:
            w *= ramp(.450, .470, z)
        return w
    if z < .145:
        # Include the groove's lower lip; retain distal split and central rear nub.
        w = ramp(.025, .047, z) * (1 - ramp(.110, .145, z))
        if y < -.065:
            w *= ramp(.045, .068, z)
        if y > .045 and abs(abs(x) - .105) < .014 and z < .065:
            w *= ramp(.050, .065, z)
        return w
    return 0.0


def main(args=None):
    args = sys.argv[sys.argv.index('--') + 1:] if args is None else args
    source, output = map(lambda p: Path(p).resolve(), args[:2])
    source_sha = sha(source)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(meshes) == 1 and meshes[0].name == 'model'
    obj = meshes[0]
    mesh = obj.data
    topology = [(tuple(p.vertices), p.material_index) for p in mesh.polygons]
    original_normals = [normal.vector.copy() for normal in mesh.corner_normals]
    uvs = [[tuple(v.uv) for v in layer.data] for layer in mesh.uv_layers]
    original = [obj.matrix_world @ v.co for v in mesh.vertices]
    low = Vector([min(p[i] for p in original) for i in range(3)])
    high = Vector([max(p[i] for p in original) for i in range(3)])
    height = high.z - low.z
    offset = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
    # Logical weld only: synchronize UV seam duplicates without changing any index.
    groups, index, points = {}, [], []
    for p in original:
        key = tuple(round(float(v), 6) for v in p)
        if key not in groups:
            groups[key] = len(points)
            points.append((p - offset) / height)
        index.append(groups[key])
    neighbors = [set() for p in points]
    for edge in mesh.edges:
        a, b = (index[i] for i in edge.vertices)
        if a != b:
            neighbors[a].add(b)
            neighbors[b].add(a)
    before = [p.copy() for p in points]
    weights = [mask(p) for p in points]
    # Positive Laplacian fills narrow pits; restrained negative pass limits shrinkage.
    # Maximum displacement is 1.2% of body height, with fixed unaffected vertices.
    for cycle in range(65):
        for factor in (.48, -.30):
            updated = [p.copy() for p in points]
            for i, (p, w) in enumerate(zip(points, weights)):
                if not w or not neighbors[i]:
                    continue
                mean = sum((points[j] for j in neighbors[i]), Vector()) / len(neighbors[i])
                delta = p + (mean - p) * (factor * w) - before[i]
                limit = .012 * w
                if delta.length > limit:
                    delta *= limit / delta.length
                updated[i] = before[i] + delta
            points = updated
    inverse = obj.matrix_world.inverted()
    for vertex, group in zip(mesh.vertices, index):
        vertex.co = inverse @ (points[group] * height + offset)
    mesh.update()
    # Synchronize normals across logical seam duplicates only in the edited mask.
    # Preserve the source's custom loop normals everywhere else.
    sums = [Vector() for p in points]
    for polygon in mesh.polygons:
        a, b, c = [mesh.vertices[i].co for i in polygon.vertices]
        normal = (b - a).cross(c - a)
        if normal.length_squared < 1e-20:
            continue
        for i in polygon.vertices:
            sums[index[i]] += normal
    normals = []
    for loop, original_normal in zip(mesh.loops, original_normals):
        group = index[loop.vertex_index]
        normal = sums[group]
        normals.append(normal.normalized() if weights[group] and normal.length_squared > 1e-20
                       else original_normal)
    mesh.normals_split_custom_set(normals)
    assert topology == [(tuple(p.vertices), p.material_index) for p in mesh.polygons]
    assert uvs == [[tuple(v.uv) for v in layer.data] for layer in mesh.uv_layers]
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB',
                             export_animations=False, export_normals=True,
                             export_texcoords=True, export_materials='EXPORT',
                             export_image_format='AUTO', export_yup=True)
    assert sha(source) == source_sha
    moved = [(p - q).length for p, q in zip(points, before)]
    manifest = dict(source=str(source), sourceSha256=source_sha, output=str(output),
                    outputSha256=sha(output), candidate=1, localCorrection=1, topologyChanged=False,
                    uvChanged=False, materialChanged=False, vertexCount=len(mesh.vertices),
                    triangleCount=len(mesh.polygons), iterations=65,
                    movedWeldedVertices=sum(d > 1e-8 for d in moved),
                    maxDisplacementBodyHeights=max(moved),
                    protected='distal split hoof shells, rear dewclaws, elbows, body outside masks')
    output.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('QIANGliANG_NATIVE_CANDIDATE ' + json.dumps(manifest), flush=True)


if __name__ == '__main__':
    main()
