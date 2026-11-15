"""Inpaint only four native Qiangliang proximal hoof-root UV masks.

No geometry, UV, distal hoof, elbow, or upper tiger-stripe edits. Blender numpy
rasterizes the 3D masks into each original map. Robust boundary samples define
a feathered constant harmonic fill; repaired normal-map vectors normalize.
"""
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def root_mask(p):
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    wrists = smooth(.435, .452, z) * (1 - smooth(.550, .565, z))
    wrists *= smooth(.235, .265, np.abs(x))
    # Distal shells/dewclaws and upper forearm tiger stripes stay untouched.
    wrists *= np.where((y > .028) & (z < .47), smooth(.45, .47, z), 1)
    ankles = smooth(.025, .033, z) * (1 - smooth(.110, .135, z))
    ankles *= 1 - smooth(.20, .235, np.abs(x))
    ankles *= np.where(y < -.065, smooth(.045, .051, z), 1)
    ankles *= np.where((y > .045) & (np.abs(np.abs(x) - .105) < .014) & (z < .065),
                       smooth(.05, .065, z), 1)
    return np.maximum(wrists, ankles)


def raster_mask(mesh, positions, width, height):
    result = np.zeros((height, width), np.float32)
    uv = mesh.uv_layers.active
    for poly in mesh.polygons:
        ids = list(poly.vertices)
        pts = positions[ids]
        # Skip unaffected triangles, including head, torso, elbows and distal soles.
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        if not ((hi[2] > .025 and lo[2] < .135) or
                (hi[2] > .435 and lo[2] < .565 and max(abs(lo[0]), abs(hi[0])) > .235)):
            continue
        coords = np.array([list(uv.data[i].uv) for i in poly.loop_indices])
        coords *= np.array([width, height])
        a, b, c = coords
        low = np.maximum(np.floor(coords.min(axis=0)).astype(int), 0)
        high = np.minimum(np.ceil(coords.max(axis=0)).astype(int), [width - 1, height - 1])
        if np.any(high < low):
            continue
        xx, yy = np.meshgrid(np.arange(low[0], high[0] + 1) + .5,
                             np.arange(low[1], high[1] + 1) + .5)
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-10:
            continue
        wa = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denominator
        wb = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denominator
        wc = 1 - wa - wb
        inside = (wa >= -1e-5) & (wb >= -1e-5) & (wc >= -1e-5)
        p = wa[..., None] * pts[0] + wb[..., None] * pts[1] + wc[..., None] * pts[2]
        value = root_mask(p) * inside
        region = result[low[1]:high[1] + 1, low[0]:high[0] + 1]
        np.maximum(region, value, out=region)
    return result


def boundary_fill(pixels, mask, diffuse):
    # Robust boundary color rejects the baked dark pits, tiger stripes and empty
    # UV padding. A constant harmonic solution avoids dragging false dark edges
    # across a repaired root; the 3D mask feathers it into the original maps.
    selected = mask > .001
    samples = (mask > .001) & (mask < .30)
    if diffuse:
        brightness = pixels[..., :3].mean(axis=2)
        chroma = np.ptp(pixels[..., :3], axis=2)
        samples &= (brightness > .38) & (brightness < .95) & (chroma < .15)
    if samples.sum() < 30:
        samples = selected
    value = np.median(pixels[samples], axis=0)
    weight = np.where(selected, mask, 0)[..., None]
    result = pixels * (1 - weight) + value * weight
    result[~selected] = pixels[~selected]
    assert np.array_equal(result[~selected], pixels[~selected])
    return result, value.tolist()


def main(args=None):
    args = sys.argv[sys.argv.index('--') + 1:] if args is None else args
    source, destination = [Path(p).resolve() for p in args[:2]]
    pack_existing = '--pack-existing' in args
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
    mesh = obj.data
    points = np.array([list(obj.matrix_world @ v.co) for v in mesh.vertices])
    low, high = points.min(axis=0), points.max(axis=0)
    origin = np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]])
    positions = (points - origin) / (high[2] - low[2])
    records = (json.loads(destination.with_suffix('.json').read_text())['images']
               if pack_existing else [])
    masks = {}
    for material in mesh.materials:
        for node in material.node_tree.nodes:
            image = getattr(node, 'image', None)
            if image is None:
                continue
            texture = destination.parent / (image.name.replace('/', '_') + '.png')
            if pack_existing:
                repaired_image = bpy.data.images.load(str(texture), check_existing=False)
                repaired_image.colorspace_settings.name = image.colorspace_settings.name
                repaired_image.pack()
                node.image = repaired_image
                continue
            width, height = image.size
            channels = image.channels
            values = np.empty(width * height * channels, np.float32)
            image.pixels.foreach_get(values)
            pixels = values.reshape(height, width, channels)
            key = (width, height)
            if key not in masks:
                masks[key] = raster_mask(mesh, positions, width, height)
            mask = masks[key]
            repaired, boundary_color = boundary_fill(pixels, mask, 'diffuse' in image.name.lower())
            is_normal = 'normal' in image.name.lower()
            if is_normal:
                selected = mask > .001
                # Geometry is now smooth; remove the baked false groove's normal
                # instead of retaining an obsolete tangent-space depression.
                weight = np.where(selected, mask, 0)[..., None]
                neutral = np.zeros_like(repaired[..., :3]) + np.array([.5, .5, 1])
                repaired[..., :3] = repaired[..., :3] * (1 - weight) + neutral * weight
                vector = repaired[selected, :3] * 2 - 1
                vector /= np.maximum(np.linalg.norm(vector, axis=1, keepdims=True), 1e-8)
                repaired[selected, :3] = vector * .5 + .5
            repaired[..., 3] = pixels[..., 3]
            changed = np.max(np.abs(repaired - pixels), axis=2) > 1e-7
            assert not np.any(changed & (mask <= .001)), 'Repair escaped root mask'
            image.pixels.foreach_set(repaired.ravel())
            image.update()
            # Save into a separate trusted output directory, then pack the PNG.
            texture = destination.parent / (image.name.replace('/', '_') + '.png')
            image.filepath_raw = str(texture)
            image.file_format = 'PNG'
            image.save()
            # Imported GLB images still carry the old packed payload. Replace the
            # image datablock with the saved repair so export cannot reuse it.
            repaired_image = bpy.data.images.load(str(texture), check_existing=False)
            repaired_image.colorspace_settings.name = image.colorspace_settings.name
            repaired_image.pack()
            node.image = repaired_image
            records.append(dict(image=image.name, size=[width, height],
                                maskedTexels=int((mask > .001).sum()),
                                changedTexels=int(changed.sum()),
                                sha256=hashlib.sha256(texture.read_bytes()).hexdigest(),
                                boundarySampleMedian=boundary_color, normalNeutralized=is_normal))
    bpy.ops.export_scene.gltf(filepath=str(destination), export_format='GLB',
                             export_animations=False, export_normals=True,
                             export_texcoords=True, export_materials='EXPORT',
                             export_image_format='AUTO', export_yup=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    report = dict(source=str(source), sourceSha256=source_hash,
                  output=str(destination), outputSha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                  geometryEdited=False, uvEdited=False, textureRepair='3D-root-mask UV raster; robust boundary median constant harmonic fill; feathered edges',
                  images=records)
    destination.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print('QIANGliANG_TEXTURE_REPAIR ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
