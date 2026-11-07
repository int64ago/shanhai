"""Yingzhao: offline verified HIGH striped horse, human head and bird wings.
No generation. Source specifies horse body/human face/tiger pattern/bird wings;
two wings, single horse tail, colors, hair and grounded display are inferences.
Inputs are normalized lushu-body-max, luwu-head-max, qiongqi-wing-max HIGHs.
"""
import argparse,math,sys
from pathlib import Path
import bpy,bmesh
import numpy as np
from mathutils import Matrix,Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from turnaround import setup_render,render_views
from prepare_ershu import material,curve,ellipsoid

WING_ROOTS={side:Vector((side*.105,-.09,.715)) for side in (-1,1)}
FEET={'front_l':Vector((.1154,-.1886,0)),'front_r':Vector((-.1132,-.1625,0)),
      'back_l':Vector((.1118,.3396,0)),'back_r':Vector((-.1143,.4325,0))}


def load(path,name):
    before=set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes=[o for o in bpy.context.scene.objects if o not in before and o.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:o.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    if len(meshes)>1:bpy.ops.object.join()
    o=meshes[0]
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    o.name=name
    o.data.name=name
    return o


def finish_trim(obj,predicate,cap):
    bm=bmesh.new();bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-5)
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if predicate(v.co)],context='VERTS')
    obj.data.materials.append(cap)
    faces=bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)['faces']
    for f in faces:f.material_index=len(obj.data.materials)-1
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
    print('RETAINED',obj.name,sum(len(p.vertices)-2 for p in obj.data.polygons))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('body');p.add_argument('head');p.add_argument('wing');p.add_argument('output');p.add_argument('views')
    p.add_argument('--view',choices=['34','side','front','back','left']);p.add_argument('--render-only',action='store_true')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);bpy.ops.wm.read_factory_settings(use_empty=True)
    if a.render_only:
        bpy.ops.import_scene.gltf(filepath=a.output)
        body=bpy.data.objects['yingzhao_horse_body']
    else:
        head=load(a.head,'yingzhao_human_head')
        # Match the actual retained HIGH neck's sRGB skin, not a separately
        # guessed linear material color (which produced a pale collar).
        bsdf=head.data.materials[0].node_tree.nodes.get('Principled BSDF')
        source_image=bsdf.inputs['Base Color'].links[0].from_node.image
        source_pixels=np.empty(len(source_image.pixels),dtype=np.float32)
        source_image.pixels.foreach_get(source_pixels)
        source_pixels=source_pixels.reshape(source_image.size[1],source_image.size[0],4)
        samples=[];source_uv=head.data.uv_layers.active
        for polygon in head.data.polygons:
            if not (.058<polygon.center.z<.090 and abs(polygon.center.x)<.045):continue
            for loop in polygon.loop_indices:
                uv=source_uv.data[loop].uv
                rgb=source_pixels[int(uv.y*source_image.size[1])%source_image.size[1],int(uv.x*source_image.size[0])%source_image.size[0],:3]
                if rgb[0]>rgb[1]*1.10 and rgb[1]>rgb[2]*1.05 and rgb.mean()>.2:samples.append(rgb)
        skin_rgb=np.median(samples,axis=0) if samples else np.array([.75,.55,.40])
        print('MATCHED_HIGH_NECK_SRGB',skin_rgb.tolist(),'samples',len(samples))
        skin_linear=[((c+.055)/1.055)**2.4 if c>.04045 else c/12.92 for c in skin_rgb]
        skin=material('matched HIGH neck skin',skin_linear)
        coat=material('continuous neck coat to skin',(.48,.28,.12))
        # One continuous UV-painted surface. Fade the tiger ink before the
        # upper neck reaches the human skin; no polygon-height material split.
        image=bpy.data.images.new('offline graduated neck tiger ink',width=512,height=512)
        image.colorspace_settings.name=source_image.colorspace_settings.name
        u,v=np.meshgrid(np.linspace(0,1,512),np.linspace(0,1,512))
        z=.55+.30*v
        def ease(a,b,value):
            t=np.clip((value-a)/(b-a),0,1);return t*t*(3-2*t)
        blend=ease(.695,.800,z+.005*np.sin(u*math.tau))
        stripe=(np.sin(u*math.tau*7+.65*np.sin(v*12)+.22*np.sin(v*29))>.86)*(1-ease(.68,.78,z))
        base=np.array([.82,.61,.37])*(1-blend[:,:,None])+skin_rgb*blend[:,:,None]
        pixels=np.ones((512,512,4),dtype=np.float32)
        pixels[:,:,:3]=base*(1-stripe[:,:,None])+np.array([.065,.045,.027])*stripe[:,:,None]
        image.pixels.foreach_set(pixels.ravel());image.pack()
        nodes=coat.node_tree.nodes;tex=nodes.new('ShaderNodeTexImage');tex.image=image
        coat.node_tree.links.new(tex.outputs['Color'],nodes.get('Principled BSDF').inputs['Base Color'])
        body=load(a.body,'yingzhao_horse_body')
        # Remove the entire native horse skull/ears/mane above the neck and
        # the central short tail. Four measured hoof components stay intact.
        rump_mat=material('rump repair ochre',(.64,.42,.23))
        finish_trim(body,lambda q:(q.z>.685 and q.y<.04) or (abs(q.x)<.07 and q.y>.425 and q.z>.48),rump_mat)
        for v in body.data.vertices:
            if v.co.z<.009:v.co.z=0
        # Bury the lower taper inside the horse chest. The old forward base
        # exposed a flat bottom rim, making the neck resemble a rectangular bib.
        vertices,faces=[],[]
        for i in range(33):
            t=i/32;r=.120*(1-t)+.049*t+.005*math.sin(math.pi*t)
            for j in range(48):
                angle=math.tau*j/48
                vertices.append((r*math.cos(angle),-.13-.17*t+.90*r*math.sin(angle),.55+.275*t))
        for i in range(32):
            for j in range(48):
                k=(j+1)%48;faces.append((i*48+j,i*48+k,(i+1)*48+k,(i+1)*48+j))
        faces+=[tuple(reversed(range(48))),tuple(32*48+j for j in range(48))]
        mesh=bpy.data.meshes.new('anatomical tapered neck');mesh.from_pydata(vertices,[],faces)
        mesh.materials.append(coat)
        for polygon in mesh.polygons:polygon.use_smooth=True
        mesh.update()
        neck=bpy.data.objects.new('yingzhao_neck_bridge',mesh);bpy.context.collection.objects.link(neck)
        # Rounded shoulder buries the retained cut rim. Keep the HIGH horse
        # surface unchanged; its thin hoof walls must not be voxel-remeshed.
        shoulder=ellipsoid('neck shoulder blend',(0,-.12,.66),(.14,.19,.10),coat)
        bpy.ops.object.select_all(action='DESELECT')
        for o in (neck,shoulder):o.select_set(True)
        bpy.context.view_layer.objects.active=neck;bpy.ops.object.join()
        mod=neck.modifiers.new('sculpt only new neck volumes','REMESH');mod.mode='VOXEL';mod.voxel_size=.0035;mod.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=mod.name)
        mod=neck.modifiers.new('round muscular neck','SMOOTH');mod.factor=.9;mod.iterations=14;bpy.ops.object.modifier_apply(modifier=mod.name)
        neck.data.materials.clear();neck.data.materials.append(coat)
        for layer in list(neck.data.uv_layers):neck.data.uv_layers.remove(layer)
        uv=neck.data.uv_layers.new(name=body.data.uv_layers.active.name)
        neck.data.uv_layers.active=uv;uv.active_render=True
        for polygon in neck.data.polygons:
            polygon.use_smooth=True;polygon.material_index=0
            for loop in polygon.loop_indices:
                q=neck.data.vertices[neck.data.loops[loop].vertex_index].co
                uv.data[loop].uv=(math.atan2(q.y+.24,q.x)/math.tau+.5,(q.z-.55)/.30)
        rump=ellipsoid('rounded native tail repair',(0,.417,.60),(.075,.041,.11),rump_mat)
        bpy.ops.object.select_all(action='DESELECT')
        for o in (body,neck,rump):o.select_set(True)
        bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
        print('ASSEMBLED_HORSE_TRIANGLES',sum(len(p.vertices)-2 for p in body.data.polygons))
        # The human HIGH includes a thin white shirt/base below the neck.
        # Remove it, retaining the anatomical neck down to a narrow skin ring.
        finish_trim(head,lambda q:q.z<.055 or (q.z<.08 and abs(q.x)>.05),skin)
        for v in head.data.vertices:v.co=1.12*v.co+Vector((0,-.30,.737))
        for side in (-1,1):
            wing=load(a.wing,f'yingzhao_wing_{"l" if side==1 else "r"}')
            for v in wing.data.vertices:
                x,y,z=v.co
                v.co=WING_ROOTS[side]+Vector((side*(x+.4),.17-z,y+.008))
            # Offline reflected coordinates require reversed winding, never a
            # negative object scale on an outlined runtime mesh.
            bm=bmesh.new();bm.from_mesh(wing.data)
            bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(wing.data);bm.free()
        tailmat=material('horse tail hair',(.075,.049,.03))
        curve('yingzhao_horse_tail',[(0,.405,.66),(0,.47,.61),(.015,.51,.46),(.025,.52,.26)],.026,tailmat)
        bpy.ops.object.select_all(action='DESELECT')
        for o in bpy.context.scene.objects:
            if o.type=='MESH':o.select_set(True)
        bpy.context.view_layer.objects.active=body
        Path(a.output).parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    # Preserve each component's UV layer/material ownership during concepts.
    # A bounds-only mesh drives the camera without joining textured surfaces.
    pts=[o.matrix_world@v.co for o in bpy.context.scene.objects if o.type=='MESH' for v in o.data.vertices]
    lo,hi=[Vector(tuple(fn(q[i] for q in pts) for i in range(3))) for fn in (min,max)]
    mesh=bpy.data.meshes.new('all component bounds');mesh.from_pydata([(x,y,z) for x in (lo.x,hi.x) for y in (lo.y,hi.y) for z in (lo.z,hi.z)],[],[])
    body=bpy.data.objects.new('render bounds only',mesh);bpy.context.collection.objects.link(body)
    Path(a.views).mkdir(parents=True,exist_ok=True);cam=setup_render(1024)
    if a.view=='left':
        pts=[v.co for v in body.data.vertices];lo,hi=[Vector(tuple(fn(q[i] for q in pts) for i in range(3))) for fn in (min,max)]
        center=(lo+hi)/2;extent=max(hi-lo);cam.data.ortho_scale=extent*1.15
        location=center+Vector((-extent*3,0,0));cam.matrix_world=Matrix.LocRotScale(location,(center-location).to_track_quat('-Z','Y'),Vector((1,1,1)))
        bpy.context.view_layer.update();bpy.context.scene.render.filepath=f'{a.views}/view_left.png';bpy.ops.render.render(write_still=True)
    else:render_views(body,cam,a.views,only_view=a.view)

if __name__=='__main__':main()
