"""Offline qique candidate from the locally cached, decoded Fenghuang chicken.
Input is the decoded runtime asset, SHA recorded in qique.json; no generation.
Retain feather tissue; repaint white head/brown fowl plumage, reduce the comb,
straighten the native bill, replace scaly avian shanks with fused rodent feet.
Render four textured and four neutral, outline-free views before rigging.
"""
import argparse
import math
import sys
from pathlib import Path
import bmesh
import bpy
import numpy as np
from mathutils import Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import render_views, setup_render, smoothstep


def load_donor(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    obj=max((o for o in bpy.context.scene.objects if o.type=='MESH'),key=lambda o:len(o.data.vertices))
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True)
    bpy.context.view_layer.objects.active=obj
    for mod in list(obj.modifiers):obj.modifiers.remove(mod)
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    for other in list(bpy.context.scene.objects):
        if other is not obj:bpy.data.objects.remove(other,do_unlink=True)
    obj.vertex_groups.clear()
    return obj


def paint(obj):
    # Keep feather relief/shadows, discard Fenghuang's five colours and glyphs.
    for mat in obj.data.materials:
        bsdf=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        image=bsdf.inputs['Base Color'].links[0].from_node.image
        image=image.copy();bsdf.inputs['Base Color'].links[0].from_node.image=image
        w,h=image.size;px=np.empty(w*h*4,dtype=np.float32);image.pixels.foreach_get(px)
        rgba=px.reshape(h,w,4);old=rgba.copy();uv=obj.data.uv_layers.active.data
        obj.data.calc_loop_triangles()
        for tri in obj.data.loop_triangles:
            if obj.data.materials[tri.material_index]!=mat:continue
            coords=np.array([(uv[i].uv.x*(w-1),uv[i].uv.y*(h-1)) for i in tri.loops])
            lo=np.maximum(np.floor(coords.min(axis=0)).astype(int)-1,0)
            hi=np.minimum(np.ceil(coords.max(axis=0)).astype(int)+1,[w-1,h-1])
            xx,yy=np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1));a,b,c=coords
            d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(d)<1e-8:continue
            u=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/d
            v=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/d
            pts=np.array([obj.data.vertices[i].co[:] for i in tri.vertices])
            xyz=u[...,None]*pts[0]+v[...,None]*pts[1]+(1-u-v)[...,None]*pts[2]
            x,y,z=xyz[...,0],xyz[...,1],xyz[...,2]
            src=old[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3]
            lum=src@np.array([.2126,.7152,.0722]);shade=np.clip(.68+lum*.70,.68,1.30)[...,None]
            colour=np.array([.39,.245,.125])*shade
            head=(np.clip((z-.705)/.075,0,1)*np.clip((-.16-y)/.055,0,1))[...,None]
            white=np.array([.89,.87,.81])*(.88+.12*np.clip(lum*2,0,1))[...,None]
            colour=colour*(1-head)+white*head
            # The native eyes are small dark tissue; preserve only that orbit.
            # Native chicken looks obliquely left; locate both actual globes,
            # rather than assuming the head shares the body's forward axis.
            eye_radius=np.minimum(((x-.003)/.015)**2+((y+.370)/.015)**2+((z-.849)/.014)**2,
                                  ((x+.082)/.015)**2+((y+.315)/.015)**2+((z-.850)/.014)**2)
            eye=eye_radius<1
            colour[eye]=np.array([.20,.105,.038])
            colour[eye&(eye_radius<.45)]=np.array([.025,.018,.012])
            axial=-(x+.035)*.77-(y+.365)*.64;lateral=(x+.035)*.64-(y+.365)*.77
            bill=(axial>.025)&(abs(lateral)<.034)&(z>.795)&(z<.860)
            colour[bill]=(np.array([.56,.39,.18])*shade)[bill]
            mask=(u>=-.02)&(v>=-.02)&(u+v<=1.02)
            dst=rgba[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3];dst[mask]=np.clip(colour,0,1)[mask]
        image.pixels.foreach_set(rgba.ravel());image.update();image.pack()
        mat.name='qique_body' if mat==obj.data.materials[0] else 'qique_flight'


def material(name,colour):
    image=bpy.data.images.new(name,width=256,height=256)
    u,v=np.meshgrid(np.linspace(0,1,256),np.linspace(0,1,256))
    grain=.025*np.sin(u*193+np.sin(v*71))*np.sin(v*137+u*47)
    pixels=np.ones((256,256,4),dtype=np.float32);pixels[:,:,:3]=np.array(colour)*(1+grain[...,None])
    image.pixels.foreach_set(pixels.ravel());image.pack()
    mat=bpy.data.materials.new(name);mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF');tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color']);bsdf.inputs['Roughness'].default_value=.78
    return mat


def tube(name,centers,radii,mat,flatten=1):
    sides=20;verts=[];faces=[]
    for i,p in enumerate(centers):
        tangent=(centers[min(i+1,len(centers)-1)]-centers[max(0,i-1)]).normalized()
        lateral=Vector((1,0,0))
        if abs(tangent.dot(lateral))>.95:lateral=Vector((0,1,0))
        a=tangent.cross(lateral).normalized();b=tangent.cross(a).normalized()
        for j in range(sides):
            theta=j/sides*math.tau;verts.append(p+radii[i]*(a*math.cos(theta)*flatten+b*math.sin(theta)))
    for i in range(len(centers)-1):
        for j in range(sides):faces.append((i*sides+j,i*sides+(j+1)%sides,(i+1)*sides+(j+1)%sides,(i+1)*sides+j))
    faces.extend([tuple(range(sides-1,-1,-1)),tuple((len(centers)-1)*sides+j for j in range(sides))])
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);mesh.materials.append(mat)
    uv=mesh.uv_layers.new()
    for face in mesh.polygons:
        face.use_smooth=True
        for loop in face.loop_indices:
            i=mesh.loops[loop].vertex_index;uv.data[loop].uv=(i//sides/(len(centers)-1),i%sides/sides)
    return obj


def join(parts,active):
    bpy.ops.object.select_all(action='DESELECT')
    for p in parts:p.select_set(True)
    bpy.context.view_layer.objects.active=active;bpy.ops.object.join();return active


def feet():
    skin=material('qique_skin',(.64,.435,.355));claw=material('qique_claw',(.60,.49,.32));parts=[]
    for sign in [1,-1]:
        x=sign*.101;skinparts=[];claws=[]
        # Hock narrows into the Achilles, then broadens gradually into the heel.
        nodes=[(x,-.100,.235,.034),(x,-.111,.188,.026),(x,-.122,.136,.020),
               (x,-.137,.088,.020),(x,-.159,.049,.023),(x,-.187,.028,.027),
               (x,-.209,.024,.034),(x,-.228,.020,.024),(x,-.239,.018,.002)]
        centers=[];radii=[]
        # Cubic tissue path: Achilles rounds into the heel and dorsal arch.
        for j in range(len(nodes)-1):
            p0=Vector(nodes[max(0,j-1)]);p1=Vector(nodes[j]);p2=Vector(nodes[j+1]);p3=Vector(nodes[min(len(nodes)-1,j+2)])
            for i in range(12):
                t=i/12;q=.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t)
                centers.append(Vector(q[:3]));radii.append(q[3])
        centers.append(Vector(nodes[-1][:3]));radii.append(nodes[-1][3])
        skinparts.append(tube('ankle_dorsum',centers,radii,skin,.62))
        # Five long fine digits, distinct from the thick-root hooked keratin.
        for digit,length in enumerate([.058,.106,.132,.117,.086]):
            spread=(digit-2)*.019
            root_y=[-.202,-.218,-.226,-.222,-.210][digit]
            start=Vector((x+spread*.76,root_y,.023));end=Vector((x+spread*1.90,root_y-length,.010))
            centers=[];radii=[]
            for i in range(41):
                t=i/40;p=start.lerp(end,t)
                p.x+=spread*.20*math.sin(math.pi*t);p.z+=.006*math.sin(math.pi*t)**2
                # Broad proximal tendon merges into a slender terminal phalanx.
                radius=.0062+.0055*(1-smoothstep(0,.40,t))+.0007*math.exp(-((t-.52)/.10)**2)
                radius-=.0005*math.exp(-((t-.63)/.025)**2)
                centers.append(p);radii.append(radius)
            skinparts.append(tube('digit',centers,radii,skin,.92))
            direction=end-start;direction.z=0;direction.normalize();centers=[];radii=[]
            for i in range(41):
                t=i/40;p=end+direction*(.052*t)
                # Continuous distal sheath, then a long swept taper. Root
                # diameter matches the terminal phalanx, with no bulb/ball.
                p.z=end.z+.085*t*t-.091*t*t*t
                centers.append(p);radii.append(.0068*(1-t)**.85+.0002)
            claws.append(tube('tiger_claw',centers,radii,claw,.86))
        paw=join(skinparts,skinparts[0]);paw.name='rodent_foot_'+str(sign)
        # A single remeshed surface removes every primitive intersection/joint.
        mod=paw.modifiers.new('continuous_tissue','REMESH');mod.mode='VOXEL';mod.voxel_size=.0018;mod.use_smooth_shade=True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        mod=paw.modifiers.new('relax_junctions','SMOOTH');mod.factor=.65;mod.iterations=5;bpy.ops.object.modifier_apply(modifier=mod.name)
        for v in paw.data.vertices:
            p=v.co
            # Raised extensor flow across the instep, continuous with its skin.
            if p.z>.027 and -.225<p.y<-.145:
                u=max(0,min(1,(-p.y-.145)/.080))
                dorsal=smoothstep(.025,.041,p.z)*(math.sin(math.pi*u)**2)
                ridge=sum(math.exp(-((p.x-x-spread*u)/.0030)**2) for spread in [-.018,0,.018])
                p.z+=.0024*dorsal*ridge
            # Fine anterior hock folds alter one surface, not separate rings.
            if .065<p.z<.16 and p.y<-.110:
                envelope=math.sin(math.pi*(p.z-.065)/.095)**2
                p.y+=.0008*envelope*math.cos(p.z*610+(p.x-x)*18)
            p.z=max(.003,p.z)
        # Remeshing creates new geometry/normals, without modifying donor normals.
        bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.uv.smart_project(island_margin=.02);bpy.ops.object.mode_set(mode='OBJECT')
        for poly in paw.data.polygons:poly.use_smooth=True
        parts.extend([paw,*claws])
    return parts


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('output');p.add_argument('views');a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    obj=load_donor(a.input);obj.name='qique_candidate';obj.data.calc_loop_triangles()
    print('DONOR_TRIANGLES',len(obj.data.loop_triangles))
    print('DONOR_MATERIAL_TRIANGLES',{m.name:sum(1 for t in obj.data.loop_triangles if t.material_index==i) for i,m in enumerate(obj.data.materials)})
    paint(obj)
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.co.z<.185],context='VERTS');bm.to_mesh(obj.data);bm.free()
    normals=[n.vector.copy() for n in obj.data.corner_normals]
    jacobians=[];forward=Vector((-.77,-.64,0));displacement=Vector((-.012*.77,-.012*.64,.010))
    for v in obj.data.vertices:
        p=v.co;zz=1;derivative=0
        # Small white low comb is an explicit design inference; keep native head.
        if p.z>.873:p.z=.873+(p.z-.873)*.24;zz=.24
        axial=-(p.x+.035)*.77-(p.y+.365)*.64;lateral=(p.x+.035)*.64-(p.y+.365)*.77
        if axial>.025 and abs(lateral)<.034 and .795<p.z<.860:
            u=max(0,min(1,(axial-.025)/.085));t=u*u*(3-2*u);derivative=6*u*(1-u)/.085
            p+=displacement*t
        jacobians.append((zz,derivative))
    # Guarded inverse transpose of I + displacement * grad(t)^T.
    for loop,n in zip(obj.data.loops,normals):
        zz,derivative=jacobians[loop.vertex_index];n.z/=zz
        gradient=forward*derivative;n-=gradient*(displacement.dot(n)/max(1e-8,1+gradient.dot(displacement)))
        if n.length>1e-8:n.normalize()
        else:n[:]=(0,0,1)
    obj.data.normals_split_custom_set(normals);obj.data.update()
    parts=feet();obj=join([obj,*parts],obj)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    root=Path(a.views);(root/'textured').mkdir(parents=True,exist_ok=True);(root/'gray').mkdir(parents=True,exist_ok=True)
    cam=setup_render(1024)
    bpy.context.scene.world.node_tree.nodes['Background'].inputs[1].default_value=.35
    render_views(obj,cam,str(root/'textured'))
    def detail(folder):
        camera=cam.copy();camera.data=cam.data.copy();bpy.context.collection.objects.link(camera)
        camera.location=(.62,-.85,.43);target=Vector((.02,-.21,.09))
        camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.ortho_scale=.55
        bpy.context.scene.camera=camera;bpy.context.scene.render.filepath=str(folder/'feet_detail.png');bpy.ops.render.render(write_still=True)
        side=camera.copy();side.data=camera.data.copy();bpy.context.collection.objects.link(side)
        side.location=(.90,-.21,.13);side.rotation_euler=(Vector((.10,-.22,.11))-side.location).to_track_quat('-Z','Y').to_euler();side.data.ortho_scale=.46
        bpy.context.scene.camera=side;bpy.context.scene.render.filepath=str(folder/'feet_side.png');bpy.ops.render.render(write_still=True)
    detail(root/'textured')
    gray=bpy.data.materials.new('neutral_sculpt');gray.use_nodes=True
    gray.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(.28,.28,.28,1)
    for i in range(len(obj.data.materials)):obj.data.materials[i]=gray
    render_views(obj,cam,str(root/'gray'));detail(root/'gray')
    obj.data.calc_loop_triangles();print('CANDIDATE_TRIANGLES',len(obj.data.loop_triangles))


if __name__=='__main__':main()
