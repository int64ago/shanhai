"""Offline kingfisher remodel of the verified Jingwei HIGH master; no generation.
Run after normalize.py --length 1.5. Preserves its 49,902-triangle feather mesh.
Blender --background --python prepare_min_bird.py -- input.glb output.glb concept_dir
"""
import os
import sys
import math
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0, os.path.dirname(__file__))
from turnaround import load, setup_render, render_views, smoothstep


def remodel(p):
    x, y, z = p
    # Two genuinely separate short tarsi, broad breast, compact neck, large skull.
    head = smoothstep(.78, .96, z) * (1 - smoothstep(.17, .26, abs(x)))
    x *= 1 + .24 * head
    y = y + (y + .35) * .12 * head
    if z > .65:
        z = .65 + (z - .65) * .85
    z = z * .48 if z < .32 else z - .1664
    # Replace crow's hooked silhouette with a long, straight, pointed red bill.
    bill = smoothstep(.47, .53, -p.y) * smoothstep(.86, .94, p.z) * (1 - smoothstep(1.01, 1.045, p.z))
    y -= max(0, -p.y - .45) * 1.35 * bill
    z += (.98 - p.z) * .45 * bill
    # Short wedge tail rather than the source's long descending crow tail.
    tail = smoothstep(.16, .34, p.y) * (1 - smoothstep(.48, .6, p.z))
    y -= max(0, p.y - .16) * .64 * tail
    z += .17 * tail
    # Bring both preserved feather wings against the flanks, swept to the rear.
    wing = smoothstep(.16, .26, abs(p.x)) * smoothstep(.42, .58, p.z)
    extent = max(0, abs(p.x) - .16)
    x = x * (1 - wing) + math.copysign(.16 + extent * .15, p.x) * wing
    y += extent * .60 * wing
    z -= extent * .67 * wing
    return Vector((x, y, z))


def repaint(obj, original, size=2048):
    """Rasterize anatomical washes onto existing UVs, retaining source feather relief.
    The exact teal/cream palette is an artistic inference, not a textual claim.
    """
    image = next(n.image for n in obj.active_material.node_tree.nodes
                 if n.type == 'TEX_IMAGE' and n.image and 'diffuse' in n.image.name)
    image.scale(size, size)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape(size, size, 4)
    out = np.ones_like(pixels)
    out[:, :, :3] = [.12, .42, .43]
    uv = obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        uvs = np.array([uv[i].uv[:] for i in tri.loops]) * (size - 1)
        lo = np.maximum(0, np.floor(uvs.min(axis=0)).astype(int))
        hi = np.minimum(size - 1, np.ceil(uvs.max(axis=0)).astype(int))
        if np.any(hi < lo):
            continue
        xx, yy = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        a, b, c = uvs
        den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den) < 1e-9:
            continue
        wa = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        wb = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den
        wc = 1-wa-wb
        mask = (wa >= -.025) & (wb >= -.025) & (wc >= -.025)
        if not mask.any():
            continue
        ids = tri.vertices
        p = wa[...,None]*original[ids[0]]+wb[...,None]*original[ids[1]]+wc[...,None]*original[ids[2]]
        x, y, z = p[...,0], p[...,1], p[...,2]
        src = pixels[yy,xx,:3]
        value = src.max(axis=2)
        shade = np.clip(.55 + .75 * np.sqrt(value), .55, 1.12)
        color = np.zeros_like(src) + [.10,.47,.49]
        # Cream throat and warm buff breast distinguish the tiny waterside bird.
        def blend(target, weight):
            nonlocal color
            weight = np.clip(weight, 0, 1)[...,None]
            color = color * (1-weight) + np.array(target) * weight
        breast = np.clip((-y-.17)/.08,0,1) * np.clip((.88-z)/.08,0,1) * np.clip((z-.30)/.07,0,1)
        breast *= np.clip((.20-np.abs(x))/.05,0,1)
        blend([.77,.56,.32], breast)
        throat = np.clip((-y-.33)/.05,0,1) * np.clip((z-.78)/.04,0,1) * np.clip((.98-z)/.04,0,1)
        throat *= np.clip((.16-np.abs(x))/.04,0,1)
        blend([.90,.86,.68], throat)
        bill = (y < -.50) & (z > .89) & (z < 1.02) & (np.abs(x) < .09)
        color[bill] = [.76,.12,.07]
        feet = (z < .31) & (y < .14)
        color[feet] = [.57,.27,.17]
        # Small round eyes, rather than the source crow's gold brow stripe.
        eye = ((y+.445)/.032)**2 + ((z-1.025)/.026)**2 < 1
        eye &= np.abs(x) > .07
        color[eye] = [.025,.037,.035]
        glint = ((y+.457)/.007)**2 + ((z-1.034)/.007)**2 < 1
        color[glint & eye] = [.88,.88,.75]
        out[yy[mask],xx[mask],:3] = (color*shade[...,None])[mask]
    # Pad UV seams without changing the original texture layout.
    image.pixels.foreach_set(out.ravel())
    image.pack()
    mat = obj.active_material
    nodes = mat.node_tree.nodes
    bsdf = next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
    for socket in ['Normal','Metallic','Roughness']:
        for link in list(bsdf.inputs[socket].links):
            mat.node_tree.links.remove(link)
    bsdf.inputs['Roughness'].default_value = .84
    bsdf.inputs['Metallic'].default_value = 0
    print('REPAINT', size, 'teal/cream/buff inferred; red beak source')


def main():
    args = sys.argv[sys.argv.index('--')+1:]
    obj = load(args[0])
    original = np.array([v.co[:] for v in obj.data.vertices])
    repaint(obj, original)
    for v in obj.data.vertices:
        v.co = remodel(v.co.copy())
    obj.data.update()
    for p in obj.data.polygons:
        p.use_smooth = True
    obj.name = 'min_bird_high_remodel'
    bpy.ops.export_scene.gltf(filepath=args[1], export_format='GLB', export_animations=False)
    os.makedirs(args[2], exist_ok=True)
    render_views(obj, setup_render(1024), args[2])
    print('EXPORTED', args[1], 'triangles', len(obj.data.loop_triangles))

if __name__ == '__main__':
    main()
