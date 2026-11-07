"""Give Lili's coincident UV-seam vertices identical skin weights.

The generic rigger smooths weights over disconnected UV islands, opening cracks
when Lili breathes or walks. Average only coincident body vertices after rigging;
keep UVs, topology and the four rigid spur bindings intact.

Usage:
  blender --background --factory-startup --python pipeline/blender/stitch_lili_skin.py -- \
      raw/_build/lili/body_rig.glb raw/_build/lili/body_stitched.glb
"""
import argparse
from collections import defaultdict
import sys
from pathlib import Path

import bpy
from mathutils.kdtree import KDTree


def stitch(obj):
    tree = KDTree(len(obj.data.vertices))
    for vertex in obj.data.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()
    seen = set()
    repaired = 0
    for seed in obj.data.vertices:
        if seed.index in seen:
            continue
        # Match normalize.py's weld tolerance without rounding-bin boundaries.
        indices = {seed.index}
        pending = [seed.index]
        while pending:
            current = pending.pop()
            for _, index, _ in tree.find_range(obj.data.vertices[current].co, 1e-5):
                if index not in indices:
                    indices.add(index)
                    pending.append(index)
        seen.update(indices)
        vertices = [obj.data.vertices[index] for index in sorted(indices)]
        if len(vertices) < 2:
            continue
        weights = defaultdict(float)
        for vertex in vertices:
            for group in vertex.groups:
                weights[group.group] += group.weight
        # glTF retains four influences. Choose the same four for every seam copy.
        strongest = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:4]
        total = sum(weight for _, weight in strongest)
        if total <= 0:
            raise RuntimeError(f'{obj.name}: unweighted seam')
        indices = [vertex.index for vertex in vertices]
        for group in obj.vertex_groups:
            group.remove(indices)
        for index, weight in strongest:
            obj.vertex_groups[index].add(indices, weight / total, 'REPLACE')
        repaired += 1
    print(f'LILI stitched {repaired} coincident vertex groups in {obj.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.input)
    bodies = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and obj.vertex_groups]
    if len(bodies) != 1:
        raise RuntimeError(f'Expected one skinned Lili body, got {len(bodies)}')
    stitch(bodies[0])
    # Select the rig and body, excluding any preview lighting or helper meshes.
    bpy.ops.object.select_all(action='DESELECT')
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE' or obj in bodies:
            obj.select_set(True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=args.output,
        export_format='GLB',
        use_selection=True,
        export_animations=True,
        export_animation_mode='NLA_TRACKS',
        export_skins=True,
        export_def_bones=False,
    )
    print('EXPORTED', args.output)


main()
