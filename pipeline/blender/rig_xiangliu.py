"""Explicit 24-segment serpentine spine, nine neck chains, rigid human heads and three clips."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils import Vector


def body_path(t):
    return Vector((.34*math.sin(2*math.pi*t)*math.sin(math.pi*t),1.9-7*t,.75-.45*t+.045*math.sin(math.pi*t)))


def neck_path(head,t):
    ease=t*t*(3-2*t)
    return Vector((head['seatx']+(head['x']-head['seatx'])*ease+.07*math.sin(math.pi*t)*math.sin(head['number']*1.7),head['seaty']+(head['y']-head['seaty'])*ease-.08*math.sin(math.pi*t),.72+(head['z']-.72)*t))


def spine_weights(y,count):
    u=max(0,min(count-1,((1.9-y)/7-.08)/.92*count-.5));i=int(u);f=u-i
    result={'spine_%02d'%i:1-f}
    if i<count-1:result['spine_%02d'%(i+1)]=f
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('destination');p.add_argument('--preview',required=True)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    source=Path(args.source);output=Path(args.destination)
    layout=json.loads((source.parent/'layout.json').read_text());heads=layout['heads']
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(source),disable_bone_shape=True)
    obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
    bpy.context.view_layer.objects.active=obj;obj.select_set(True);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    armature=bpy.data.armatures.new('xiangliu_serpentine_rig');rig=bpy.data.objects.new('xiangliu_serpentine_rig',armature)
    bpy.context.scene.collection.objects.link(rig);bpy.context.view_layer.objects.active=rig;obj.select_set(False);rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    root=armature.edit_bones.new('root');root.head=(0,.85,.55);root.tail=(0,.85,.85)
    count=24;neck_count=7
    for i in range(count):
        bone=armature.edit_bones.new('spine_%02d'%i)
        bone.head=body_path(.08+.92*i/count);bone.tail=body_path(.08+.92*(i+1)/count)
        bone.parent=root if i==0 else armature.edit_bones['spine_%02d'%(i-1)]
    for h in heads:
        number=h['number']
        for i in range(neck_count):
            bone=armature.edit_bones.new('neck_%02d_%02d'%(number,i));bone.head=neck_path(h,i/neck_count);bone.tail=neck_path(h,(i+1)/neck_count)
            bone.parent=armature.edit_bones['spine_00'] if i==0 else armature.edit_bones['neck_%02d_%02d'%(number,i-1)]
        bone=armature.edit_bones.new('head_%02d'%number);bone.head=h['top'];bone.tail=Vector(h['top'])+Vector((0,0,.35));bone.parent=armature.edit_bones['neck_%02d_%02d'%(number,neck_count-1)]
    bpy.ops.object.mode_set(mode='OBJECT')
    groups={b.name:obj.vertex_groups.new(name=b.name) for b in armature.bones}
    native=set();posterior=set()
    for face in obj.data.polygons:
        mat=obj.data.materials[face.material_index]
        if mat and mat.name.startswith('Native_High'):
            native.update(face.vertices)
        elif mat and mat.name.startswith('Actual_High_body'):
            posterior.update(face.vertices)
    rigid_count={h['number']:0 for h in heads};max_weights=0;min_sum=1
    points=np.array([v.co[:] for v in obj.data.vertices])
    for vi,point in enumerate(points):
        v=Vector(point);weights={}
        if vi in native:
            h=min(heads,key=lambda h:(v-Vector(h['top'])-Vector((0,0,.15))).length_squared)
            weights['head_%02d'%h['number']]=1.;rigid_count[h['number']]+=1
        elif vi not in posterior and v.y>.14 and v.z>.88:
            options=[]
            for h in heads:
                t=max(0,min(1,(v.z-.72)/(h['z']-.72)))
                options.append(((v-neck_path(h,t)).length_squared,h,t))
            _,h,t=min(options,key=lambda x:x[0])
            # Smooth roots remain with the shared anterior spine; there is no
            # weighted face mask and no mixing between different rigid heads.
            root_mix=max(0,min(1,(v.z-.88)/.30));root_mix=root_mix*root_mix*(3-2*root_mix)
            anterior=max(0,min(1,(v.y-.14)/.30));root_mix*=anterior*anterior*(3-2*anterior)
            u=t*neck_count-.5;i=max(0,min(neck_count-1,int(math.floor(u))));f=max(0,min(1,u-i))
            a='neck_%02d_%02d'%(h['number'],i)
            b='neck_%02d_%02d'%(h['number'],i+1) if i<neck_count-1 else 'head_%02d'%h['number']
            if v.z>=h['z']-.065:a=b='head_%02d'%h['number'];f=0
            weights[a]=root_mix*(1-f);weights[b]=weights.get(b,0)+root_mix*f
            for bone,w in spine_weights(v.y,count).items():weights[bone]=weights.get(bone,0)+w*(1-root_mix)
        else:
            weights=spine_weights(v.y,count)
        weights={k:w for k,w in weights.items() if w>1e-7};total=sum(weights.values());min_sum=min(min_sum,total);max_weights=max(max_weights,len(weights))
        assert total>.99999
        for name,w in weights.items():groups[name].add([vi],w/total,'REPLACE')
    modifier=obj.modifiers.new('Nine_necks_and_serpentine_spine','ARMATURE');modifier.object=rig;obj.parent=rig
    scene=bpy.context.scene;scene.render.fps=30
    clips=[]
    for name,seconds,amplitude in [('idle',8.,.012),('walk',4.,.045),('special',3.6,.030)]:
        frames=round(seconds*30);scene.frame_start=1;scene.frame_end=frames+1
        if rig.animation_data:rig.animation_data.action=None
        action=bpy.data.actions.new(name);rig.animation_data_create();rig.animation_data.action=action
        for bone in rig.pose.bones:bone.rotation_mode='XYZ';bone.rotation_euler=(0,0,0);bone.location=(0,0,0)
        for frame in range(1,frames+2,3):
            phase=(frame-1)/frames*math.tau
            for i in range(count):
                bone=rig.pose.bones['spine_%02d'%i]
                taper=.35+.65*i/(count-1)
                bone.rotation_euler=(amplitude*.18*math.sin(phase-i*.31),0,amplitude*taper*math.sin(phase-i*.32))
                bone.keyframe_insert('rotation_euler',frame=frame)
            for h in heads:
                number=h['number'];offset=number*.67
                for i in range(neck_count):
                    bone=rig.pose.bones['neck_%02d_%02d'%(number,i)]
                    strength=(.006 if name=='idle' else .012 if name=='walk' else .019)*(i+1)/neck_count
                    pulse=math.sin(phase*.5)**2 if name=='special' else 1
                    bone.rotation_euler=(strength*math.sin(phase-offset-i*.5)*pulse,0,strength*.7*math.cos(phase-offset-i*.45)*pulse)
                    bone.keyframe_insert('rotation_euler',frame=frame)
                bone=rig.pose.bones['head_%02d'%number]
                bone.rotation_euler=(.012*math.sin(phase-offset),(.07 if name=='special' else .025)*math.sin(phase-offset),0)
                bone.keyframe_insert('rotation_euler',frame=frame)
            rootbone=rig.pose.bones['root'];rootbone.location=(0,.15+.018*math.sin(phase),0);rootbone.keyframe_insert('location',frame=frame)
        # Keep each clip separate for the unified exporter.
        track=rig.animation_data.nla_tracks.new();track.name=name
        track.strips.new(name,1,action);rig.animation_data.action=None
        clips.append(dict(name=name,seconds=seconds,frames=frames+1))
    # Sample actual skinned head coordinates, not only node counts.
    qa=[]
    for track in rig.animation_data.nla_tracks:
        for other in rig.animation_data.nla_tracks:other.mute=other!=track
        for fraction in [0,.25,.5,.75,1]:
            scene.frame_set(1+round((track.strips[0].frame_end-1)*fraction));bpy.context.view_layer.update()
            centers={h['number']:rig.pose.bones['head_%02d'%h['number']].matrix.translation.copy() for h in heads}
            separation=min((a-b).length for i,a in centers.items() for j,b in centers.items() if i<j)
            qa.append(dict(action=track.name,fraction=fraction,minimumHeadRootDistance=separation))
    for track in rig.animation_data.nla_tracks:track.mute=False
    scene.frame_set(1)
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);rig.select_set(True);bpy.context.view_layer.objects.active=rig
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',use_selection=True,export_yup=True,export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_all_influences=False,export_normals=True,export_attributes=True)
    (output.parent/'rig-audit.json').write_text(json.dumps(dict(source=str(source),vertices=len(points),nativeRigidVertices=rigid_count,maxInfluences=max_weights,minWeightSum=min_sum,spineBones=count,neckChains=9,neckBonesPerChain=neck_count,rigidHeadBones=9,clips=clips,sampledHeadSeparation=qa,scope='Weight normalization and rigid human-face groups plus pose-space root separation; browser closeups remain necessary'),indent=2)+'\n')
    # The unified contract passes an actual preview filename.
    preview=Path(args.preview);preview.parent.mkdir(parents=True,exist_ok=True)
    for track in rig.animation_data.nla_tracks:track.mute=track.name!='idle'
    scene.frame_set(1);scene.render.engine='CYCLES';scene.cycles.samples=8;scene.cycles.use_denoising=True
    scene.render.resolution_x=900;scene.render.resolution_y=650;scene.render.resolution_percentage=100
    world=bpy.data.worlds.new('Rig_preview_world');world.use_nodes=True
    world.node_tree.nodes['Background'].inputs[0].default_value=(.55,.58,.57,1);world.node_tree.nodes['Background'].inputs[1].default_value=.8;scene.world=world
    target=Vector((0,-1.6,1.3))
    for i,location in enumerate([(4,5,8),(-5,0,5)]):
        light=bpy.data.objects.new('Preview_light_'+str(i),bpy.data.lights.new('Preview_light_'+str(i),'AREA'))
        scene.collection.objects.link(light);light.location=location;light.data.energy=1400;light.data.size=6
        light.rotation_euler=(target-light.location).to_track_quat('-Z','Y').to_euler()
    camera=bpy.data.objects.new('Preview_camera',bpy.data.cameras.new('Preview_camera'));scene.collection.objects.link(camera)
    camera.location=target+Vector((9,10,6));camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.type='ORTHO';camera.data.ortho_scale=8.5;scene.camera=camera;scene.render.filepath=str(preview);bpy.ops.render.render(write_still=True)
    print('EXPORTED '+str(output),flush=True)


if __name__=='__main__':main()
