"""Render actual imported High PBR with a positive uniform object transform only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import bpy
from mathutils import Matrix, Vector

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--out-dir',required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);source=Path(a.source);output=Path(a.out_dir);output.mkdir(parents=True,exist_ok=False)
hash_before=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(source),disable_bone_shape=True)
objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
points=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
low=Vector([min(v[k] for v in points) for k in range(3)]);high=Vector([max(v[k] for v in points) for k in range(3)])
scale=7/max(high-low);offset=Vector((-(low.x+high.x)*scale/2,-(low.y+high.y)*scale/2,-low.z*scale))
transform=Matrix.Translation(offset)@Matrix.Scale(scale,4)
triangles=0;counts=[]
for o in objects:
    o.data.calc_loop_triangles();triangles+=len(o.data.loop_triangles)
    counts.append(dict(name=o.name,vertices=len(o.data.vertices),triangles=len(o.data.loop_triangles),uvLayers=len(o.data.uv_layers),materials=[m.name if m else None for m in o.data.materials]))
    o.matrix_world=transform@o.matrix_world
helper=Path(__file__).with_name('prepare_xiangliu.py');spec=importlib.util.spec_from_file_location('trusted_xiangliu_authoring',helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.render_views(objects,output)
assert hashlib.sha256(source.read_bytes()).hexdigest()==hash_before
(output/'native-review.json').write_text(json.dumps(dict(source=str(source),sha256=hash_before,sourceBounds=dict(min=list(low),max=list(high)),uniformScale=scale,translation=list(offset),actualTriangles=triangles,meshes=counts,geometryEdited=False,uvEdited=False,materialsEdited=False,sourceHashUnchanged=True,viewNames='Camera directions in unchanged Blender import axes; front/back are not anatomical assignments',accepted=False),indent=2)+'\n')
