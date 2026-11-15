import bpy, bmesh, sys, math, json, os
from mathutils import Vector, Matrix

import argparse
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
parser = argparse.ArgumentParser(description='Prepare the historical Shuhu four-view reference from explicit Medium sources')
parser.add_argument('--body', default=ROOT+'/raw/shuhu-production-20261114-human-headed-equine-v4-medium/base_basic_pbr.glb')
parser.add_argument('--wing-donor', default=ROOT+'/raw/shuhu-production-20261115-native-human-face-v12-medium/base_basic_pbr.glb')
parser.add_argument('--output-dir', default=ROOT+'/raw/_build/shuhu-native-reference')
parser.add_argument('--inspect', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
BASE = str(Path(args.body).resolve())
DONOR = str(Path(args.wing_donor).resolve())
OUT = str(Path(args.output_dir).resolve())
os.makedirs(OUT,exist_ok=True)

def load(path,name):
    before=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    obs=[o for o in bpy.data.objects if o not in before and o.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active=obs[0]
    bpy.ops.object.convert(target='MESH')
    bpy.ops.object.join()
    obj=bpy.context.object
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    obj.name=name
    vs=[v.co for v in obj.data.vertices]
    lo=Vector(tuple(min(v[i] for v in vs) for i in range(3)))
    hi=Vector(tuple(max(v[i] for v in vs) for i in range(3)))
    h=hi.z-lo.z
    mid=(lo+hi)/2
    for v in obj.data.vertices:
        v.co=(v.co-Vector((mid.x,mid.y,lo.z)))/h
    obj.data.update()
    print('MODEL',name,len(vs),'bounds',list(lo),list(hi),flush=True)
    return obj

def clusters(obj,z):
    pts=[v.co.copy() for v in obj.data.vertices if v.co.z<z]
    groups=[]
    while pts:
        queue=[pts.pop()]; group=[]
        while queue:
            p=queue.pop();group.append(p)
            nearby=[q for q in pts if (p-q).length<.035]
            for q in nearby: pts.remove(q)
            queue+=nearby
        groups.append(group)
    print('FEET',obj.name,z,[(len(g),[round(sum(p[i] for p in g)/len(g),4) for i in range(3)]) for g in groups],flush=True)

def setup(size=800):
    sc=bpy.context.scene;sc.render.engine='CYCLES';sc.cycles.samples=16;sc.cycles.use_denoising=True
    sc.render.resolution_x=size;sc.render.resolution_y=size;sc.render.resolution_percentage=100
    sc.view_settings.view_transform='AgX'
    w=bpy.data.worlds.new('neutral');w.use_nodes=True;w.node_tree.nodes['Background'].inputs[0].default_value=(.47,.47,.47,1);w.node_tree.nodes['Background'].inputs[1].default_value=.8;sc.world=w
    for name,loc,power,size in [('key',(3,-4,5),400,4),('fill',(-4,-2,3),250,4),('rim',(1,4,4),350,3)]:
        data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size
        ob=bpy.data.objects.new(name,data);sc.collection.objects.link(ob);ob.location=loc;ob.rotation_euler=(Vector((0,0,.55))-ob.location).to_track_quat('-Z','Y').to_euler()

def render(obj,name,views=None,size=None):
    if size:bpy.context.scene.render.resolution_x=size;bpy.context.scene.render.resolution_y=size
    vs=[o.matrix_world@v.co for o in ([obj] if not isinstance(obj,list) else obj) for v in o.data.vertices]
    lo=Vector(tuple(min(v[i] for v in vs) for i in range(3)));hi=Vector(tuple(max(v[i] for v in vs) for i in range(3)))
    target=(lo+hi)/2
    directions=views or [('34',(1,-1.6,.40)),('side',(1,0,0)),('front',(0,-1,0)),('back',(0,1,0))]
    for label,dir in directions:
        cam=bpy.data.objects.new('camera_'+label,bpy.data.cameras.new('camera_'+label));bpy.context.scene.collection.objects.link(cam);cam.data.type='ORTHO'
        cam.location=target+Vector(dir).normalized()*4;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
        rot=cam.rotation_euler.to_matrix().transposed()
        proj=[rot@(p-target) for p in vs]
        span=max(max(p.x for p in proj)-min(p.x for p in proj),max(p.y for p in proj)-min(p.y for p in proj))
        cam.data.ortho_scale=span*1.15
        bpy.context.scene.camera=cam;bpy.context.view_layer.update();bpy.context.scene.render.filepath=name+'_'+label+'.png';bpy.ops.render.render(write_still=True)

def smoothstep(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)

def activate(ob):
    bpy.ops.object.select_all(action='DESELECT');ob.select_set(True);bpy.context.view_layer.objects.active=ob

def apply(ob,mod):
    activate(ob);bpy.ops.object.modifier_apply(modifier=mod.name)

def sample_color(ob):
    import numpy as np
    # Sample the native base-color atlases into dense corner colors before union.
    # The result is transferred by Blender's nearest-polygon interpolation.
    me=ob.data
    uv=np.empty(len(me.loops)*2,dtype=np.float32);me.uv_layers.active.data.foreach_get('uv',uv);uv=uv.reshape((-1,2))
    out=np.ones((len(me.loops),4),dtype=np.float32)
    for mi,mat in enumerate(me.materials):
        if not mat or not mat.use_nodes:continue
        principled=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if not principled:continue
        links=principled.inputs['Base Color'].links
        img=links[0].from_node.image if links and links[0].from_node.type=='TEX_IMAGE' else None
        ids=np.array([li for p in me.polygons if p.material_index==mi for li in p.loop_indices],dtype=np.int32)
        if img:
            w,h=img.size;pix=np.empty(w*h*4,dtype=np.float32);img.pixels.foreach_get(pix);pix=pix.reshape((h,w,4))
            xy=uv[ids]%1.0;xx=xy[:,0]*(w-1);yy=xy[:,1]*(h-1);x0=xx.astype(int);y0=yy.astype(int);x1=np.minimum(x0+1,w-1);y1=np.minimum(y0+1,h-1)
            fx=(xx-x0)[:,None];fy=(yy-y0)[:,None]
            col=(pix[y0,x0]*(1-fx)+pix[y0,x1]*fx)*(1-fy)+(pix[y1,x0]*(1-fx)+pix[y1,x1]*fx)*fy
            # Imported PNG/JPEG buffers expose sRGB values. Store scene-linear.
            rgb=col[:,:3];col[:,:3]=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
            out[ids]=col
        else:out[ids]=principled.inputs['Base Color'].default_value[:]
    attr=me.color_attributes.get('NativeColor') or me.color_attributes.new(name='NativeColor',type='FLOAT_COLOR',domain='CORNER')
    attr.data.foreach_set('color',out.ravel())
    return out

def mesh_clean(ob):
    bm=bmesh.new();bm.from_mesh(ob.data);bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000015)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(ob.data);bm.free();ob.data.update()

def cleanup_body(body):
    # The source head is turned slightly: preserve ALL native upper anatomy.
    # Only the region below the belly is mirrored to enforce four native hooves.
    bm=bmesh.new();bm.from_mesh(body.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000015)
    # Overlapping upper/lower solids avoid a zero-thickness contact seam.
    for cut in [.395,.465]:
        bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=(0,0,cut),plane_no=(0,0,1))
    bm.to_mesh(body.data);bm.free()
    legs=body.copy();legs.data=body.data.copy();bpy.context.scene.collection.objects.link(legs);legs.name='Mirrored_lower_legs_only'
    bm=bmesh.new();bm.from_mesh(legs.data)
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.co.z>.465001],context='VERTS')
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=(0,0,0),plane_no=(1,0,0))
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.co.x<-.000001],context='VERTS')
    # Remove the dangling horsehair region, including below the belly split.
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.co.y>.375],context='VERTS')
    bm.to_mesh(legs.data);bm.free()
    mirror=legs.modifiers.new('Applied lower-limb mirror','MIRROR');mirror.use_clip=True;mirror.use_mirror_merge=True;mirror.merge_threshold=.00003;apply(legs,mirror)
    bm=bmesh.new();bm.from_mesh(legs.data)
    bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(legs.data);bm.free()
    bm=bmesh.new();bm.from_mesh(body.data)
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.co.z<.394999 or (v.co.y>.375 and v.co.z<.69)],context='VERTS')
    bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(body.data);bm.free()
    # Keep both closed shells separate until voxel union; their 7cm overlap is deliberate.
    activate(body);legs.select_set(True);bpy.ops.object.join()
    rump=body.vertex_groups.new(name='Original_tail_cap_local_repair')
    for vertex in body.data.vertices:
        p=vertex.co
        w=smoothstep(.295,.345,p.y)*(1-smoothstep(.12,.165,abs(p.x)))*smoothstep(.395,.455,p.z)*(1-smoothstep(.65,.71,p.z))
        if w>.001:rump.add([vertex.index],w,'REPLACE')
    smooth=body.modifiers.new('Relax original tail cap only','SMOOTH');smooth.vertex_group=rump.name;smooth.factor=.62;smooth.iterations=12;apply(body,smooth)
    sub=body.modifiers.new('Dense native color sampling','SUBSURF');sub.subdivision_type='SIMPLE';sub.levels=2;apply(body,sub)
    sample_color(body)
    # Restore only the aft rump: cap UVs must never read the old black tail.
    import statistics
    colors=body.data.color_attributes['NativeColor'].data
    nearby=[colors[i].color[:] for i,l in enumerate(body.data.loops) if .20<body.data.vertices[l.vertex_index].co.y<.31 and .48<body.data.vertices[l.vertex_index].co.z<.66 and sum(colors[i].color[:3])>.42]
    chestnut=Vector(tuple(statistics.median(c[k] for c in nearby) for k in range(3)))
    for i,l in enumerate(body.data.loops):
        p=body.data.vertices[l.vertex_index].co
        if p.y>.28 and .40<p.z<.73:
            c=colors[i].color;w=smoothstep(.305,.355,p.y)
            if sum(c[:3])<.30:w=1
            rgb=Vector(c[:3]).lerp(chestnut,w);colors[i].color=(*rgb,1)
    print('BODY_CLEANED_NATIVE_UPPER',len(body.data.vertices),'RUMP_REPAINT',list(chestnut),flush=True)

def extract_wings(donor):
    bm=bmesh.new();bm.from_mesh(donor.data)
    # Retain only the positive-X feathered wing, rooted inside the horse shoulder.
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.co.x < .143+max(0,.62-v.co.z)*.60 or v.co.y>-.025 or v.co.z<.49],context='VERTS')
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000012)
    bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(donor.data);bm.free()
    # Bury the entire inner cut within the shoulder/back volume, not outside it.
    # Measured original cut top z=.754; shifted top=.639 is below the native back.
    for v in donor.data.vertices:
        v.co.x-=.095
        v.co.z-=.115
    mirror=donor.modifiers.new('Applied paired wing mirror','MIRROR');mirror.use_mirror_merge=False;apply(donor,mirror)
    mesh_clean(donor);sample_color(donor)
    print('WINGS_EXTRACTED',len(donor.data.vertices),flush=True)

def make_tail():
    # One continuous tapered serpent tail; no separate snake head or horsehair tassel.
    pts=[(0,.305,.59,.055),(0,.385,.59,.048),(.018,.48,.555,.043),(.075,.585,.475,.035),(.16,.67,.39,.027),(.245,.70,.31,.021),(.31,.69,.29,.014),(.355,.65,.315,.007),(.365,.615,.35,.0012)]
    # Catmull-Rom spline, with interpolated tube radius.
    centers=[]
    for i in range(len(pts)-1):
        p0=Vector(pts[max(0,i-1)]);p1=Vector(pts[i]);p2=Vector(pts[i+1]);p3=Vector(pts[min(len(pts)-1,i+2)])
        for j in range(12):
            t=j/12;centers.append(.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t))
    centers.append(Vector(pts[-1]));vertices=[];faces=[];N=48
    global TAIL_FRAMES
    TAIL_FRAMES=[];arc=0;rows=0
    for i,c in enumerate(centers):
        a=Vector(c[:3]);tangent=Vector(centers[min(i+1,len(centers)-1)][:3])-Vector(centers[max(i-1,0)][:3]);tangent.normalize()
        u=tangent.cross(Vector((1,0,0))).normalized();v=tangent.cross(u).normalized()
        step=max(.005,c[3]*.31)
        if i:
            ds=(a-Vector(centers[i-1][:3])).length;arc+=ds;rows+=ds/step
        TAIL_FRAMES.append((a.copy(),tangent.copy(),u.copy(),v.copy(),c[3],arc,rows,step))
        for j in range(N):
            ang=j*math.tau/N;vertices.append(a+(u*math.cos(ang)+v*math.sin(ang))*c[3])
    for i in range(len(centers)-1):
        for j in range(N):faces.append((i*N+j,i*N+(j+1)%N,(i+1)*N+(j+1)%N,(i+1)*N+j))
    faces += [tuple(reversed(range(N))),tuple((len(centers)-1)*N+j for j in range(N))]
    me=bpy.data.meshes.new('Single_serpent_tail');me.from_pydata(vertices,[],faces);me.update();tail=bpy.data.objects.new('Single_serpent_tail',me);bpy.context.scene.collection.objects.link(tail)
    attr=me.color_attributes.new(name='NativeColor',type='FLOAT_COLOR',domain='CORNER')
    for li,loop in enumerate(me.loops):
        p=me.vertices[loop.vertex_index].co
        root=max(0,min(1,(p.y-.36)/.15));root=root*root*(3-2*root)
        # Body-colored root grades to muted grey-green scales; belly is warm ivory.
        c=Vector((.48,.26,.12)).lerp(Vector((.14,.20,.105)),root)
        t=max(0,min(1,(p.y-.4)/.3));c*=1-.12*t
        attr.data[li].color=(*c,1)
    mesh_clean(tail)
    return tail

def sculpt_tail_scales(ob):
    from mathutils.kdtree import KDTree
    tree=KDTree(len(TAIL_FRAMES))
    for i,f in enumerate(TAIL_FRAMES):tree.insert(f[0],i)
    tree.balance();shades={}
    # Staggered, elongated scale cells with individual curved shoulders/keels.
    # Adjacent rows offset half a cell, so edges never become circumferential rings.
    for vert in ob.data.vertices:
        p=vert.co
        if p.y<.415:continue
        co,index,dist=tree.find(p);a,t,u,v,r,arc,rows,step=TAIL_FRAMES[index]
        if dist>r*1.65+.004:continue
        delta=p-a;along=delta.dot(t);radial=delta-t*along
        if radial.length<.0001:continue
        theta=math.atan2(radial.dot(v),radial.dot(u));qx=theta/math.tau*16;qy=rows+along/step
        nearest=[]
        for row in range(math.floor(qy)-1,math.floor(qy)+2):
            shift=.5*(row%2);middle=round(qx-shift)
            for col in range(middle-1,middle+2):
                dx=qx-(col+shift);dy=qy-row
                nearest.append(((dx/.68)**2+(dy/.95)**2,dx,dy,row,col))
        nearest.sort();d1,dx,dy,row,col=nearest[0];d2=nearest[1][0]
        interior=smoothstep(.025,.28,d2-d1)
        growth=smoothstep(.415,.465,p.y)*(1-smoothstep(.64,.72,arc))
        keel=math.exp(-((dx/.15)**2))*max(0,1-abs(dy))
        displacement=min(.0011,r*.045)*growth*(.75*interior+.25*keel)
        vert.co+=radial.normalized()*displacement
        variation=.025*math.sin(row*1.7+col*2.3)
        shades[vert.index]=1+growth*((.72+.31*interior+variation)-1)
    attr=ob.data.color_attributes['NativeColor']
    for i,l in enumerate(ob.data.loops):
        shade=shades.get(l.vertex_index)
        if shade is not None:
            c=attr.data[i].color;attr.data[i].color=(c[0]*shade,c[1]*shade,c[2]*shade,1)
    ob.data.update()
    print('SCULPTED_STAGGERED_SCALES',len(shades),flush=True)

def color_material():
    mat=bpy.data.materials.new('Baked_native_color');mat.use_nodes=True
    nodes=mat.node_tree.nodes;p=nodes.get('Principled BSDF');p.inputs['Roughness'].default_value=.77
    col=nodes.new('ShaderNodeVertexColor');col.layer_name='NativeColor';mat.node_tree.links.new(col.outputs['Color'],p.inputs['Base Color'])
    return mat

def build():
    import shutil
    rejected=OUT+'/rejected-candidate-01'
    if os.path.exists(ROOT+'/concept/shuhu/view_34.png') and not os.path.exists(rejected):
        os.makedirs(rejected)
        for view in ['34','side','front','back']:
            shutil.copy2(ROOT+'/concept/shuhu/view_'+view+'.png',rejected+'/view_'+view+'.png')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body=load(BASE,'Native_human_faced_horse');cleanup_body(body)
    donor=load(DONOR,'Native_feathered_wings');extract_wings(donor)
    tail=make_tail()
    # The broad native wing bases now intersect the thorax directly.
    # There are no spherical joint/transition meshes.
    parts=[body,donor,tail]
    bpy.ops.object.select_all(action='DESELECT')
    for ob in parts:ob.select_set(True)
    bpy.context.view_layer.objects.active=body;bpy.ops.object.join();source=body;source.name='Preunion_color_source'
    # A whole-volume union removes internal donor/body boundaries. No neck graft.
    unified=source.copy();unified.data=source.data.copy();bpy.context.scene.collection.objects.link(unified);unified.name='Shuhu_reference_unified'
    remesh=unified.modifiers.new('Whole anatomical volume union','REMESH');remesh.mode='VOXEL';remesh.voxel_size=.0018;remesh.use_smooth_shade=True;apply(unified,remesh)
    # Very light relaxation removes voxel steps without rounding away human features.
    smooth=unified.modifiers.new('Organic surface relaxation','SMOOTH');smooth.factor=.38;smooth.iterations=3;apply(unified,smooth)
    seam=unified.vertex_groups.new(name='Lower_belly_local_blend')
    for vertex in unified.data.vertices:
        p=vertex.co
        weight=(1-smoothstep(.055,.095,abs(p.z-.43)))*(1-smoothstep(.14,.18,abs(p.x)))
        if -.4<p.y<.345 and weight>.001:seam.add([vertex.index],weight,'REPLACE')
    smooth=unified.modifiers.new('Local leg belly seam relaxation','SMOOTH');smooth.vertex_group=seam.name;smooth.factor=.7;smooth.iterations=36;apply(unified,smooth)
    # Discard only disconnected remesh islands left by the removed tail cap.
    # Main body, four legs, both wings and snake tail remain one connected component.
    activate(unified)
    seed=min(unified.data.vertices,key=lambda v:(v.co-Vector((.14,0,.55))).length_squared).index
    bpy.context.tool_settings.mesh_select_mode=(True,False,False)
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='DESELECT')
    bm=bmesh.from_edit_mesh(unified.data);bm.verts.ensure_lookup_table();bm.verts[seed].select_set(True);bmesh.update_edit_mesh(unified.data)
    bpy.ops.mesh.select_linked(delimit=set());bpy.ops.mesh.select_all(action='INVERT');bpy.ops.mesh.delete(type='VERT');bpy.ops.object.mode_set(mode='OBJECT')
    # Recover full native colors from the untouched dense source surface.
    if not unified.data.color_attributes.get('NativeColor'):unified.data.color_attributes.new(name='NativeColor',type='FLOAT_COLOR',domain='CORNER')
    transfer=unified.modifiers.new('Native color bake to union','DATA_TRANSFER');transfer.object=source;transfer.use_loop_data=True;transfer.data_types_loops={'COLOR_CORNER'};transfer.loop_mapping='POLYINTERP_NEAREST';apply(unified,transfer)
    sculpt_tail_scales(unified)
    unified.data.materials.clear();unified.data.materials.append(color_material())
    for p in unified.data.polygons:p.use_smooth=True;p.material_index=0
    source.hide_render=True;source.hide_set(True)
    for ob in list(bpy.context.scene.objects):
        if ob.type not in ['MESH']:bpy.data.objects.remove(ob,do_unlink=True)
    activate(unified)
    concept=ROOT+'/concept/shuhu';os.makedirs(concept,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=OUT+'/shuhu-native-unified-reference.glb',use_selection=True,export_format='GLB',export_normals=True,export_vertex_color='NAME',export_vertex_color_name='NativeColor',export_materials='EXPORT')
    setup(1200)
    bpy.ops.wm.save_as_mainfile(filepath=OUT+'/shuhu-native-unified-reference.blend')
    render(unified,concept+'/view',size=1200)
    render(unified,OUT+'/check',views=[('other_side',(-1,0,0))],size=1000)
    for label,target,direction,scale in [('tail_detail',(.17,.57,.44),(1,2,.45),.63),('shoulder_detail',(0,-.12,.61),(1,-2,.65),.69)]:
        cam=bpy.data.objects.new(label,bpy.data.cameras.new(label));bpy.context.scene.collection.objects.link(cam);cam.data.type='ORTHO';cam.data.ortho_scale=scale
        cam.location=Vector(target)+Vector(direction).normalized()*3;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
        bpy.context.scene.camera=cam;bpy.context.view_layer.update();bpy.context.scene.render.filepath=OUT+'/check_'+label+'.png';bpy.ops.render.render(write_still=True)
    print('UNIFIED_RESULT',len(unified.data.vertices),len(unified.data.polygons),flush=True)

if __name__=='__main__':
    if '--inspect' in sys.argv:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        body=load(BASE,'v4');clusters(body,.08)
        donor=load(DONOR,'v12');clusters(donor,.08)
        setup();body.hide_render=True;render(donor,OUT+'/donor')
    else:build()
