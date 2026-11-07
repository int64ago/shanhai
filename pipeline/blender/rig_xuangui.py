"""Fresh HIGH turtle/bird/serpent assembly and rigid-shell, planted turtle gait.
Inputs are normalized (+Z glTF forward) generated surfaces, never primitives.
"""
import sys, math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as base
from rig_jingwei import set_segment
from rig_ershu import smooth
FPS = 30
RADIUS = .85
SPEED = .065
DUTY = .74
WALK_SECONDS = 2.8
# Start inside the throat opening, below the shell rim. The lower neck curves
# forward out of the opening before rising, rather than piercing the shell roof.
NECK_ROOT = Vector((0, -.42, .24))
TAIL_ROOT = Vector((0, .50, .25))


def load(path, name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in set(bpy.data.objects)-before if o.type == 'MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes: o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes)>1: bpy.ops.object.join()
    obj = bpy.context.object
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = name
    return obj


def lift_neck_texture(obj):
    """A UV mask lifts only neck scales; black eyes and head feathers stay dark."""
    slot = obj.data.materials[0]
    bsdf = next(n for n in slot.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    node = bsdf.inputs['Base Color'].links[0].from_node
    image = node.image.copy(); node.image = image
    if max(image.size)>2048: image.scale(2048,2048)
    width,height=image.size
    pixels=np.asarray(image.pixels[:],dtype=np.float32).reshape(height,width,4)
    mask=np.zeros((height,width),dtype=np.float32)
    uv=obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        weights=np.array([1-smooth(.33,.45,obj.data.vertices[i].co.z) for i in tri.vertices])
        if max(weights)<1e-6: continue
        pts=np.array([(uv[i].uv.x*(width-1),uv[i].uv.y*(height-1)) for i in tri.loops])
        x0=max(0,int(np.floor(pts[:,0].min()))); x1=min(width-1,int(np.ceil(pts[:,0].max())))
        y0=max(0,int(np.floor(pts[:,1].min()))); y1=min(height-1,int(np.ceil(pts[:,1].max())))
        a,b,c=pts; den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-8: continue
        yy,xx=np.mgrid[y0:y1+1,x0:x1+1]
        w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den; w2=1-w0-w1
        inside=(w0>=-.015)&(w1>=-.015)&(w2>=-.015)
        values=np.clip(w0*weights[0]+w1*weights[1]+w2*weights[2],0,1)*inside
        region=mask[y0:y1+1,x0:x1+1]; np.maximum(region,values,out=region)
    # Preserve generated scale variation while moving the grey-blue neck out
    # of the ink shader's solid-black range. This is inferred artistic color.
    w=mask[:,:,None]
    pixels[:,:,:3]=np.clip(pixels[:,:,:3]*(1-.3*w)+np.array([.16,.19,.20])*w,0,1)
    image.pixels.foreach_set(pixels.ravel()); image.update(); image.pack()


def add_bone(arm, name, head, tail, parent):
    bone = arm.data.edit_bones.new(name)
    bone.head = head; bone.tail = tail
    if parent: bone.parent = arm.data.edit_bones[parent]
    return bone


def bind(obj, arm, weights):
    groups = {b.name: obj.vertex_groups.new(name=b.name) for b in arm.data.bones}
    for v in obj.data.vertices:
        for name, weight in weights(v.co).items():
            if weight > 1e-7: groups[name].add([v.index], weight, 'REPLACE')
    mod = obj.modifiers.new('generated anatomy skin', 'ARMATURE'); mod.object = arm
    obj.parent = arm
    base.normalize_weights(obj)


def chain_weights(value, count, prefix):
    t = max(0, min(count-1, value)); lo = int(t); w = t-lo
    result = {f'{prefix}{lo}': 1-w}
    if w and lo+1<count: result[f'{prefix}{lo+1}'] = w
    return result


def contact(arm, leg, frame, lateral=0, backward=0, lift=0, yaw=0):
    upper=arm.pose.bones[leg+'_upper']; lower=arm.pose.bones[leg+'_lower']; foot=arm.pose.bones[leg+'_foot']
    hip=upper.bone.head_local; ankle=foot.bone.head_local
    target=ankle+Vector((lateral,backward,lift)); axis=target-hip
    direction=axis.normalized(); l1,l2=upper.bone.length,lower.bone.length
    distance=min(axis.length,(l1+l2)*.999999)
    along=(l1*l1-l2*l2+distance*distance)/(2*distance)
    rest=upper.bone.tail_local-hip
    normal=(rest-direction*rest.dot(direction)).normalized()
    knee=hip+direction*along+normal*math.sqrt(max(0,l1*l1-along*along))
    set_segment(upper,hip,knee); set_segment(lower,knee,target)
    foot.matrix=Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-ankle)@foot.bone.matrix_local
    bpy.context.view_layer.update()
    for bone in (upper,lower,foot):
        bone.keyframe_insert('rotation_quaternion',frame=frame); bone.keyframe_insert('location',frame=frame)


def animate(arm, name, seconds):
    action=base.new_action(arm,name); n=round(seconds*FPS)
    for frame in range(n+1):
        t=frame/FPS; phase=frame/n
        display=smooth(.2,1.2,t)*(1-smooth(3.0,4.7,t)) if name=='special' else 0
        pose={}
        for i in range(4):
            bone=arm.pose.bones[f'neck_{i}']
            # Keep the buried root steady; motion flows through the upper neck.
            amp=(i/3)*(.013+.016*display)
            pose[bone.name]=base.world_rot(bone,base.X,-.028*display+amp*math.sin(phase*math.tau-i*.35))@base.world_rot(bone,base.Z,.016*display*math.sin(t*2))
        for i in range(8):
            bone=arm.pose.bones[f'tail_{i}']
            pose[bone.name]=base.world_rot(bone,base.Z,(.014+.015*display)*(i+1)/8*math.sin(phase*math.tau-i*.48))
        base.key_pose(arm,frame,pose); bpy.context.view_layer.update()
        for leg,offset in [('back_l',0),('front_l',.25),('back_r',.5),('front_r',.75)]:
            lateral=backward=lift=yaw=0
            if name=='walk':
                p=(phase+offset)%1
                if p<DUTY: relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY); relative=seconds*DUTY*(.5-u*u*(3-2*u)); lift=.035*math.sin(math.pi*u)
                yaw=-SPEED/RADIUS*relative
                ankle=arm.data.bones[leg+'_foot'].head_local; x=ankle.x-RADIUS; y=ankle.y
                lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,leg,frame,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for fc in base.action_fcurves(action):
        for key in fc.keyframe_points: key.interpolation='LINEAR'


def main():
    body_path,head_path,tail_path,output=sys.argv[sys.argv.index('--')+1:]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body=load(body_path,'xuangui_body')
    # Turtle soles are broad, with toes sharing the resting ground plane.
    for v in body.data.vertices:
        if v.co.z<.023: v.co.z=0
    feet={}
    for front in (True,False):
        for sign,label in [(1,'l'),(-1,'r')]:
            pts=[v.co for v in body.data.vertices if v.co.z<.05 and sign*v.co.x>.20 and (v.co.y<0)==front]
            assert len(pts)>20
            name=('front' if front else 'back')+'_'+label
            feet[name]=Vector(((min(p.x for p in pts)+max(p.x for p in pts))/2,(min(p.y for p in pts)+max(p.y for p in pts))/2,.055))
    print('XUANGUI_FEET',{k:tuple(round(x,5) for x in v) for k,v in feet.items()})
    head=load(head_path,'xuangui_bird_head')
    lift_neck_texture(head)
    # Retain the generated neck surface, but seat its root inside the throat.
    # A gradual forward sweep puts the upper neck in front of the shell rim.
    root_pts=[v.co for v in head.data.vertices if v.co.z<.012]
    origin=sum(root_pts,Vector())/len(root_pts)
    rotation=Matrix.Rotation(.38,3,'X')
    for v in head.data.vertices:
        p=(v.co-origin)*.88
        flare=1+.20*(1-smooth(0,.17,p.z))
        p.x*=flare; p.y*=flare
        height=p.z
        v.co=NECK_ROOT+rotation@p+Vector((0,-.13*smooth(0,.20,height),0))
    tail=load(tail_path,'xuangui_serpent_tail')
    max_y=max(v.co.y for v in tail.data.vertices)
    root_pts=[v.co for v in tail.data.vertices if v.co.y>max_y-.015]
    origin=sum(root_pts,Vector())/len(root_pts)
    rotation=Matrix.Rotation(math.pi,3,'Z')
    for v in tail.data.vertices: v.co=TAIL_ROOT+rotation@((v.co-origin)*.93)
    data=bpy.data.armatures.new('xuangui_rig'); arm=bpy.data.objects.new('xuangui_rig',data)
    bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active=arm
    bpy.ops.object.select_all(action='DESELECT'); arm.select_set(True); bpy.ops.object.mode_set(mode='EDIT')
    add_bone(arm,'root',(0,0,.25),(0,0,.4),None)
    for name,foot in feet.items():
        s=1 if name.endswith('_l') else -1
        hip=Vector((s*.25,foot.y*.78,.31))
        knee=Vector((s*.43,foot.y*.93,.19))
        add_bone(arm,name+'_upper',hip,knee,'root')
        add_bone(arm,name+'_lower',knee,foot,name+'_upper')
        # Independent sole target avoids compounded quaternion interpolation
        # through the two bending limb joints; the lower chain still reaches it.
        add_bone(arm,name+'_foot',foot,foot+Vector((0,-.10,0)),'root')
    for i in range(4):
        a=NECK_ROOT+Vector((0,-.07*i,.12*i))
        add_bone(arm,f'neck_{i}',a,a+Vector((0,-.07,.12)),'root' if i==0 else f'neck_{i-1}')
    for i in range(8):
        a=TAIL_ROOT+Vector((0,.116*i,0))
        add_bone(arm,f'tail_{i}',a,a+Vector((0,.116,0)),'root' if i==0 else f'tail_{i-1}')
    bpy.ops.object.mode_set(mode='OBJECT')
    def body_weights(p):
        # The hard shell and plastron stay entirely on root. Skin blends only
        # across actual lateral legs, keeping apertures and shoulders coherent.
        if p.z>=.265 or abs(p.x)<.25 or -.35<p.y<.285: return {'root':1}
        name=('front' if p.y<0 else 'back')+('_l' if p.x>0 else '_r')
        root_w=smooth(.20,.265,p.z)
        foot_w=1-smooth(.12,.20,p.z)
        lower_w=(1-root_w)*(1-foot_w)
        return {'root':root_w,name+'_foot':foot_w*(1-root_w),name+'_lower':lower_w}
    bind(body,arm,body_weights)
    bind(head,arm,lambda p:chain_weights((p.z-NECK_ROOT.z)/.12-.2,4,'neck_'))
    bind(tail,arm,lambda p:chain_weights((p.y-TAIL_ROOT.y)/.116-.45,8,'tail_'))
    for obj in (body,head,tail):
        assert base.unweighted_count(obj)==0
        obj.data.calc_loop_triangles(); print('XUANGUI_TRIS',obj.name,len(obj.data.loop_triangles))
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4),('walk',WALK_SECONDS),('special',4.8)]: animate(arm,name,seconds)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)

if __name__=='__main__': main()
