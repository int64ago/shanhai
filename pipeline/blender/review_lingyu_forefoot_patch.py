"""Render actual re-imported GLBs; pass SOURCE OUTPUT_DIR [--donor]. No mesh edits."""
import bpy,sys,json,hashlib
from pathlib import Path
from mathutils import Vector
args=sys.argv[sys.argv.index('--')+1:];source=Path(args[0]).resolve();out=Path(args[1]).resolve();donor='--donor' in args
out.mkdir(parents=True,exist_ok=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.samples=32;s.cycles.use_denoising=True
s.render.resolution_x=s.render.resolution_y=800;s.render.resolution_percentage=100;s.view_settings.view_transform='AgX'
w=bpy.data.worlds.new('Neutral');w.use_nodes=True;w.node_tree.nodes['Background'].inputs[0].default_value=(.55,.57,.60,1);w.node_tree.nodes['Background'].inputs[1].default_value=.8;s.world=w
for loc,power,size in [((2,-3,4),240,3),((-3,-1,2),210,3),((1,3,3),180,3)]:
 d=bpy.data.lights.new('softbox','AREA');d.energy=power;d.size=size;o=bpy.data.objects.new('softbox',d);s.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,-.4))-o.location).to_track_quat('-Z','Y').to_euler()
views=[]
for side in [-1,1]:
 t=Vector((.34 if side>0 else -.275,-.11,-.913)) if donor else Vector((side*.145,-.005,-.486))
 extent=.31 if donor else .205
 for name,direction in [('top',(0,-1,.4)),('front',(0,-1,.23)),('side',(side,0,.12))]:
  views.append((f'foot_{side:+d}_{name}',t,direction,extent))
 if not donor:views.append((f'foot_{side:+d}_top_cutaway',t,(0,0,1),extent))
if not donor:
 views += [('whole_34',Vector((0,0,0)),(.65,-.75,.3),2.2)]
for name,t,direction,extent in views:
 d=bpy.data.cameras.new(name);d.type='ORTHO';d.ortho_scale=extent
 # Fish body lies directly above the feet: disclose a near-plane cutaway for
 # true vertical top inspection. Other cameras retain the full unhidden model.
 if name.endswith('top_cutaway'):d.clip_start=3.89
 o=bpy.data.objects.new(name,d);s.collection.objects.link(o);o.location=t+Vector(direction).normalized()*4;o.rotation_euler=(t-o.location).to_track_quat('-Z','Y').to_euler();s.camera=o;s.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
json.dump({'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'actualReimportedGlb':True,'meshEdits':False,'hiddenObjects':False,'topViewDisclosure':'top is an unobstructed elevated front camera. top_cutaway is true vertical with camera near clip at 3.89 of 4 units, removing the occluding body from that camera only. Other views have ordinary clipping.','images':[v[0]+'.png' for v in views]},open(out/'render-manifest.json','w'),indent=2)
