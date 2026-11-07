"""Adapt the verified, tailless Tiangou feline master into Huan without generation.

Input is the decoded Tiangou body normalized to length 1m. Smooth away both native
eye sockets and replace their painted eye regions with pale fur, then embed ONE
central eye. Bind material prefix huan_eye rigidly to head when running the generic
quadruped rigger. The input master already has no native tail; three Zheng tails
are attached by the runtime component.

Usage:
  blender -b --python pipeline/blender/prepare_huan.py -- master_norm.glb body_clean.glb concept/huan
  blender -b --python pipeline/blender/rig_quadruped.py -- body_clean.glb body_rig.glb --rigid-part huan_eye:head --rigid-part huan_head:head
  blender -b --python pipeline/blender/prepare_huan.py -- body_rig.glb body_stitched.glb --stitch-skin
"""
import argparse
from collections import defaultdict
import math
from pathlib import Path
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = mat.node_tree.nodes['Principled BSDF']
    # inkify reads texture color, so bake even solid eye colors into tiny maps.
    image = bpy.data.images.new(name, 4, 4)
    # A tiny grain prevents optimize/prune from replacing solid maps with
    # baseColorFactor, which the project's texture-driven ink shader ignores.
    pixels = []
    for i in range(16):
        grain = 0.006 if i % 2 else -0.006
        pixels.extend([*(max(0, min(1, channel + grain)) for channel in color), 1])
    image.pixels.foreach_set(pixels)
    image.pack()
    texture = mat.node_tree.nodes.new('ShaderNodeTexImage')
    texture.image = image
    mat.node_tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    shader.inputs['Roughness'].default_value = 0.72
    return mat


def erase_lateral_eyes(body):
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    # The master has integrated eye surfaces, not separate eyeball objects.
    # Relax the entire upper muzzle so neither old socket survives as a second eye.
    region = [v for v in bm.verts if v.co.y < -0.37 and 0.648 < v.co.z < 0.745]
    for _ in range(22):
        bmesh.ops.smooth_vert(bm, verts=region, factor=0.45, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    # Replace residual eyelid relief with a continuous convex forehead. Relaxing
    # alone can leave closed-eye outlines, which would still read as extra eyes.
    for vertex in bm.verts:
        point = vertex.co
        d = (point.x - 0.01) / 0.12
        if point.y < -0.395 and 0.645 < point.z < 0.755 and abs(d) < 0.95:
            blend = min(1, (point.z - 0.645) / 0.026, (0.755 - point.z) / 0.026)
            blend = blend * blend * (3 - 2 * blend)
            target_y = -0.37 - 0.105 * math.sqrt(1 - d * d)
            point.y += (target_y - point.y) * blend
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(body.data)
    bm.free()
    # Drop imported custom normals that still carry the old eyelid relief.
    body.data.normals_split_custom_set([(0, 0, 0)] * len(body.data.loops))

    # Inpaint only the dark native eye texels in the original atlas. Retaining
    # surrounding fur avoids a rectangular replacement-material border on cheeks.
    source_material = body.data.materials[0]
    shader = source_material.node_tree.nodes['Principled BSDF']
    # The original normal map also encodes eyelids. Runtime ink ignores it;
    # disconnect it so offline views do not show the erased eyes as embossing.
    for link in list(shader.inputs['Normal'].links):
        source_material.node_tree.links.remove(link)
    texture = shader.inputs['Base Color'].links[0].from_node
    image = texture.image.copy()
    texture.image = image
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    mask = np.zeros((height, width), dtype=bool)
    uv = body.data.uv_layers.active
    changed = 0
    for face in body.data.polygons:
        center = face.center
        if not (center.y < -0.35 and 0.635 < center.z < 0.758):
            continue
        coords = [np.array(uv.data[index].uv) * (width - 1, height - 1) for index in face.loop_indices]
        for j in range(1, len(coords) - 1):
            a, b, c = coords[0], coords[j], coords[j + 1]
            lower = np.maximum(np.floor(np.minimum(np.minimum(a, b), c)).astype(int) - 1, 0)
            upper = np.minimum(np.ceil(np.maximum(np.maximum(a, b), c)).astype(int) + 1, (width - 1, height - 1))
            xs, ys = np.meshgrid(np.arange(lower[0], upper[0] + 1), np.arange(lower[1], upper[1] + 1))
            denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(denominator) < 1e-8:
                continue
            first = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / denominator
            second = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / denominator
            inside = (first >= -0.03) & (second >= -0.03) & (first + second <= 1.03)
            mask[ys[inside], xs[inside]] = True
        changed += 1
    # Cover bilinear texture filtering along the selected UV triangle borders.
    for _ in range(2):
        mask |= np.roll(mask, 1, 0) | np.roll(mask, -1, 0) | np.roll(mask, 1, 1) | np.roll(mask, -1, 1)
    rgb = pixels[:, :, :3]
    bright = rgb[mask & (np.min(rgb, axis=2) > 0.75)]
    if not len(bright):
        raise RuntimeError('Missing pale face fur for eye inpainting')
    fur_color = np.median(bright, axis=0)
    alpha = np.clip((0.82 - np.max(rgb, axis=2)) / 0.14, 0, 1) * mask
    rgb[:] = rgb * (1 - alpha[:, :, None]) + fur_color * alpha[:, :, None]
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    image.pack()
    # Keep the forehead and embedded eye on the same rigid head bone, so neck
    # blending cannot move the skin in front of the eye during idle or alert.
    head_material = body.data.materials[0].copy()
    head_material.name = 'huan_head_fur'
    body.data.materials.append(head_material)
    head_slot = len(body.data.materials) - 1
    for face in body.data.polygons:
        if face.center.y < -0.34 and face.center.z > 0.55:
            face.material_index = head_slot
    print('HUAN inpainted eye-region faces', changed, 'fur', fur_color.tolist())


def sphere(name, location, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def embed_single_eye(body):
    tree = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())
    x, z = 0.018, 0.714
    hit = tree.ray_cast(Vector((x, -1, z)), Vector((0, 1, 0)))
    if hit[0] is None:
        raise RuntimeError('Missing forehead skin for the central eye')
    skin_y = hit[0].y
    # All layers overlap the forehead. The socket is not a hovering eyeball.
    pieces = [sphere('huan_eye_socket', (x, skin_y + 0.006, z), (0.045, 0.011, 0.033), material('huan_eye_socket', (0.18, 0.10, 0.055))),
              sphere('huan_eye_sclera', (x, skin_y - 0.002, z), (0.040, 0.007, 0.028), material('huan_eye_sclera', (0.67, 0.54, 0.29))),
              sphere('huan_eye_iris', (x, skin_y - 0.009, z), (0.023, 0.003, 0.025), material('huan_eye_iris', (0.48, 0.24, 0.045))),
              sphere('huan_eye_pupil', (x, skin_y - 0.012, z), (0.008, 0.001, 0.022), material('huan_eye_pupil', (0.012, 0.014, 0.01))),
              sphere('huan_eye_glint', (x - 0.009, skin_y - 0.013, z + 0.011), (0.005, 0.0005, 0.005), material('huan_eye_glint', (0.94, 0.9, 0.75)))]
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    for piece in pieces:
        piece.select_set(True)
        if piece.data.uv_layers:
            piece.data.uv_layers[0].name = body.data.uv_layers.active.name
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    print('HUAN one embedded eye at', (x, skin_y, z), 'native tails: zero')


def stitch_skin(body):
    # UV seams split during glTF export. Equal rest positions must keep equal skin
    # weights so smoothing on separate islands cannot open animated cracks.
    tree = KDTree(len(body.data.vertices))
    for v in body.data.vertices:
        tree.insert(v.co, v.index)
    tree.balance()
    seen = set()
    for seed in body.data.vertices:
        if seed.index in seen:
            continue
        indices, pending = {seed.index}, [seed.index]
        while pending:
            current = pending.pop()
            for _, index, _ in tree.find_range(body.data.vertices[current].co, 1e-5):
                if index not in indices:
                    indices.add(index)
                    pending.append(index)
        seen.update(indices)
        if len(indices) < 2:
            continue
        weights = defaultdict(float)
        for index in indices:
            for g in body.data.vertices[index].groups:
                weights[g.group] += g.weight
        strongest = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:4]
        total = sum(weight for _, weight in strongest)
        if not total:
            raise RuntimeError('Unweighted Huan seam')
        indices = sorted(indices)
        for group in body.vertex_groups:
            group.remove(indices)
        for index, weight in strongest:
            body.vertex_groups[index].add(indices, weight / total, 'REPLACE')
    print('HUAN skin seams synchronized')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('views', nargs='?')
    p.add_argument('--stitch-skin', action='store_true')
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if a.stitch_skin:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=a.input)
        body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.vertex_groups)
        stitch_skin(body)
    else:
        body = load(a.input)
        erase_lateral_eyes(body)
        embed_single_eye(body)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', export_animations=a.stitch_skin,
                             export_animation_mode='NLA_TRACKS', export_skins=a.stitch_skin, export_def_bones=False)
    if a.views:
        Path(a.views).mkdir(parents=True, exist_ok=True)
        camera = setup_render(1024)
        render_views(body, camera, a.views)
        # Mandatory opposite-side check confirms no old lateral eye remains.
        center = Vector((0, 0, 0.414))
        camera.location = center + Vector((-3, 0, 0))
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.scene.camera = camera
        bpy.context.scene.render.filepath = str(Path(a.views) / 'view_opposite.png')
        bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    main()
