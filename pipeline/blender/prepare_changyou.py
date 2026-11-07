"""Primate-specific preparation; never apply quadruped rump/tail correction.
Render each view in a separate Blender process (EEVEE camera cache).
"""
import argparse
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import turnaround
from mathutils import Matrix, Vector
import math


def clear_native_pinna(body):
    """Erase residual native-ear UV markings and tuck its tiny rim into scalp.
    Target temporal skin only; eyes, muzzle and hands are outside this volume.
    """
    import numpy as np
    mesh = body.data
    uv = mesh.uv_layers.active.data
    material = mesh.materials[0]
    principled = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    image = principled.inputs['Base Color'].links[0].from_node.image
    width, height = image.size
    pixels = np.empty(width*height*4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape((height,width,4))
    samples = []
    for poly in mesh.polygons:
        for loop in poly.loop_indices:
            p = mesh.vertices[mesh.loops[loop].vertex_index].co
            if p.z > 1.22 and abs(p.x) < .055 and p.y > -.17:
                u,v = uv[loop].uv
                samples.append(pixels[int(v*(height-1)),int(u*(width-1)),:3])
    color = np.median(np.array(samples),axis=0)
    count = 0
    for poly in mesh.polygons:
        center = sum((mesh.vertices[i].co for i in poly.vertices),Vector())/len(poly.vertices)
        if not (1.095 < center.z < 1.215 and abs(center.x) > .067 and -.205 < center.y < -.045):
            continue
        loops = list(poly.loop_indices)
        for j in range(1,len(loops)-1):
            a,b,c = [np.array(uv[i].uv)*np.array([width-1,height-1]) for i in [loops[0],loops[j],loops[j+1]]]
            low = np.maximum(0,np.floor(np.minimum(np.minimum(a,b),c)).astype(int)-1)
            high = np.minimum([width-1,height-1],np.ceil(np.maximum(np.maximum(a,b),c)).astype(int)+1)
            xx,yy = np.meshgrid(np.arange(low[0],high[0]+1),np.arange(low[1],high[1]+1))
            denom = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denom)<1e-7: continue
            one=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denom
            two=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denom
            mask=(one>=-.025)&(two>=-.025)&(one+two<=1.025)
            region=pixels[low[1]:high[1]+1,low[0]:high[0]+1,:3]
            region[mask]=color
        count += 1
    image.pixels.foreach_set(pixels.ravel());image.update();image.pack()
    for v in mesh.vertices:
        p=v.co
        if 1.095 < p.z < 1.215 and abs(p.x) > .067 and -.205 < p.y < -.045:
            limit=.079*math.sqrt(max(.1,1-((p.z-1.16)/.17)**2))
            p.x=math.copysign(min(abs(p.x),limit),p.x)
    mesh.update()
    print('NATIVE_PINNA_ERASED',count,'faces; scalp RGB',color.tolist())


def assemble(body, ear_path):
    body.name = 'changyou_primate'
    clear_native_pinna(body)
    # Flatten only the two supporting soles; hands and curled tail remain intact.
    for v in body.data.vertices:
        if abs(v.co.x) < .25 and v.co.y < .09 and v.co.z < .008:
            v.co.z = .001
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=ear_path)
    parts = [o for o in bpy.context.scene.objects if o not in before and o.type == 'MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in parts: o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1: bpy.ops.object.join()
    master = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    pts = [v.co for v in master.data.vertices]
    lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
    hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    center = (lo + hi) * .5
    for v in master.data.vertices: v.co -= center
    for side, label in [(1, 'l'), (-1, 'r')]:
        for index, (height, z, x) in enumerate([(.13, 1.20, .112), (.11, 1.075, .106)]):
            ear = master.copy(); ear.data = master.data.copy()
            bpy.context.scene.collection.objects.link(ear)
            ear.name = f'changyou_ear_{label}_{index}'
            s = height / (hi.z - lo.z)
            rotation = Matrix.Rotation(side * .95, 3, 'Z')
            for v in ear.data.vertices:
                p = v.co * s
                p.y *= .65
                p = rotation @ p
                # Sweep and lengthen the medial dermis into the temporal skin.
                # The visible pinna faces outward rather than four frontal discs.
                medial = max(0, min(1, -side*p.x/.025))
                p.x -= side*.022*medial*medial*(3-2*medial)
                p += Vector((side*x, -.137, z))
                v.co = p
            ear.data.update()
    bpy.data.objects.remove(master, do_unlink=True)
    for o in list(bpy.context.scene.objects):
        if o.type != 'MESH': bpy.data.objects.remove(o, do_unlink=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
    p.add_argument('--correct-medium', action='store_true')
    p.add_argument('--assemble', metavar='EAR_HIGH')
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.input)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes: o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1: bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.context.scene.objects):
        if o is not obj: bpy.data.objects.remove(o, do_unlink=True)
    if args.assemble:
        assemble(obj, args.assemble)
    if args.correct_medium:
        # v2 arrives facing +Y despite normalized node transforms. Bake the
        # coordinates themselves, then tuck native pinnae into temporal scalp.
        for v in obj.data.vertices:
            v.co.x *= -1
            v.co.y *= -1
            if v.co.z > 1.35 and abs(v.co.x) > .105:
                sign = 1 if v.co.x > 0 else -1
                v.co.x = sign * (.105 + (abs(v.co.x) - .105) * .035)
        obj.data.update()
    if args.view:
        Path(args.output).mkdir(parents=True, exist_ok=True)
        from mathutils import Vector
        cam = turnaround.setup_render(768)
        pts = [v.co for v in obj.data.vertices]
        lo = Vector(tuple(min(p[i] for p in pts) for i in range(3)))
        hi = Vector(tuple(max(p[i] for p in pts) for i in range(3)))
        center = (lo + hi) * .5
        extent = max(hi - lo)
        d = extent * 3
        offsets = {'34': (.62*d, -.72*d, .3*d), 'side': (d, 0, 0),
                   'front': (0, -d, 0), 'back': (0, d, 0)}
        cam.location = center + Vector(offsets[args.view])
        cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
        cam.data.ortho_scale = extent * 1.15
        bpy.context.scene.frame_set(1)
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath = str(Path(args.output).resolve() / f'view_{args.view}.png')
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB')


if __name__ == '__main__':
    main()
