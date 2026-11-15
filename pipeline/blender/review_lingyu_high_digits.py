"""Additional native High finger/toe cameras; no geometry/material edits or rigging.
Blender --background --factory-startup --disable-autoexec --python-exit-code 1
 --python <this> -- SOURCE.glb NEW_OUTPUT_DIR
"""
import bpy,sys,json
from pathlib import Path
from mathutils import Matrix,Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import review_native_source_20261114 as review
ROOT=Path(__file__).resolve().parents[2]
source,out=[Path(x).resolve() for x in sys.argv[sys.argv.index('--')+1:]]
assert source.is_relative_to(ROOT/'raw') and out.is_relative_to(ROOT/'raw/_build')
assert source.name=='base_high_pbr.glb'
out.mkdir(parents=True,exist_ok=False)
source_hash=review.digest(source)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source),disable_bone_shape=True)
objects=list(bpy.context.scene.objects);meshes=[o for o in objects if o.type=='MESH']
assert meshes and not any(o.type=='ARMATURE' for o in objects)
surface_before=review.surface_digest(meshes);material_before=review.material_digest(meshes)
b=review.bounds(review.world_points(meshes));lo,hi=Vector(b['min']),Vector(b['max']);scale=1/max(hi-lo)
offset=Vector((-(lo.x+hi.x)*.5*scale,-(lo.y+hi.y)*.5*scale,-lo.z*scale))
normalization=bpy.data.objects.new('native_uniform_review_only',None);bpy.context.scene.collection.objects.link(normalization);normalization.matrix_world=Matrix.Translation(offset)@Matrix.Scale(scale,4)
for o in objects:
 if o.parent is None:o.parent=normalization
bpy.context.view_layer.update()
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.samples=48;s.cycles.use_denoising=True
s.render.resolution_x=s.render.resolution_y=800;s.render.resolution_percentage=100;s.view_settings.view_transform='AgX'
w=bpy.data.worlds.new('Native_digit_review');w.use_nodes=True;w.node_tree.nodes['Background'].inputs[0].default_value=(.55,.57,.60,1);w.node_tree.nodes['Background'].inputs[1].default_value=.8;s.world=w
for loc,energy,size in [((2,-3,4),240,3),((-3,1,2),210,3),((1,3,3),180,3)]:
 d=bpy.data.lights.new('softbox','AREA');d.energy=energy;d.size=size;o=bpy.data.objects.new('softbox',d);s.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.4))-o.location).to_track_quat('-Z','Y').to_euler()
images=[]
for name,target,direction,extent in [('toes_plus_x',(.078,.012,.026),(0,-1,.35),.14),('toes_minus_x',(-.078,.012,.026),(0,-1,.35),.14),('palm_plus_x',(.19,-.25,.12),(0,-1,-.05),.22),('palm_minus_x',(-.19,-.25,.12),(0,-1,-.05),.22)]:
 t=Vector(target);loc=t+Vector(direction).normalized()*3;d=bpy.data.cameras.new(name);d.type='ORTHO';d.ortho_scale=extent;o=bpy.data.objects.new(name,d);s.collection.objects.link(o);o.matrix_world=Matrix.LocRotScale(loc,(t-loc).to_track_quat('-Z','Y'),Vector((1,1,1)));s.camera=o;bpy.context.view_layer.update();s.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True);images.append({'path':name+'.png','sha256':review.digest(out/(name+'.png')),'target':target,'direction':direction})
assert source_hash==review.digest(source)
assert surface_before==review.surface_digest(meshes)
assert material_before==review.material_digest(meshes)
json.dump({'source':str(source),'sourceSha256':source_hash,'sourceUnchanged':True,'nativeSurfaceUvNormalsSha256':surface_before,'nativeMaterialsSha256':material_before,'onlyUniformScaleAndTranslation':True,'images':images,'status':'PENDING_PARENT_NATIVE_DIGIT_REVIEW'},open(out/'digit-manifest.json','w'),indent=2)
