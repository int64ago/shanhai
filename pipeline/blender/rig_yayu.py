"""Yayu independent skeleton, inverse curved stance and whole-sole orientation.
Offline ox/head/horse-hoof assembly; no generation transactions.
"""
import math, sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_quadruped as base
from rig_yingzhao import contact
from rig_ershu import rigid, smooth
from prepare_yayu import FEET
FPS=30
RADIUS=1.0
SPEED=.12
WALK_SECONDS=2.0
DUTY=.70


def animate(arm,name,seconds):
    action=base.new_action(arm,name); n=round(seconds*FPS)
    for frame in range(n+1):
        t=frame/FPS; phase=frame/n
        display=smooth(.15,1.0,t)*(1-smooth(2.7,3.8,t)) if name=='special' else 0
        delta=Vector((0,0,-.020 if name=='walk' else -.006*display))
        # Neck is allowed only a restrained movement so its short junction stays
        # embedded. Head gestures are baked; neither mouse tracking nor VFX.
        pose={'head':base.world_rot(arm.pose.bones['head'],base.X,.065*display+.012*math.sin(phase*math.tau)),
              'yayu_tail_bone':base.world_rot(arm.pose.bones['yayu_tail_bone'],base.Y,.065*math.sin(phase*math.tau))}
        base.key_loc(arm,frame,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,frame,pose); bpy.context.view_layer.update()
        for leg,offset in [('back_l',0),('front_l',.25),('back_r',.5),('front_r',.75)]:
            lateral=backward=lift=yaw=0
            if name=='walk':
                p=(phase+offset)%1
                if p<DUTY: relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY); relative=seconds*DUTY*(.5-u*u*(3-2*u)); lift=.040*math.sin(math.pi*u)
                yaw=-SPEED/RADIUS*relative
                ankle=arm.data.bones[leg+'_foot'].head_local; x=ankle.x-RADIUS; y=ankle.y
                lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,leg,frame,delta,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for fc in base.action_fcurves(action):
        for key in fc.keyframe_points: key.interpolation='LINEAR'


def main():
    source,output=sys.argv[sys.argv.index('--')+1:]
    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=source)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    for o in meshes:
        bpy.context.view_layer.objects.active=o; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM'); bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    lm={'height':.91,'length':1.02,'legs':FEET,'front_y':-.14,'back_y':.38,
        'chest':Vector((0,-.14,.48)),'chest_top':.65,'hips':Vector((0,.32,.49)),
        'head':Vector((0,-.27,.78)),'snout':Vector((0,-.36,.78)),'rear':Vector((0,.44,.60))}
    arm=base.build_armature(lm); arm.name='yayu_rig'
    body=bpy.data.objects['yayu_ox_body']; base.skin(body,arm)
    axial=[arm.data.bones[n] for n in ('hips','spine1','spine2','chest','neck')]
    # Keep body mass out of leg chains and the lower pasterns planted with
    # their whole HIGH hoof. Continuous weights through the upper joints.
    for v in body.data.vertices:
        if v.co.z<.12:
            name=min(FEET,key=lambda k:(v.co-FEET[k]).length_squared)+'_foot'
            for g in body.vertex_groups: g.remove([v.index])
            body.vertex_groups[name].add([v.index],1,'REPLACE')
        elif v.co.z>.38:
            blend=smooth(.38,.50,v.co.z)
            weights={body.vertex_groups[g.group].name:g.weight*(1-blend) for g in v.groups}
            nearest=min(axial,key=lambda b:(b.head_local-v.co).length_squared)
            weights[nearest.name]=weights.get(nearest.name,0)+blend
            for g in body.vertex_groups: g.remove([v.index])
            for name,w in weights.items():
                if w>1e-6: body.vertex_groups[name].add([v.index],w,'REPLACE')
    base.normalize_weights(body)
    bpy.context.view_layer.objects.active=arm; bpy.ops.object.mode_set(mode='EDIT')
    b=arm.data.edit_bones.new('yayu_tail_bone'); b.head=(0,.44,.60); b.tail=(0,.54,.20); b.parent=arm.data.edit_bones['hips']
    bpy.ops.object.mode_set(mode='OBJECT')
    for o in meshes:
        if o is body: continue
        if o.name.startswith('yayu_horse_hoof_'): rigid(o,arm,o.name.removeprefix('yayu_horse_hoof_')+'_foot')
        elif o.name=='yayu_tail': rigid(o,arm,'yayu_tail_bone')
        else: rigid(o,arm,'head')
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4),('walk',WALK_SECONDS),('special',4)]: animate(arm,name,seconds)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('YAYU_RIG',len(arm.data.bones),'bones; body unweighted',base.unweighted_count(body))
    assert base.unweighted_count(body)==0

if __name__=='__main__': main()
