"""Yingzhao's independent HIGH assembly rig with world-planted curved gait.
The inverse circular targets and sole yaw match runtime root movement exactly.
"""
import math,sys
from pathlib import Path
import bpy
from mathutils import Matrix,Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_quadruped as base
from rig_jingwei import set_segment
from rig_ershu import rigid,smooth
from prepare_yingzhao import WING_ROOTS,FEET
FPS=30
RADIUS=1.0
SPEED=.14
WALK_SECONDS=1.8
DUTY=.68
WING_BONES=5


def contact(arm,leg,frame,delta,lateral=0,backward=0,lift=0,yaw=0):
    upper=arm.pose.bones[leg+'_upper'];lower=arm.pose.bones[leg+'_lower'];foot=arm.pose.bones[leg+'_foot']
    hip=upper.bone.head_local+delta;ankle=foot.bone.head_local
    target=ankle+Vector((lateral,backward,lift));axis=target-hip
    direction=axis.normalized();l1,l2=upper.bone.length,lower.bone.length
    distance=min(axis.length,(l1+l2)*.99999)
    along=(l1*l1-l2*l2+distance*distance)/(2*distance)
    normal=Vector((0,-direction.z,direction.y)).normalized()
    rest_axis=(lower.bone.tail_local-hip).normalized();rest_normal=Vector((0,-rest_axis.z,rest_axis.y)).normalized()
    sign=1 if (upper.bone.tail_local-hip).dot(rest_normal)>=0 else -1
    knee=hip+direction*along+normal*math.sqrt(max(0,l1*l1-along*along))*sign
    set_segment(upper,hip,knee);set_segment(lower,knee,target)
    foot.matrix=Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-ankle)@foot.bone.matrix_local
    bpy.context.view_layer.update()
    for bone in (upper,lower,foot):
        bone.keyframe_insert('rotation_quaternion',frame=frame);bone.keyframe_insert('location',frame=frame)


def extra(arm):
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    for side,label in [(1,'l'),(-1,'r')]:
        for i in range(WING_BONES):
            b=arm.data.edit_bones.new(f'yingzhao_wing_{label}_{i}')
            b.head=WING_ROOTS[side]+Vector((side*.16*i,0,0));b.tail=b.head+Vector((side*.16,0,0))
            b.parent=arm.data.edit_bones['chest' if i==0 else f'yingzhao_wing_{label}_{i-1}']
            b.use_connect=i>0
    b=arm.data.edit_bones.new('yingzhao_tail');b.head=(0,.405,.66);b.tail=(0,.52,.26);b.parent=arm.data.edit_bones['hips']
    bpy.ops.object.mode_set(mode='OBJECT')


def wing_skin(obj,arm,side,label):
    groups=[obj.vertex_groups.new(name=f'yingzhao_wing_{label}_{i}') for i in range(WING_BONES)]
    for v in obj.data.vertices:
        t=max(0,min(WING_BONES-1,(side*(v.co.x-WING_ROOTS[side].x))/.16-.5));lo=int(t);w=t-lo
        groups[lo].add([v.index],1-w,'REPLACE')
        if w and lo+1<WING_BONES:groups[lo+1].add([v.index],w,'REPLACE')
    mod=obj.modifiers.new('independent feather chain','ARMATURE');mod.object=arm;obj.parent=arm


def animate(arm,name,seconds):
    action=base.new_action(arm,name);n=round(seconds*FPS)
    for frame in range(n+1):
        t=frame/FPS;phase=frame/n;display=smooth(.2,1.1,t)*(1-smooth(3.1,4.6,t)) if name=='special' else 0
        pose={'head':base.world_rot(arm.pose.bones['head'],base.X,-.025*display+.01*math.sin(phase*math.tau)),
              'yingzhao_tail':base.world_rot(arm.pose.bones['yingzhao_tail'],base.Y,.04*math.sin(phase*math.tau))}
        for side,label in [(1,'l'),(-1,'r')]:
            for i in range(WING_BONES):
                bone=arm.pose.bones[f'yingzhao_wing_{label}_{i}']
                if i==0:
                    sweep=side*(.65-.45*display)
                    elevation=-side*(.26+.18*display+.14*display*math.sin(t*math.tau*.8))
                    pose[bone.name]=base.world_rot(bone,base.Z,sweep)@base.world_rot(bone,base.Y,elevation)
                else:pose[bone.name]=base.world_rot(bone,base.Y,-side*(.025+.035*display)*math.sin(t*2-i*.45))
        # Lower the walking torso slightly to leave reach reserve in the
        # nearly straight forelegs; otherwise clamped IK lifts planted soles.
        delta=Vector((0,0,-.018 if name=='walk' else 0))
        base.key_loc(arm,frame,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,frame,pose);bpy.context.view_layer.update()
        for leg,offset in [('back_l',0),('front_l',.25),('back_r',.5),('front_r',.75)]:
            lateral=backward=lift=yaw=0
            if name=='walk':
                p=(phase+offset)%1
                if p<DUTY:relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY);relative=seconds*DUTY*(.5-u*u*(3-2*u));lift=.045*math.sin(math.pi*u)
                yaw=-SPEED/RADIUS*relative
                ankle=arm.data.bones[leg+'_foot'].head_local;x=ankle.x-RADIUS;y=ankle.y
                lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,leg,frame,delta,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for k in fc.keyframe_points:k.interpolation='LINEAR'


def main():
    source,output=sys.argv[sys.argv.index('--')+1:];bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=source)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    for o in meshes:
        bpy.context.view_layer.objects.active=o;bpy.ops.object.select_all(action='DESELECT');o.select_set(True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    lm={'height':1.04,'length':1.05,'legs':FEET,'front_y':-.17,'back_y':.38,'chest':Vector((0,-.17,.59)),
        'chest_top':.76,'hips':Vector((0,.33,.60)),'head':Vector((0,-.30,.94)),
        'snout':Vector((0,-.40,.93)),'rear':Vector((0,.405,.66))}
    arm=base.build_armature(lm);arm.name='yingzhao_rig'
    body=bpy.data.objects['yingzhao_horse_body'];base.skin(body,arm)
    # Rigid hooves prevent heat diffusion from bending soles. Blend upper
    # chest/neck only to axial bones; wing roots cannot steal body weights.
    axial=[arm.data.bones[n] for n in ('hips','spine1','spine2','chest','neck')]
    for v in body.data.vertices:
        if v.co.z<.105:
            name=min(FEET,key=lambda k:(v.co-FEET[k]).length_squared)+'_foot'
            for g in body.vertex_groups:g.remove([v.index])
            body.vertex_groups[name].add([v.index],1,'REPLACE')
        elif v.co.z>.46:
            blend=smooth(.46,.59,v.co.z);weights={body.vertex_groups[g.group].name:g.weight*(1-blend) for g in v.groups}
            nearest=min(axial,key=lambda b:(b.head_local-v.co).length_squared);weights[nearest.name]=weights.get(nearest.name,0)+blend
            for g in body.vertex_groups:g.remove([v.index])
            for name,w in weights.items():
                if w>1e-6:body.vertex_groups[name].add([v.index],w,'REPLACE')
    base.normalize_weights(body);extra(arm)
    for o in meshes:
        if o is body:continue
        if o.name.startswith('yingzhao_wing_'):
            label=o.name[-1];wing_skin(o,arm,1 if label=='l' else -1,label)
        elif o.name=='yingzhao_horse_tail':rigid(o,arm,'yingzhao_tail')
        elif o.name=='yingzhao_neck_bridge':rigid(o,arm,'neck')
        else:rigid(o,arm,'head')
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4),('walk',WALK_SECONDS),('special',4.8)]:animate(arm,name,seconds)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('YINGZHAO_RIG',len(arm.data.bones),'bones; body unweighted',base.unweighted_count(body))

if __name__=='__main__':main()
