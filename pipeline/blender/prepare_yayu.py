"""Yayu, North Mountains' first itinerary only: ox form, red body, human face,
horse feet. Offline derivatives of verified HIGH zhuhuai/luwu/lushu components.
New neck/pastern/tail sculpt and red paint are explicitly not a new HIGH output.
"""
import argparse, math, sys
from pathlib import Path
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_yingzhao import load, finish_trim
from prepare_ershu import material, ellipsoid, curve
from turnaround import setup_render, render_views

FEET = {f'{end}_{side}': Vector((sign*.105, -.14 if end=='front' else .38, 0))
        for end in ('front','back') for side,sign in [('l',1),('r',-1)]}
HORSE_FEET = {'front_l':Vector((.1154,-.1886,0)), 'front_r':Vector((-.1132,-.1625,0)),
              'back_l':Vector((.1118,.3396,0)), 'back_r':Vector((-.1143,.4325,0))}
RED = (.72, .20, .115)


def paint_face(obj):
    for mat in obj.data.materials:
        bsdf = mat.node_tree.nodes.get('Principled BSDF') if mat.use_nodes else None
        if not bsdf or not bsdf.inputs['Base Color'].is_linked: continue
        tex = bsdf.inputs['Base Color'].links[0].from_node
        if tex.type != 'TEX_IMAGE': continue
        image = tex.image.copy(); tex.image = image
        pixels = np.empty(len(image.pixels), dtype=np.float32); image.pixels.foreach_get(pixels)
        rgba = pixels.reshape(-1,4); rgb = rgba[:,:3].copy()
        lum = rgb @ np.array([.2126,.7152,.0722])
        # Keep dark hair/beard, lips and bright eye whites; paint skin only.
        skin = (rgb[:,0] > rgb[:,1]*1.14) & (rgb[:,1] > rgb[:,2]*1.03) & (lum > .18)
        rgba[skin,:3] = (.76 + .24*lum[skin,None]) * np.array(RED)
        rgba[:,3] = 1
        for link in list(bsdf.inputs['Alpha'].links): mat.node_tree.links.remove(link)
        bsdf.inputs['Alpha'].default_value = 1
        image.pixels.foreach_set(pixels); image.update(); image.pack()


def join(objects, active):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects: o.select_set(True)
    bpy.context.view_layer.objects.active=active; bpy.ops.object.join()
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('body','head','horse','output','views'): p.add_argument(arg)
    p.add_argument('--view',choices=['34','side','front','back','left'])
    p.add_argument('--render-only',action='store_true')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]); bpy.ops.wm.read_factory_settings(use_empty=True)
    if a.render_only:
        bpy.ops.import_scene.gltf(filepath=a.output); body=bpy.data.objects['yayu_ox_body']
    else:
        red=material('new offline cinnabar neck and pasterns',(.38,.027,.010))
        body=load(a.body,'yayu_ox_body')
        # Remove all bovine face/ears, four native split hooves, and native tail.
        finish_trim(body,lambda q:(q.y<-.265 and q.z>.28) or q.z<.12 or (abs(q.x)<.065 and q.y>.49),red)
        # Trimming may disconnect the lowest tip of an ear or tail: retain torso.
        bm=bmesh.new(); bm.from_mesh(body.data)
        remaining=set(bm.verts); islands=[]
        while remaining:
            stack=[remaining.pop()]; group=[]
            while stack:
                v=stack.pop(); group.append(v)
                for e in v.link_edges:
                    w=e.other_vert(v)
                    if w in remaining: remaining.remove(w); stack.append(w)
            islands.append(group)
        largest=max(islands,key=len)
        bmesh.ops.delete(bm,geom=[v for g in islands if g is not largest for v in g],context='VERTS')
        # One irregular cut loop can be rejected by holes_fill. Close its
        # complete boundary explicitly before volume fusion; assert watertight.
        boundary=[e for e in bm.edges if e.is_boundary]
        if boundary: bmesh.ops.contextual_create(bm,geom=boundary)
        assert not any(e.is_boundary for e in bm.edges), 'Open ox surface before voxel union'
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(body.data); bm.free()
        print('RETAINED_HIGH_OX',sum(len(p.vertices)-2 for p in body.data.polygons))
        # Short, muscular shoulder/neck bridge. Same red surface as the torso;
        # no stacked cylindrical collar or floating human bust.
        vertices,faces=[],[]
        for i in range(33):
            t=i/32; rx=.140*(1-t)+.041*t; ry=.140*(1-t)+.045*t
            for j in range(48):
                angle=math.tau*j/48
                vertices.append((rx*math.cos(angle),-.13-.14*t+ry*math.sin(angle),.48+.245*t))
        for i in range(32):
            for j in range(48):
                k=(j+1)%48; faces.append((i*48+j,i*48+k,(i+1)*48+k,(i+1)*48+j))
        faces += [tuple(reversed(range(48))),tuple(32*48+j for j in range(48))]
        mesh=bpy.data.meshes.new('new tapered shoulder to human neck'); mesh.from_pydata(vertices,[],faces); mesh.materials.append(red); mesh.update()
        neck=bpy.data.objects.new('new sloped neck',mesh); bpy.context.collection.objects.link(neck)
        masses=[body,neck]
        for name,foot in FEET.items():
            vertices,faces=[],[]
            for i in range(21):
                t=i/20; r=.023+.009*t
                center=Vector((foot.x*(1-.18*t),foot.y+(.055 if name.startswith('front') else .020)*t,.052+.14*t))
                for j in range(24):
                    angle=math.tau*j/24; vertices.append(tuple(center+Vector((r*math.cos(angle),r*math.sin(angle),0))))
            for i in range(20):
                for j in range(24):
                    k=(j+1)%24; faces.append((i*24+j,i*24+k,(i+1)*24+k,(i+1)*24+j))
            faces += [tuple(reversed(range(24))),tuple(20*24+j for j in range(24))]
            mesh=bpy.data.meshes.new('new tapered pastern'); mesh.from_pydata(vertices,[],faces); mesh.materials.append(red); mesh.update()
            obj=bpy.data.objects.new('new pastern '+name,mesh); bpy.context.collection.objects.link(obj); masses.append(obj)
        join(masses,body)
        mod=body.modifiers.new('continuous offline ox and neck sculpt','REMESH'); mod.mode='VOXEL'; mod.voxel_size=.003; mod.use_smooth_shade=True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        mod=body.modifiers.new('round new anatomical joins','SMOOTH'); mod.factor=1; mod.iterations=24; bpy.ops.object.modifier_apply(modifier=mod.name)
        # Newly painted cinnabar coat throughout, rather than projecting the
        # donor's baked normal/AO shadows onto the new neck and pasterns.
        coat=material('offline uniform cinnabar coat',(.38,.027,.010))
        body.data.materials.clear(); body.data.materials.append(coat)
        for poly in body.data.polygons: poly.use_smooth=True; poly.material_index=0
        print('OFFLINE_CONTINUOUS_BODY',sum(len(p.vertices)-2 for p in body.data.polygons))
        head=load(a.head,'yayu_human_head')
        finish_trim(head,lambda q:q.z<.075 or (q.z<.09 and abs(q.x)>.05),red)
        paint_face(head)
        for v in head.data.vertices: v.co=1.20*v.co+Vector((0,-.27,.584))
        for name,foot in FEET.items():
            hoof=load(a.horse,'yayu_horse_hoof_'+name)
            source=HORSE_FEET[name]
            finish_trim(hoof,lambda q:q.z>.065 or min(HORSE_FEET,key=lambda k:(q-HORSE_FEET[k]).length_squared)!=name,red)
            hoof.data.materials.clear(); hoof.data.materials.append(material('offline dark hoof '+name,(.035,.026,.023)))
            for poly in hoof.data.polygons: poly.material_index=0
            for v in hoof.data.vertices:
                v.co=1.05*(v.co-source)+foot
                if v.co.z<.010: v.co.z=0
            print('RETAINED_HIGH_HOOF',name,sum(len(p.vertices)-2 for p in hoof.data.polygons))
        tailmat=material('inferred ox tail dark red',(.26,.055,.028))
        curve('yayu_tail',[(0,.44,.60),(0,.50,.54),(.012,.53,.36),(.015,.54,.20)],.012,tailmat)
        tuft=ellipsoid('new ox tail tuft',(.015,.54,.19),(.022,.023,.046),tailmat)
        tail=bpy.data.objects['yayu_tail']; join([tail,tuft],tail); tail.data.name='yayu_tail'
        bpy.ops.object.select_all(action='DESELECT')
        for o in bpy.context.scene.objects:
            if o.type=='MESH': o.select_set(True)
        bpy.context.view_layer.objects.active=body; Path(a.output).parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    # Use an invisible bounds-only mesh; joining textured primitives for a
    # render would discard the head UV when the painted torso has no UV layer.
    pts=[o.matrix_world@v.co for o in bpy.context.scene.objects if o.type=='MESH' for v in o.data.vertices]
    lo,hi=[Vector(tuple(fn(q[i] for q in pts) for i in range(3))) for fn in (min,max)]
    mesh=bpy.data.meshes.new('all component bounds'); mesh.from_pydata([(x,y,z) for x in (lo.x,hi.x) for y in (lo.y,hi.y) for z in (lo.z,hi.z)],[],[])
    body=bpy.data.objects.new('render bounds only',mesh); bpy.context.collection.objects.link(body)
    Path(a.views).mkdir(parents=True,exist_ok=True); cam=setup_render(1024)
    if a.view=='left':
        pts=[v.co for v in body.data.vertices]; lo,hi=[Vector(tuple(fn(q[i] for q in pts) for i in range(3))) for fn in (min,max)]
        center=(lo+hi)/2; extent=max(hi-lo); cam.data.ortho_scale=extent*1.15
        location=center+Vector((-extent*3,0,0)); cam.matrix_world=Matrix.LocRotScale(location,(center-location).to_track_quat('-Z','Y'),Vector((1,1,1)))
        bpy.context.view_layer.update(); bpy.context.scene.render.filepath=f'{a.views}/view_left.png'; bpy.ops.render.render(write_still=True)
    else: render_views(body,cam,a.views,only_view=a.view)

if __name__=='__main__': main()
