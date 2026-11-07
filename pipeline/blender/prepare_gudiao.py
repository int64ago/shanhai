"""Offline eagle proportions and one inferred horn from the verified avian HIGH.
Blender --background --python prepare_gudiao.py -- normalized_high.glb out_dir concept_dir
"""
import math
import os
import sys
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0, os.path.dirname(__file__))
from turnaround import load, setup_render, render_views, smoothstep


def remodel(p):
    x, y, z = p
    # Broader barrel breast, a heavier raptor skull and short powerful tarsi.
    breast = smoothstep(.28, .48, z) * (1 - smoothstep(.76, .94, z))
    head = smoothstep(.81, .95, z) * (1 - smoothstep(.16, .25, abs(x)))
    x *= 1 + .26 * breast + .22 * head
    y -= .035 * breast * (1 - smoothstep(-.10, .08, y))
    z = z * .84 if z < .30 else z - .048
    # Broad cere and hooked distal bill, not a kingfisher's long straight spear.
    bill = smoothstep(.47, .55, -p.y) * smoothstep(.86, .93, p.z) * (1 - smoothstep(1.02, 1.065, p.z))
    distal = smoothstep(.54, .68, -p.y)
    x *= 1 + .18 * bill
    y += max(0, -p.y - .48) * .12 * bill
    z -= .075 * distal * bill
    # Lower the front brow slightly above the eye; keep round eye geometry intact.
    brow = smoothstep(.99, 1.055, p.z) * (1 - smoothstep(1.075, 1.12, p.z)) * smoothstep(.32, .43, -p.y)
    z -= .018 * brow
    # Full folded primaries outside the broad chest; less compressed than bluebirds.
    wing = smoothstep(.17, .29, abs(p.x)) * smoothstep(.42, .58, p.z)
    extent = max(0, abs(p.x) - .18)
    x = x * (1 - wing) + math.copysign(.22 + extent * .28, p.x) * wing
    y += extent * .65 * wing
    z -= extent * .47 * wing
    tail = smoothstep(.20, .42, p.y) * (1 - smoothstep(.48, .60, p.z))
    y -= max(0, p.y - .20) * .20 * tail
    z += .05 * tail
    # Widen the existing paired feet and sharpen their distal toe silhouette.
    foot = (1 - smoothstep(.07, .14, p.z)) * (1 - smoothstep(.13, .20, p.y))
    center = math.copysign(.17, p.x)
    x += (p.x - center) * .22 * foot
    return Vector((x, y, z))


def repaint(obj, original, size=2048):
    image = next(n.image for n in obj.active_material.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image and 'diffuse' in n.image.name)
    image.scale(size, size)
    pixels = np.array(image.pixels[:], dtype=np.float32).reshape(size, size, 4)
    out = np.ones_like(pixels); out[:, :, :3] = [.25, .14, .07]
    uv = obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        uvs = np.array([uv[i].uv[:] for i in tri.loops]) * (size-1)
        lo = np.maximum(0, np.floor(uvs.min(axis=0)).astype(int)); hi = np.minimum(size-1, np.ceil(uvs.max(axis=0)).astype(int))
        if np.any(hi < lo): continue
        xx, yy = np.meshgrid(np.arange(lo[0], hi[0]+1), np.arange(lo[1], hi[1]+1))
        a, b, c = uvs; den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den) < 1e-9: continue
        wa = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        wb = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den; wc = 1-wa-wb
        mask = (wa >= -.025) & (wb >= -.025) & (wc >= -.025)
        if not mask.any(): continue
        ids = tri.vertices; p = wa[..., None]*original[ids[0]]+wb[..., None]*original[ids[1]]+wc[..., None]*original[ids[2]]
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        value = pixels[yy, xx, :3].max(axis=2); shade = np.clip(.50+.85*np.sqrt(value), .50, 1.15)
        color = np.zeros_like(p)+[.30, .17, .075]
        def blend(target, weight):
            nonlocal color
            w = np.clip(weight, 0, 1)[..., None]; color = color*(1-w)+np.array(target)*w
        chest = np.clip((-y-.13)/.14, 0, 1)*np.clip((.86-z)/.12, 0, 1)*np.clip((z-.30)/.10, 0, 1)
        blend([.62, .43, .22], chest)
        nape = np.clip((z-.82)/.13, 0, 1)*np.clip((.20-np.abs(x))/.06, 0, 1)
        blend([.72, .57, .32], nape)
        wing = np.clip((np.abs(x)-.20)/.15, 0, 1)*np.clip((z-.45)/.10, 0, 1)
        blend([.22, .13, .075], wing)
        bill = (y < -.50) & (z > .87) & (z < 1.035) & (np.abs(x) < .10)
        color[bill] = [.14, .13, .10]
        cere = bill & (y > -.555); color[cere] = [.72, .52, .22]
        feet = np.clip((.26-z)/.08, 0, 1)*np.clip((.17-y)/.04, 0, 1)
        blend([.62, .40, .16], feet)
        claws = np.clip((.065-z)/.025, 0, 1)*np.maximum(np.clip((-.11-y)/.05, 0, 1), np.clip((y-.045)/.04, 0, 1))
        blend([.09, .075, .055], claws)
        eye = (((y+.445)/.032)**2+((z-1.025)/.026)**2 < 1) & (np.abs(x) > .07)
        color[eye] = [.035, .028, .018]
        glint = (((y+.457)/.006)**2+((z-1.034)/.006)**2 < 1) & eye; color[glint] = [.88, .83, .60]
        out[yy[mask], xx[mask], :3] = (color*shade[..., None])[mask]
    image.pixels.foreach_set(out.ravel()); image.pack()
    bsdf = next(n for n in obj.active_material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    for socket in ['Normal', 'Metallic', 'Roughness']:
        for link in list(bsdf.inputs[socket].links): obj.active_material.node_tree.links.remove(link)
    bsdf.inputs['Roughness'].default_value = .85; bsdf.inputs['Metallic'].default_value = 0


def horn(obj):
    # The source says 有角 without a count. This single swept horn is inferred.
    # A broad scalloped collar begins inside the crown, never above a floating gap.
    crown = max(v.co.z for v in obj.data.vertices if abs(v.co.x) < .065 and -.39 < v.co.y < -.26)
    base = Vector((0, -.325, crown-.035))
    verts=[]; faces=[]; rings=24; sides=24
    for i in range(rings+1):
        t=i/rings
        center=base+Vector((0, .16*t*t, .32*t-.06*t*t))
        radius=max(.0012, .064*(1-t)**.85)*(1+.035*math.sin(t*math.pi*18))
        for j in range(sides):
            a=j*math.tau/sides; r=radius*(1+.035*math.cos(a*8))
            verts.append(tuple(center+Vector((math.cos(a)*r, math.sin(a)*r, -.012*math.cos(a*4)*(1-t)))))
    for i in range(rings):
        for j in range(sides):
            a=i*sides+j; b=i*sides+(j+1)%sides
            faces.append((a,b,b+sides,a+sides))
    faces.append(tuple(reversed(range(sides)))); faces.append(tuple(rings*sides+j for j in range(sides)))
    mesh=bpy.data.meshes.new('gudiao_single_horn');mesh.from_pydata(verts,[],faces);mesh.update()
    part=bpy.data.objects.new('gudiao_horn',mesh);bpy.context.scene.collection.objects.link(part)
    mat=bpy.data.materials.new('inferred_ochre_horn');mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(.40,.26,.12,1);bsdf.inputs['Roughness'].default_value=.8
    # Ink materials consume albedo maps, so keep the horn's inferred ochre wash
    # in a tiny embedded texture rather than relying on the solid material factor.
    uv=mesh.uv_layers.new(name=obj.data.uv_layers.active.name)
    for loop in mesh.loops:
        uv.data[loop.index].uv=((loop.vertex_index%sides)/sides,(loop.vertex_index//sides)/rings)
    image=bpy.data.images.new('gudiao_horn_ochre',width=64,height=64)
    pixels=[]
    for row in range(64):
        t=row/63;shade=(1-.32*t)*(.96+.04*math.cos(t*math.pi*18))
        for col in range(64):pixels.extend((.40*shade,.26*shade,.12*shade,1))
    image.pixels.foreach_set(pixels);image.pack()
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    part.data.materials.append(mat)
    for f in mesh.polygons: f.use_smooth=True
    return part,base


def prepare(path):
    obj=load(path);original=np.array([v.co[:] for v in obj.data.vertices])
    repaint(obj, original)
    for v in obj.data.vertices: v.co=remodel(v.co.copy())
    obj.data.update();obj.name='gudiao_high_body'
    return obj,original


if __name__ == '__main__':
    args=sys.argv[sys.argv.index('--')+1:];os.makedirs(args[1],exist_ok=True);os.makedirs(args[2],exist_ok=True)
    obj,_=prepare(args[0]);part,base=horn(obj)
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);part.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.join()
    bpy.ops.export_scene.gltf(filepath=f'{args[1]}/body_norm.glb',export_format='GLB',export_animations=False)
    render_views(obj,setup_render(1024),args[2]);print('HORN BASE',list(base))
