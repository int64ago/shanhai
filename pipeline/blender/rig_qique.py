"""Qique's grounded two-foot fowl walk and wing-spreading claw display.
Uses the proven dense bird feather weighting, with independent sagittal IK
and paw-flat contact for the sculpted rodent-like feet. All source/visual
interpretation is recorded in content/beasts/qique.json.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_jingwei as bird
from rig_avian import FPS,load,new_action,finish_action,key_loc,key_pose,world_rot


def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def contact(arm,lm,side,frame,delta,backward=0,lift=0,lateral=0,yaw=0):
    ankle=lm['feet'][side]
    upper=arm.pose.bones[f'leg_{side}_upper'];lower=arm.pose.bones[f'leg_{side}_lower'];foot=arm.pose.bones[f'foot_{side}']
    hip=upper.bone.head_local+delta
    target=ankle+Vector((lateral,backward,lift))
    axis=target-hip;direction=axis.normalized();distance=min(axis.length,(upper.bone.length+lower.bone.length)*.9999)
    l1,l2=upper.bone.length,lower.bone.length
    along=(l1*l1-l2*l2+distance*distance)/(2*distance)
    normal=Vector((0,-direction.z,direction.y)).normalized()
    # Preserve the rest knee's bend side. The crow template bends the other
    # way; using its unconditional sign inverts this shorter fowl leg.
    rest_axis=(lower.bone.tail_local-upper.bone.head_local).normalized()
    rest_normal=Vector((0,-rest_axis.z,rest_axis.y)).normalized()
    side=1 if (upper.bone.tail_local-upper.bone.head_local).dot(rest_normal)>=0 else -1
    knee=hip+direction*along+normal*math.sqrt(max(0,l1*l1-along*along))*side
    bird.set_segment(upper,hip,knee);bird.set_segment(lower,knee,target)
    # Rotate about the ankle, countering the runtime body's circular heading.
    # The whole rigid sole, including its outer toes, stays planted in world space.
    foot.matrix=Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-ankle)@foot.bone.matrix_local
    bpy.context.view_layer.update()
    for pb in [upper,lower,foot]:
        pb.keyframe_insert('rotation_quaternion',frame=frame);pb.keyframe_insert('location',frame=frame)


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for f in range(n+1):
        t=f/FPS;phase=f/n
        delta=Vector((0,0,-.012+.003*math.sin(phase*math.tau*2)))
        spread=0;neck=.02*math.sin(phase*math.tau)
        targets={side:(0,0,0,0) for side in ['l','r']}
        if name=='walk':
            # Match Qique.tsx's .16m/s, .8m radius circle, including different
            # inside/outside stride lengths and inverse sole yaw during stance.
            radius=.8;omega=.16/radius;duty=.62
            for side,offset in [('l',0),('r',.5)]:
                p=(phase+offset)%1
                if p<duty:
                    relative=seconds*(p-duty/2);lift=0
                else:
                    u=(p-duty)/(1-duty)
                    relative=seconds*duty*(.5-u*u*(3-2*u));lift=.065*math.sin(u*math.pi)
                yaw=-omega*relative
                ankle=lm['feet'][side];x=ankle.x-radius;y=ankle.y
                px=radius+math.cos(yaw)*x-math.sin(yaw)*y
                py=math.sin(yaw)*x+math.cos(yaw)*y
                targets[side]=(py-ankle.y,lift,px-ankle.x,yaw)
            neck=.025*math.sin(phase*math.tau*2)
        elif name=='alert':
            spread=smooth(.3,1.1,t)*(1-smooth(3.0,3.8,t))
            neck=.13*spread
            # Raise one broad foot to expose the five digits and hooked claws,
            # then plant it before the wings relax. Opposite foot stays fixed.
            lift=.10*smooth(1.0,1.5,t)*(1-smooth(2.0,2.6,t))
            targets['l']=(-.025*spread,lift,0,0)
        key_loc(arm,f,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'neck':world_rot(arm.pose.bones['neck'],(1,0,0),neck),
              'head':world_rot(arm.pose.bones['head'],(0,0,1),.03*math.sin(phase*math.tau)),
              'tail_feather':world_rot(arm.pose.bones['tail_feather'],(1,0,0),-.045*math.sin(phase*math.tau))}
        for side,sign in [('l',1),('r',-1)]:
            for i in [1,2,3]:
                fold=(.96-.80*spread) if i==1 else .025*math.sin(t*3-i)*spread
                pb=arm.pose.bones[f'wing_{side}_{i}']
                sweep=(.52 if i==1 else .18)*(1-spread)
                pose[pb.name]=world_rot(pb,(0,0,1),sign*sweep)@world_rot(pb,(0,1,0),sign*fold)
        key_pose(arm,f,pose);bpy.context.view_layer.update()
        for side,(back,lift,lateral,yaw) in targets.items():contact(arm,lm,side,f,delta,back,lift,lateral,yaw)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for k in fc.keyframe_points:k.interpolation='LINEAR'


def main():
    args=sys.argv[sys.argv.index('--')+1:];obj=load(args[0]);bpy.context.scene.render.fps=FPS
    arm,lm=bird.make_rig(obj)
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    for side,sign in [('l',1),('r',-1)]:
        ankle=Vector((sign*.145,-.045,.075));hip=Vector((sign*.145,.0,.43));knee=Vector((sign*.145,-.08,.25))
        lm['feet'][side]=ankle
        for name,a,b in [(f'leg_{side}_upper',hip,knee),(f'leg_{side}_lower',knee,ankle),(f'foot_{side}',ankle,ankle+Vector((0,-.14,-.06)))]:
            arm.data.edit_bones[name].head=a;arm.data.edit_bones[name].tail=b
    bpy.ops.object.mode_set(mode='OBJECT')
    bird.skin(obj,arm,lm)
    # All sculpted palms/digits/claws remain rigid with their respective paw;
    # transition the narrow bare ankle into the shin above the replacement.
    for v in obj.data.vertices:
        if v.co.z<.15 and v.co.y<.15:
            for g in obj.vertex_groups:g.remove([v.index])
            obj.vertex_groups['foot_l' if v.co.x>0 else 'foot_r'].add([v.index],1,'REPLACE')
    for name,seconds in [('idle',4),('walk',1.2),('alert',4.2)]:animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('EXPORTED',args[1],'bones',len(arm.data.bones),'independent paw-flat IK')

if __name__=='__main__':main()
