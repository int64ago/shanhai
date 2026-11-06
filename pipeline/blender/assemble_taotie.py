"""Assemble the three corrected Rodin masters into one skinnable Paoxiao.

Inputs are the normalized Stage-2 torso (.8 m), head (.28 m), and hand (.18 m).
Run rig_quadruped.py on the assembly, then fix_taotie_weights.py before applying
WebP/meshopt compression. Preserve material prefixes for that weight correction.
"""
import argparse
import math
import sys
from pathlib import Path
import bmesh
import bpy
from mathutils import Matrix, Vector

p = argparse.ArgumentParser()
p.add_argument('body')
p.add_argument('head')
p.add_argument('hand')
p.add_argument('output')
p.add_argument('views')
p.add_argument('--view', choices=['34','side','front','back'])
a = p.parse_args(sys.argv[sys.argv.index('--')+1:])
bpy.ops.wm.read_factory_settings(use_empty=True)

def load(path, role):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objects = [o for o in bpy.context.scene.objects if o not in before and o.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects)>1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = role
    for slot in obj.material_slots:
        if slot.material:
            slot.material = slot.material.copy()
            slot.material.name = role+'_'+slot.material.name
    return obj

def bounds(obj):
    vs = [v.co for v in obj.data.vertices]
    return Vector(tuple(min(v[i] for v in vs) for i in range(3))), Vector(tuple(max(v[i] for v in vs) for i in range(3)))

body = load(a.body, 'torso')
lo,hi = bounds(body)
# Four ankle stumps stay distinct; attach the wrist slightly inside each.
low = [v.co.copy() for v in body.data.vertices if v.co.z < lo.z+.035]
mid_y = (min(v.y for v in low)+max(v.y for v in low))/2
feet = {}
for fb in ['front','back']:
    for side in ['l','r']:
        pts = [v for v in low if (v.y<mid_y)==(fb=='front') and (v.x>0)==(side=='l')]
        if not pts:
            raise RuntimeError('Missing ankle '+fb+'_'+side)
        feet[fb+'_'+side] = sum(pts, Vector())/len(pts)
body.data.transform(Matrix.Translation((0,0,.035)))
head = load(a.head, 'human_head')
# Stage two added a white collar below the neck. Remove it, not the face.
bm = bmesh.new()
bm.from_mesh(head.data)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
result = bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces), plane_co=(0,0,.055), plane_no=(0,0,-1), clear_outer=True, clear_inner=False, dist=1e-6)
edges = [e for e in result['geom_cut'] if isinstance(e,bmesh.types.BMEdge) and e.is_boundary]
bmesh.ops.holes_fill(bm, edges=edges, sides=0)
bm.to_mesh(head.data)
bm.free()
head.data.transform(Matrix.Translation((0,0,-.055)))
head.data.transform(Matrix.Scale(1.4,4))
head.data.transform(Matrix.Rotation(math.radians(10),4,'X'))
head.data.transform(Matrix.Translation((0,lo.y+.12,.31)))

hand = load(a.hand, 'hand_master')
hlo,hhi = bounds(hand)
# The corrected reference lies palm-down, with wrist behind (+Y) the digits.
hand.data.transform(Matrix.Translation((-(hlo.x+hhi.x)/2,-hhi.y,-hlo.z)))
objects = [body,head]
for name, position in feet.items():
    obj = hand.copy()
    obj.data = hand.data.copy()
    bpy.context.scene.collection.objects.link(obj)
    obj.name = 'claw_'+name
    for i, material in enumerate(obj.data.materials):
        if material:
            obj.data.materials[i] = material.copy()
            obj.data.materials[i].name = 'claw_'+name+'_'+material.name
    if name.endswith('_r'):
        obj.data.transform(Matrix.Diagonal((-1,1,1,1)))
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
    obj.data.transform(Matrix.Translation((position.x,position.y+.025,0)))
    objects.append(obj)
bpy.data.objects.remove(hand, do_unlink=True)
bpy.ops.object.select_all(action='DESELECT')
for obj in objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
body.name = 'body'
Path(a.output).parent.mkdir(parents=True,exist_ok=True)
bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from turnaround import render_views, setup_render
Path(a.views).mkdir(parents=True,exist_ok=True)
render_views(body, setup_render(1024), a.views, only_view=a.view)
