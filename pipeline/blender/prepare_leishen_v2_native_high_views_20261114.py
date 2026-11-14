"""Four High-reference images from native Leishen v2. No pose/mesh/material edits.
Run Blender --background --factory-startup --disable-autoexec --python-exit-code 1
--python this_trusted_file -- --source /absolute/raw/source.glb --output-dir /absolute/new/raw/_build/output
Canonical front is the preserved human face direction after whole-object yaw.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
from mathutils import Matrix, Vector
from review_native_source_20261114 import digest, surface_digest, material_digest, world_points, bounds

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = '9d45340027d64531bec2ee4647aa059fab008acb07ddd611b083f2c99ee77a8e'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source=Path(args.source).resolve(strict=True)
    output=Path(args.output_dir).resolve()
    assert source.is_relative_to(ROOT/'raw') and source.suffix.lower()=='.glb'
    assert output.is_relative_to(ROOT/'raw/_build')
    assert digest(source)==EXPECTED
    output.mkdir(parents=True,exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source),disable_bone_shape=True)
    imported=list(bpy.context.scene.objects)
    meshes=[o for o in imported if o.type=='MESH']
    assert meshes and not any(o.type=='ARMATURE' for o in imported)
    assert not any(o.modifiers for o in meshes)
    surface_before=surface_digest(meshes)
    materials_before=material_digest(meshes)
    original_bounds=bounds(world_points(meshes))
    original_world={o.name:o.matrix_world.copy() for o in meshes}
    rotation=Matrix.Rotation(-math.pi/2,4,'Z')
    rotated=[rotation@p for p in world_points(meshes)]
    rotated_bounds=bounds(rotated)
    scale=1/max(rotated_bounds['size'])
    lo,hi=Vector(rotated_bounds['min']),Vector(rotated_bounds['max'])
    offset=Vector((-(lo.x+hi.x)*.5*scale,-(lo.y+hi.y)*.5*scale,-lo.z*scale))
    transform=Matrix.Translation(offset)@Matrix.Scale(scale,4)@rotation
    root=bpy.data.objects.new('native_reference_rigid_root',None)
    bpy.context.scene.collection.objects.link(root)
    root.matrix_world=transform
    for o in imported:
        if o.parent is None:
            o.parent=root
    bpy.context.view_layer.update()
    for o in meshes:
        expected=transform@original_world[o.name]
        assert max(abs(o.matrix_world[r][c]-expected[r][c]) for r in range(4) for c in range(4))<1e-6
    points=world_points(meshes)
    transformed_bounds=bounds(points)
    assert abs(max(transformed_bounds['size'])-1)<1e-5
    # Positive uniform scale with a proper rotation only; no mesh transform_apply.
    linear=transform.to_3x3()
    assert linear.determinant()>0
    unit=linear.normalized()
    assert max(abs((unit.transposed()@unit)[r][c]-(1 if r==c else 0)) for r in range(3) for c in range(3))<1e-5
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=64
    scene.cycles.use_denoising=True
    scene.render.resolution_x=scene.render.resolution_y=1024
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGBA'
    scene.render.film_transparent=False
    scene.view_settings.view_transform='AgX'
    world=bpy.data.worlds.new('native_reference_neutral_world')
    world.use_nodes=True
    world.node_tree.nodes['Background'].inputs[0].default_value=(.55,.57,.60,1)
    world.node_tree.nodes['Background'].inputs[1].default_value=.8
    scene.world=world
    for i,(location,energy,size) in enumerate([((2,-3,4),240,3),((-3,1,2),210,3),((1,3,3),180,3)]):
        light=bpy.data.objects.new('reference_softbox_'+str(i),bpy.data.lights.new('reference_softbox_'+str(i),'AREA'))
        scene.collection.objects.link(light)
        light.location=location
        light.rotation_euler=(Vector((0,0,.4))-light.location).to_track_quat('-Z','Y').to_euler()
        light.data.energy,light.data.size=energy,size
    center=(Vector(transformed_bounds['min'])+Vector(transformed_bounds['max']))*.5
    specs=[('34',(-.65,-.75,.3),'front-left elevated three-quarter; human face visible and full trunk readable'),('side',(1,0,0),'canonical +X, human-face profile; foreshortened native body axis'),('front',(0,-1,0),'canonical -Y, human-face front; native sideways head-to-trunk yaw preserved'),('back',(0,1,0),'canonical +Y, rear cranium and full trunk')]
    images=[]
    for name,direction,meaning in specs:
        camera=bpy.data.objects.new('reference_'+name,bpy.data.cameras.new('reference_'+name))
        scene.collection.objects.link(camera)
        location=center+Vector(direction).normalized()*3
        camera.matrix_world=Matrix.LocRotScale(location,(center-location).to_track_quat('-Z','Y'),Vector((1,1,1)))
        camera.data.type='ORTHO'
        camera.data.ortho_scale=1.15
        camera.data.clip_start,camera.data.clip_end=.01,100
        scene.camera=camera
        bpy.context.view_layer.update()
        path=output/('view_'+name+'.png')
        scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
        # Every native surface vertex must stay within the image, with a margin.
        from bpy_extras.object_utils import world_to_camera_view
        projected=[world_to_camera_view(scene,camera,p) for p in points]
        projected_bounds={'x':[min(p.x for p in projected),max(p.x for p in projected)],'y':[min(p.y for p in projected),max(p.y for p in projected)]}
        assert all(.025<value<.975 for values in projected_bounds.values() for value in values),projected_bounds
        source_direction=rotation.inverted().to_3x3()@Vector(direction)
        images.append({'path':path.name,'sha256':digest(path),'resolution':[1024,1024],'meaning':meaning,'canonicalCameraDirection':list(direction),'sourceCameraDirection':list(source_direction),'cameraLocation':list(location),'target':list(center),'orthoScale':1.15,'projectedNativeVertexBounds':projected_bounds})
    surface_after=surface_digest(meshes)
    materials_after=material_digest(meshes)
    assert surface_before==surface_after
    assert materials_before==materials_after
    assert digest(source)==EXPECTED
    manifest={'status':'FOUR_NATIVE_HIGH_REFERENCE_VIEWS_PENDING_PARENT_IMAGE_REVIEW','source':str(source),'sourceSha256Before':EXPECTED,'sourceSha256After':digest(source),'sourceBounds':original_bounds,'canonicalBounds':transformed_bounds,'transform':{'uniformScale':scale,'yawDegrees':-90,'translation':list(offset),'worldMatrix':[list(r) for r in transform],'operation':'parent-only positive uniform scale + one whole-object rigid yaw + translation','deformation':False,'sourceHumanFaceDirection':'+X, established by prior source image inspection','canonicalHumanFaceDirection':'-Y','sourceBodyTailDirection':'+Y','canonicalBodyTailDirection':'+X','headToBodyYawPreserved':True,'frontBackConvention':'human-face orientation; body long axis remains transverse due to native head yaw'},'surfaceUvNormalsSha256Before':surface_before,'surfaceUvNormalsSha256After':surface_after,'materialSha256Before':materials_before,'materialSha256After':materials_after,'topologyEdits':False,'uvEdits':False,'normalEditsOrRecomputation':False,'materialEdits':False,'poseEdits':False,'glbReexported':False,'nativeStoredDataUnchanged':True,'renderer':{'engine':'CYCLES','samples':64,'nativePbr':True,'viewTransform':'AgX'},'images':images,'suggestedImageOrder':['view_34.png','view_side.png','view_front.png','view_back.png'],'blenderVersion':bpy.app.version_string,'script':str(Path(__file__).resolve()),'scriptSha256':digest(Path(__file__).resolve()),'apiCalls':0}
    (output/'reference-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('LEISHEN_NATIVE_HIGH_REFERENCE_COMPLETE '+str(output),flush=True)

if __name__=='__main__':
    main()
