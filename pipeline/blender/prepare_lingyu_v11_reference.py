"""Historical v11 reference sculpt, retained for production provenance.
No API calls. Source and output paths are relative to this repository root.
The v12 reference lives in prepare_lingyu_local_anatomy.py.
"""
import bpy,bmesh,math,json,numpy as np
from pathlib import Path
from mathutils import Vector
from mathutils.kdtree import KDTree
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'raw/_build/lingyu-local-anatomy-v11';OUT.mkdir(parents=True,exist_ok=True)
SRC=ROOT/'raw/lingyu-production-20261115-native-face-hands-feet-v10-medium/base_basic_pbr.glb'
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(SRC))
native=next(o for o in bpy.context.scene.objects if o.type=='MESH')
bpy.context.view_layer.objects.active=native;native.select_set(True)
bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
pieces=[]
def extract_native(name,ycut,keep_front):
 bm=bmesh.new();bm.from_mesh(native.data);bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.00002)
 bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=(0,ycut,0),plane_no=(0,1,0),clear_outer=keep_front,clear_inner=not keep_front)
 if keep_front:
  bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=(0,0,.37),plane_no=(0,0,1),clear_outer=True,clear_inner=False)
 bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
 bmesh.ops.triangulate(bm,faces=[f for f in bm.faces if len(f.verts)>4]);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
 me=bpy.data.meshes.new(name);bm.to_mesh(me);bm.free();o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);pieces.append(o);return o
extract_native('Retained_single_human_face',-.675,True)
extract_native('Retained_native_forked_tail',.66,False)
bpy.data.objects.remove(native,do_unlink=True)
profile=np.array([[-.835,.004,.005,.065,.145],[-.78,.11,.13,.055,.145],[-.67,.17,.205,.035,.15],[-.5,.205,.245,.02,.14],[-.28,.235,.288,.005,.13],[-.05,.228,.30,0,.13],[.15,.19,.255,-.012,.14],[.35,.123,.175,-.025,.15],[.55,.064,.10,-.033,.15],[.70,.035,.07,-.037,.15],[.735,.002,.003,-.037,.15]])
def prof(y,k):
 i=max(0,min(len(profile)-2,int(np.searchsorted(profile[:,0],y))-1));a,b=profile[i],profile[i+1];h=b[0]-a[0];t=(y-a[0])/h
 i0=max(0,i-1);i1=min(len(profile)-1,i+2)
 m0=(b[k]-profile[i0,k])/(b[0]-profile[i0,0]);m1=(profile[i1,k]-a[k])/(profile[i1,0]-a[0])
 return (2*t**3-3*t*t+1)*a[k]+(t**3-2*t*t+t)*h*m0+(-2*t**3+3*t*t)*b[k]+(t**3-t*t)*h*m1
vs=[];fs=[];nr=600;na=192
for j,y in enumerate(np.linspace(profile[0,0],profile[-1,0],nr)):
 rx,rz,cx,cz=[prof(y,k) for k in range(1,5)]
 for i in range(na):
  th=2*math.pi*i/na;row=math.floor((y+.835)/.033);v=((y+.835)/.033)%1;u=(th/(2*math.pi)*38+.5*(row%2))%1
  relief=.0025*math.sin(math.pi*u)**2*math.sin(math.pi*v)**.7 if -.65<y<.57 else 0
  vs.append((cx+(rx+relief)*math.cos(th),y,cz+(rz+relief)*math.sin(th)))
  if j:
   a=(j-1)*na+i;b=(j-1)*na+(i+1)%na;c=j*na+(i+1)%na;d=j*na+i;fs.append((a,b,c,d))
fs.append(tuple(reversed(range(na))));fs.append(tuple((nr-1)*na+i for i in range(na)))
me=bpy.data.meshes.new('Sculpted_spindle_fish_core');me.from_pydata(vs,[],fs);me.update();body=bpy.data.objects.new('Sculpted_spindle_fish_core',me);bpy.context.scene.collection.objects.link(body);pieces.append(body)
outline=[(-.24,.423),(-.08,.60),(.19,.407),(.19,.365),(-.24,.405)]
fv=[(x,y,z) for x in (-.008,.008) for y,z in outline];nf=len(outline);ff=[tuple(reversed(range(nf))),tuple(range(nf,2*nf))]
for i in range(nf):ff.append((i,(i+1)%nf,(i+1)%nf+nf,i+nf))
fm=bpy.data.meshes.new('Small_dorsal_fin');fm.from_pydata(fv,[],ff);fo=bpy.data.objects.new('Small_dorsal_fin',fm);bpy.context.scene.collection.objects.link(fo);pieces.append(fo)
bpy.ops.object.select_all(action='DESELECT')
for o in pieces:o.select_set(True)
bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
bm=bmesh.new();bm.from_mesh(body.data);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(body.data);bm.free()
body.name='Lingyu_reconstructed_fish_single_native_face_tail'
vg=body.vertex_groups.new(name='Local_face_transition')
for v in body.data.vertices:
 w=math.exp(-((v.co.y+.61)/.055)**2)
 if w>.002:vg.add([v.index],w,'REPLACE')
mod=body.modifiers.new('Soften_native_face_ring','SMOOTH');mod.factor=1.4;mod.iterations=22;mod.vertex_group=vg.name;bpy.ops.object.modifier_apply(modifier=mod.name)
def mat(name,color,rough=.58):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;p.inputs['Metallic'].default_value=0
 return m
skin=mat('Inferred_warm_ochre_skin',(.53,.31,.19));fish=mat('Inferred_pale_blue_gray_fish',(.23,.38,.43))
body.data.materials.clear();body.data.materials.append(fish)
parts=[]
def ell(name,center,radii,material=skin):
 bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=16,location=center)
 o=bpy.context.object;o.name=name;o.scale=radii;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(material);parts.append(o);return o
def seg(name,a,b,r1):
 a,b=Vector(a),Vector(b);o=ell(name,(a+b)/2,(r1,r1,(b-a).length/2+r1*.55));o.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler();return o
TOES=[(-.043,-.041,.018),(-.017,-.033,.014),(.009,-.019,.013),(.032,-.003,.0115),(.05,.015,.01)]
for s in (-1,1):
 def p(x,y,z):return(s*x,y,z)
 ell('Shoulder_gill_transition',p(.18,-.435,.145),(.075,.095,.09))
 seg('Upper_arm',p(.215,-.435,.14),p(.33,-.405,-.005),.059)
 ell('Elbow',p(.33,-.405,-.01),(.052,.053,.055))
 seg('Forearm',p(.33,-.405,-.005),p(.362,-.47,-.15),.045)
 ell('Wrist',p(.362,-.47,-.146),(.033,.033,.045))
 ell('Human_palm',p(.365,-.477,-.202),(.051,.028,.065))
 for i,(dx,length) in enumerate([(-.038,.067),(-.013,.083),(.013,.079),(.037,.062)]):
  seg('Hand_finger_'+str(i+1),p(.365+dx,-.48,-.236),p(.365+dx*1.2,-.494,-.236-length),.012)
 seg('Hand_thumb',p(.323,-.482,-.185),p(.295,-.515,-.23),.017)
 ell('Rear_belly_hip',p(.105,.11,-.12),(.075,.095,.095))
 seg('Short_thigh',p(.105,.12,-.12),p(.145,.19,-.27),.066)
 ell('Knee',p(.145,.19,-.27),(.053,.058,.056))
 seg('Short_calf',p(.145,.19,-.27),p(.145,.18,-.41),.047)
 ell('Ankle',p(.145,.18,-.412),(.035,.037,.052))
 ell('Human_heel',p(.145,.195,-.463),(.044,.052,.041))
 ell('Human_instep',p(.145,.13,-.430),(.038,.073,.035))
 ell('Human_forefoot',p(.145,.067,-.467),(.06,.064,.028))
 for i,(dx,tip,r) in enumerate(TOES):seg('Foot_short_toe_'+str(i+1),p(.145+dx,.045,-.47),p(.145+dx,tip,-.468),r)
bpy.ops.object.select_all(action='DESELECT')
for o in parts:o.select_set(True)
bpy.context.view_layer.objects.active=parts[0];bpy.ops.object.join();limbs=bpy.context.object;limbs.name='Sculpted_human_hands_and_feet'
rem=limbs.modifiers.new('Local_limb_volume_fusion','REMESH');rem.mode='VOXEL';rem.voxel_size=.003;rem.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=rem.name)
sm=limbs.modifiers.new('Anatomical_surface_relax','SMOOTH');sm.factor=.8;sm.iterations=14;bpy.ops.object.modifier_apply(modifier=sm.name)
bpy.context.view_layer.update()
def surface_tree(o):
 k=KDTree(len(o.data.vertices))
 for i,v in enumerate(o.data.vertices):k.insert(o.matrix_world@v.co,i)
 k.balance();return k
bodytree=surface_tree(body);limbtree=surface_tree(limbs)
collar=ell('Buried_local_face_transition',(.035,-.66,.151),(.15,.07,.18),fish)
bpy.ops.object.select_all(action='DESELECT')
for o in (body,limbs,collar):o.select_set(True)
bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
r=body.modifiers.new('Local_anatomical_volume_union','REMESH');r.mode='VOXEL';r.voxel_size=.0026;r.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=r.name)
weights=body.vertex_groups.new(name='Junction_relax_only')
for v in body.data.vertices:
 x,y,z=v.co;w=math.exp(-((y+.625)/.07)**2)
 for s in (-1,1):w=max(w,math.exp(-(((x-s*.22)/.12)**2+((y+.435)/.14)**2+((z-.145)/.14)**2)),math.exp(-(((x-s*.105)/.10)**2+((y-.11)/.13)**2+((z+.12)/.13)**2)))
 if w>.004:weights.add([v.index],min(1,w),'REPLACE')
sm=body.modifiers.new('Soft_natural_junctions','SMOOTH');sm.factor=1;sm.iterations=28;sm.vertex_group=weights.name;bpy.ops.object.modifier_apply(modifier=sm.name)
body.data.materials.clear();body.data.materials.append(fish)
for a in list(body.data.color_attributes):body.data.color_attributes.remove(a)
attr=body.data.color_attributes.new(name='InferredColor',type='FLOAT_COLOR',domain='POINT')
for v,c in zip(body.data.vertices,attr.data):
 x,y,z=v.co;db=bodytree.find(v.co)[2];dl=limbtree.find(v.co)[2]
 t=max(0,min(1,(db-dl+.028)/.056));t=t*t*(3-2*t)
 f=max(0,min(1,(-y-.55)/.19));f=f*f*(3-2*f);t=max(t,f)
 pale=max(0,min(.16,(.06-z)*.55));color=np.array((.23+pale,.38+pale,.43+pale))*(1-t)+np.array((.53,.31,.19))*t;c.color=(*color,1)
n=fish.node_tree.nodes.new('ShaderNodeVertexColor');n.layer_name=attr.name;fish.node_tree.links.new(n.outputs['Color'],fish.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
nail=mat('Natural_warm_nails',(.65,.46,.34),.46)
for s in (-1,1):
 for i,(dx,tip,r) in enumerate(TOES):ell('Foot_nail_'+str(i+1),(s*(.145+dx),tip+.012,-.468+r*.9),(r*.62,r*.7,.0018),nail)
for o in bpy.context.scene.objects:
 if o.type=='MESH':
  for p in o.data.polygons:p.use_smooth=True
bpy.ops.object.select_all(action='DESELECT')
for o in bpy.context.scene.objects:
 if o.type=='MESH':o.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT/'lingyu-static-corrected.glb'),export_format='GLB',use_selection=True,export_attributes=True)
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=32;scene.cycles.use_denoising=True
scene.render.resolution_x=scene.render.resolution_y=1024;scene.render.resolution_percentage=100;scene.view_settings.view_transform='AgX'
world=bpy.data.worlds.new('Neutral_reference');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.78,.80,.80,1);world.node_tree.nodes['Background'].inputs[1].default_value=.65;scene.world=world
for name,loc,energy,size in [('Key',(2,-3,4),350,4),('Fill',(-3,-1,2),260,4),('Rim',(0,3,3),300,3)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=energy;d.shape='DISK';d.size=size;o=bpy.data.objects.new(name,d);scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,0))-o.location).to_track_quat('-Z','Y').to_euler()
for name,offset in [('34',(2.4,-3.2,1.4)),('side',(4,0,0)),('front',(0,-4,0)),('back',(0,4,0)),('feet',(2,-3,1)),('foot_side',(3,0,-.04)),('feet_sole',(1,-2,-3))]:
 d=bpy.data.cameras.new(name);d.type='ORTHO'
 d.ortho_scale={'front':1.36,'back':1.36,'feet':.58,'foot_side':.45,'feet_sole':.48}.get(name,2.22)
 t=Vector((0,0,.015)) if name not in ('feet','foot_side','feet_sole') else (Vector((0,.06,-.435)) if name=='feet' else Vector((0,.09,-.453)))
 o=bpy.data.objects.new(name,d);scene.collection.objects.link(o);o.location=t+Vector(offset);o.rotation_euler=(t-o.location).to_track_quat('-Z','Y').to_euler();scene.camera=o
 scene.render.filepath=str(OUT/((name if name in ('foot_side','feet_sole') else 'view_'+name)+'.png'));bpy.ops.render.render(write_still=True)
bpy.context.preferences.filepaths.save_version=0;bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'lingyu-static-corrected.blend'))
json.dump({'status':'STATIC_REFERENCE_RECOVERED_PENDING_READ_AND_PARENT_HIGH_APPROVAL','source':str(SRC),'source_sha256':'8400ba059797f8c0bdc14da2606070f30fa7045fa34f784397829cfbe6620db8','route':'RECONSTRUCTED_STATIC_GENERATION_REFERENCE_NATIVE_FACE_AND_TAIL','native_face_count':1,'whole_body_mirror':False,'api_calls':0,'runtime_ready':False,'main_vertices':len(body.data.vertices),'color_basis':'content/beasts/lingyu.json inferred[2]','recovery':'Original automatic worktree deleted after handback; rebuilt here from authored geometry code in current conversation; this manual worktree is git-worktree locked.'},open(OUT/'manifest.json','w'),indent=2)
print('RECOVERED_OUTPUT',OUT,'MAIN_VERTICES',len(body.data.vertices))
