"""Fresh HIGH Bifang assembly: crane, one axial leg and paired mother wing.
120Hz IK keys keep actual toe soles flat and cancel runtime .14 m/s travel.
No negative runtime scale; right-wing offline reflection reverses face winding.
"""
import math,sys
from pathlib import Path
import bpy,bmesh
from mathutils import Matrix,Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from rig_avian import new_action,finish_action,key_loc,key_pose,world_rot
from rig_jingwei import set_segment
from turnaround import setup_render,render_views
FPS=120
SPEED=.14
SECONDS=1.4
DUTY=.38
ROOTS={s:Vector((s*.135,-.01,.88)) for s in (1,-1)}


def load(path,name):
    before=set(bpy.context.scene.objects);bpy.ops.import_scene.gltf(filepath=path)
    meshes=[o for o in bpy.context.scene.objects if o not in before and o.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:o.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    if len(meshes)>1:bpy.ops.object.join()
    o=meshes[0];bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    o.name=name;return o


def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def skin(o,arm,weights):
    names={n for ws in weights for n,w in ws};groups={n:o.vertex_groups.new(name=n) for n in names}
    for v,ws in zip(o.data.vertices,weights):
        for n,w in ws:
            if w>1e-6:groups[n].add([v.index],w,'REPLACE')
    mod=o.modifiers.new('Bifang anatomical skin','ARMATURE');mod.object=arm;o.parent=arm


def make_arm(body,leg):
    data=bpy.data.armatures.new('bifang_rig');arm=bpy.data.objects.new('bifang_rig',data);bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    def bone(n,a,b,parent=None,deform=True):
        q=data.edit_bones.new(n);q.head=a;q.tail=b;q.use_deform=deform
        if parent:q.parent=data.edit_bones[parent]
    bone('root',(0,0,0),(0,0,.15),deform=False)
    bone('pelvis',(0,.10,.68),(0,-.02,.86),'root')
    bone('chest',(0,-.02,.86),(0,-.10,.97),'pelvis')
    bone('neck_0',(0,-.10,.97),(0,-.18,1.13),'chest')
    bone('neck_1',(0,-.18,1.13),(0,-.14,1.34),'neck_0')
    bone('neck_2',(0,-.14,1.34),(0,-.18,1.47),'neck_1')
    bone('head',(0,-.18,1.47),(0,-.39,1.43),'neck_2')
    bone('tail',(0,.24,.78),(0,.40,.72),'pelvis')
    bone('leg_upper',(0,.10,.68),(0,.145,.35),'pelvis')
    bone('leg_lower',(0,.145,.35),(0,.10,.065),'leg_upper')
    bone('foot',(0,.10,.065),(0,-.02,.025),'leg_lower')
    for side,label in [(1,'l'),(-1,'r')]:
        for i in range(4):
            a=ROOTS[side]+Vector((side*.245*i,0,0));b=a+Vector((side*.245,0,0))
            bone(f'wing_{label}_{i}',a,b,'chest' if i==0 else f'wing_{label}_{i-1}')
        tip=ROOTS[side]+Vector((side*.98,0,0));bone(f'wing_{label}_attach',tip,tip+Vector((side*.04,0,0)),f'wing_{label}_3',False)
    bone('beak_attach',(0,-.40,1.43),(0,-.44,1.43),'head',False)
    bone('tail_attach',(0,.40,.72),(0,.44,.72),'tail',False)
    bpy.ops.object.mode_set(mode='OBJECT');return arm


def contact(arm,f,delta,back=0,lift=0):
    upper,lower,foot=[arm.pose.bones[n] for n in ('leg_upper','leg_lower','foot')]
    hip=upper.bone.head_local+delta;ankle=foot.bone.head_local;target=ankle+Vector((0,back,lift));axis=target-hip
    d=min(axis.length,(upper.bone.length+lower.bone.length)*.99999);direction=axis.normalized()
    along=(upper.bone.length**2-lower.bone.length**2+d*d)/(2*d)
    perpendicular=Vector((0,-direction.z,direction.y)).normalized()
    knee=hip+direction*along+perpendicular*math.sqrt(max(0,upper.bone.length**2-along**2))
    set_segment(upper,hip,knee);set_segment(lower,knee,target)
    foot.matrix=Matrix.Translation(target-ankle)@foot.bone.matrix_local;bpy.context.view_layer.update()
    for pb in (upper,lower,foot):
        pb.keyframe_insert('rotation_quaternion',frame=f);pb.keyframe_insert('location',frame=f)


def animate(arm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for f in range(n+1):
        phase=f/n;t=f/FPS;wave=math.sin(phase*math.tau);back=lift=spread=0
        delta=Vector((0,0,-.020+.002*wave));nod=.018*wave
        if name=='walk':
            if phase<=DUTY:back=SPEED*seconds*(phase-DUTY/2);delta.z=-.024-.008*math.sin(phase/DUTY*math.pi)
            else:
                u=(phase-DUTY)/(1-DUTY);back=SPEED*seconds*DUTY*(.5-u*u*(3-2*u));lift=.15*math.sin(math.pi*u);delta.z=-.024+.095*math.sin(math.pi*u)
            spread=.35+.22*math.sin(phase*math.tau-.5);nod=.045*wave
        elif name=='special':
            spread=smooth(.20,1.15,t)*(1-smooth(3.45,4.65,t));nod=-.08*spread+.025*math.sin(t*5)*spread
        key_loc(arm,f,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={f'neck_{i}':world_rot(arm.pose.bones[f'neck_{i}'],(1,0,0),nod/3) for i in range(3)}
        pose['head']=world_rot(arm.pose.bones['head'],(0,0,1),.018*wave)
        pose['tail']=world_rot(arm.pose.bones['tail'],(1,0,0),.025*wave)
        for side,label in [(1,'l'),(-1,'r')]:
            for i in range(4):
                pb=arm.pose.bones[f'wing_{label}_{i}']
                # Shoulder opens first; elbow/wrist follow with a small lag.
                sweep=([1.05,.65,-.25,0][i])*(1-spread)
                flap=(.12+.13*spread*math.sin(t*math.tau*.9-i*.35)) if i==0 else .025*spread*math.sin(t*4-i*.5)
                roll=-.65*(1-spread) if i==0 else 0
                pose[pb.name]=world_rot(pb,(0,0,1),side*sweep)@world_rot(pb,(0,1,0),side*flap)@world_rot(pb,(1,0,0),roll)
        key_pose(arm,f,pose);bpy.context.view_layer.update();contact(arm,f,delta,back,lift)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for k in fc.keyframe_points:k.interpolation='LINEAR'


def main():
    body_path,leg_path,wing_path,output,views=sys.argv[sys.argv.index('--')+1:]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body=load(body_path,'bifang_body')
    for v in body.data.vertices:v.co.z+=.54
    leg=load(leg_path,'bifang_single_leg');height=max(v.co.z for v in leg.data.vertices)
    for v in leg.data.vertices:
        v.co*=.70/height;v.co.y+=.10
        if v.co.z<.008:v.co.z=0
    # Sculpt small overlapping feather vanes over the generated bare thigh
    # root. The scaly hock/tarsus and all generated toes remain untouched.
    verts=[];faces=[]
    for row in range(3):
        for j in range(9):
            angle=math.tau*(j+.5*(row%2))/9
            normal=Vector((math.cos(angle),math.sin(angle),0));tangent=Vector((-math.sin(angle),math.cos(angle),0))
            start=len(verts);top=.595-row*.052
            for i in range(10):
                u=i/9;z=top-.105*u;center=Vector((0,.10+.045*(.68-z)/.33,z))
                width=.023*math.sin(math.pi*u)**.7+.0005
                for k in range(10):
                    phi=math.tau*k/10
                    q=center+normal*(.033+.006*math.sin(math.pi*u)+.003*math.sin(phi)*math.sin(math.pi*u))+tangent*(width*math.cos(phi))
                    verts.append(tuple(q))
            for i in range(9):
                for k in range(10):
                    a=start+i*10+k;b=start+i*10+(k+1)%10;faces.append((a,b,b+10,a+10))
    me=bpy.data.meshes.new('sculpted thigh feather vanes');me.from_pydata(verts,[],faces);me.update()
    tuft=bpy.data.objects.new('feathered thigh transition',me);bpy.context.collection.objects.link(tuft)
    mat=bpy.data.materials.new('thigh feather azure');mat.use_nodes=True;mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.035,.36,.43,1);mat.diffuse_color=(.035,.36,.43,1);me.materials.append(mat)
    for f in me.polygons:f.use_smooth=True
    bpy.ops.object.select_all(action='DESELECT');leg.select_set(True);tuft.select_set(True);bpy.context.view_layer.objects.active=leg;bpy.ops.object.join()
    wings=[]
    for side,label in [(1,'l'),(-1,'r')]:
        wing=load(wing_path,f'bifang_wing_{label}')
        # Generated mother is X-horizontal / Z-chord; rotate into flight plane.
        for v in wing.data.vertices:
            x,y,z=v.co;v.co=ROOTS[side]+Vector((side*(x+.50),.28-z,y))
        if side==-1:
            bm=bmesh.new();bm.from_mesh(wing.data);bmesh.ops.reverse_faces(bm,faces=list(bm.faces));bm.to_mesh(wing.data);bm.free()
        wings.append((wing,side,label))
    arm=make_arm(body,leg)
    weights=[]
    for v in body.data.vertices:
        z=v.co.z
        if z<.88:ws=[('pelvis',1)]
        elif z<.99:
            t=smooth(.88,.99,z);ws=[('chest',1-t),('neck_0',t)]
        elif z<1.20:
            t=smooth(1.02,1.20,z);ws=[('neck_0',1-t),('neck_1',t)]
        elif z<1.43:
            t=smooth(1.25,1.43,z);ws=[('neck_1',1-t),('neck_2',t)]
        else:ws=[('head',1)]
        weights.append(ws)
    skin(body,arm,weights)
    weights=[]
    for v in leg.data.vertices:
        z=v.co.z
        if z<.09:ws=[('foot',1)]
        elif z<.17:
            t=smooth(.09,.17,z);ws=[('foot',1-t),('leg_lower',t)]
        else:
            t=smooth(.28,.41,z);ws=[('leg_lower',1-t),('leg_upper',t)]
        weights.append(ws)
    skin(leg,arm,weights)
    for wing,side,label in wings:
        weights=[]
        for v in wing.data.vertices:
            t=max(0,min(3,side*(v.co.x-ROOTS[side].x)/.245-.15));i=int(t);w=t-i
            ws=[(f'wing_{label}_{i}',1-w)]
            if w and i<3:ws.append((f'wing_{label}_{i+1}',w))
            weights.append(ws)
        skin(wing,arm,weights)
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4),('walk',SECONDS),('special',4.8)]:animate(arm,name,seconds)
    bpy.context.scene.frame_set(0)
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('BIFANG_RIG',len(arm.data.bones),'bones','triangles',sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in [body,leg]+[w[0] for w in wings]))
    # Concepts use the real rig at the first idle frame, including folded wings.
    arm.animation_data.action=bpy.data.actions['idle'];bpy.context.scene.frame_set(0);bpy.context.view_layer.update()
    pts=[]
    for o in [body,leg]+[w[0] for w in wings]:
        deps=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(deps);mesh=ev.to_mesh();pts.extend([ev.matrix_world@v.co for v in mesh.vertices]);ev.to_mesh_clear()
    lo,hi=[Vector(tuple(fn(v[i] for v in pts) for i in range(3))) for fn in (min,max)]
    me=bpy.data.meshes.new('bounds');me.from_pydata([tuple((x,y,z)) for x in (lo.x,hi.x) for y in (lo.y,hi.y) for z in (lo.z,hi.z)],[],[])
    bounds=bpy.data.objects.new('bounds',me);bpy.context.collection.objects.link(bounds)
    Path(views).mkdir(parents=True,exist_ok=True);cam=setup_render(900);render_views(bounds,cam,views)

if __name__=='__main__':main()
