"""Boyi's newly generated ovine body and generated ear/tail masters.

medium: remove generated anatomy that contradicts the source before HIGH views.
assemble: retain the new HIGH sheep anatomy, fit four ears and nine full tails.
No substituted torso, primitive legs, block hooves, or synthesized spike tails.
"""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, setup_render
from prepare_ershu import material, ellipsoid

EARS = [(side, pair) for side in (-1, 1) for pair in (0, 1)]


def finish_cut(obj, predicate):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if predicate(v.co)], context='VERTS')
    cap = material('boyi_organic_cut_root', (.66, .59, .49))
    obj.data.materials.append(cap)
    filled = bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
    for face in filled['faces']:
        face.material_index = len(obj.data.materials)-1
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def eyeless_head(obj):
    # Replace the generated face-eye albedo with short ivory wool. The nose,
    # lips and lower muzzle retain their generated texture and fine anatomy.
    ivory = material('boyi_unbroken_facial_wool', (.69, .64, .53))
    obj.data.materials.append(ivory)
    index = len(obj.data.materials)-1
    for polygon in obj.data.polygons:
        c = polygon.center
        if c.y < -.30 and c.z > .68:
            polygon.material_index = index
    # Relax the small socket crease locally; retain the long ovine nasal bridge.
    group = obj.vertex_groups.new(name='remove_generated_facial_socket')
    for vertex in obj.data.vertices:
        p = vertex.co
        w = max(0, 1-abs(p.y+.397)/.085) * max(0, 1-abs(p.z-.745)/.060)
        if p.y < -.30 and abs(p.x) > .035 and w > 0:
            group.add([vertex.index], w, 'REPLACE')
    mod = obj.modifiers.new('smooth eye-free wool surface', 'SMOOTH')
    mod.factor, mod.iterations, mod.vertex_group = .85, 18, group.name
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.vertex_groups.clear()


def medium_body(obj):
    # This submitted Medium's nose is +X after import: rotate vertex data,
    # rather than relying on a not-yet-evaluated object matrix in Blender 5.2.
    turn = Matrix.Rotation(-math.pi/2, 3, 'Z')
    for vertex in obj.data.vertices:
        vertex.co = turn @ vertex.co
    obj.data.update()
    # The generated tail reaches the floor at y=.50, x=-.08. Actual rear
    # hooves are at y=.21, x=+/-.22; select behind them by Y, never by X alone.
    finish_cut(obj, lambda p: (abs(p.x) > .082 and p.y < -.285 and p.z > .72)
               or (p.y > .40 and p.z < .36) or (p.y > .525 and p.z < .62))
    eyeless_head(obj)
    # Correct the few millimetres of uneven AI soles by an independent smooth
    # translation of each lower leg, keeping knee/hock anatomy intact.
    for front in (True, False):
        for side in (-1, 1):
            vertices = [v for v in obj.data.vertices if (v.co.y < 0) == front and v.co.x*side > 0 and v.co.z < .15]
            bottom = min(v.co.z for v in vertices)
            for vertex in vertices:
                weight = max(0, min(1, (.15-vertex.co.z)/.08))
                vertex.co.z -= bottom*weight
    # A unified sculpt guide prevents HighPack from interpreting UV/material
    # repair borders as hard plates. This is the Medium's own organic surface.
    bpy.context.view_layer.objects.active=obj
    mod=obj.modifiers.new('continuous ovine guide surface','REMESH')
    mod.mode,mod.voxel_size='VOXEL',.003
    mod.use_smooth_shade=True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    mod=obj.modifiers.new('soft fleece and socket repair','SMOOTH')
    mod.factor,mod.iterations=.7,6
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.data.materials.clear()
    obj.data.materials.append(material('ivory wool sculpt guide',(.66,.61,.51)))
    obj.data.materials.append(material('natural cloven horn guide',(.13,.11,.085)))
    obj.data.materials.append(material('ovine nose guide',(.25,.16,.13)))
    for polygon in obj.data.polygons:
        polygon.use_smooth=True
        c=polygon.center
        polygon.material_index=1 if c.z<.043 else 2 if c.y<-.551 and .625<c.z<.69 else 0
    obj.name = 'boyi_medium_corrected_body'


def medium_ear(obj):
    # Rodin returned a head with two ears. Extract one complete generated pinna
    # with a fleshy root; no face or second ear survives this diagonal cut.
    finish_cut(obj, lambda p: p.x < .038 or p.x+p.z < .235)
    root = Vector((.049, -.005, .184))
    axis = Vector((.085, 0, .065)).normalized()
    rotation = axis.rotation_difference(Vector((0,1,0)))
    for vertex in obj.data.vertices:
        vertex.co = rotation @ (vertex.co-root)
    minimum = min(v.co.y for v in obj.data.vertices)
    for vertex in obj.data.vertices:
        vertex.co.y -= minimum
        vertex.co *= .24 / .115
        vertex.co.x *= .70
        vertex.co.y *= 1.35
        vertex.co.z *= .65
    obj.name = 'boyi_medium_single_ear'


def medium_tail(obj):
    # The generated tail is upright. Keep its relaxed S profile, put its broad
    # attachment at y=0, and turn the long axis towards +Y for clean skinning.
    points = [v.co.copy() for v in obj.data.vertices]
    lo, hi = min(p.z for p in points), max(p.z for p in points)
    root_pts = [p for p in points if p.z > hi-(hi-lo)*.10]
    root = sum(root_pts, Vector())/len(root_pts)
    rotation = Matrix.Rotation(math.pi/2, 3, 'X')
    for vertex in obj.data.vertices:
        vertex.co = rotation @ (vertex.co-root)
    minimum = min(v.co.y for v in obj.data.vertices)
    for vertex in obj.data.vertices:
        vertex.co.y -= minimum
    length = max(v.co.y for v in obj.data.vertices)
    for vertex in obj.data.vertices:
        vertex.co *= .65/length
        vertex.co.x *= .38
        vertex.co.z *= .55
    obj.name = 'boyi_medium_single_tail'


def render_all(objects, out_dir, size=1024, only_view=None):
    # Keep each HIGH material and UV set intact. Camera bounds are world-space.
    bpy.context.view_layer.update()
    points=[obj.matrix_world @ v.co for obj in objects for v in obj.data.vertices]
    lo=Vector(tuple(min(p[i] for p in points) for i in range(3)))
    hi=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center=(lo+hi)/2
    extent=max(hi-lo)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    cam=setup_render(size)
    cam.data.ortho_scale=extent*1.45
    views={'34':Vector((.62,-.72,.30)), 'side':Vector((1,0,0)),
           'front':Vector((0,-1,0)), 'back':Vector((0,1,0))}
    for view in ([only_view] if only_view else views):
        cam.location=center+views[view]*extent*3
        cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
        bpy.context.scene.camera=cam
        bpy.context.scene.frame_set(bpy.context.scene.frame_current+1)
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath=f'{out_dir}/view_{view}.png'
        bpy.ops.render.render(write_still=True)
        bpy.ops.render.render(write_still=True)


def ear_root(side, pair):
    return Vector((side*.061, -.365 if pair==0 else -.296, .765 if pair==0 else .799))


def tail_center(index, t):
    fan=(index-4)/4
    root=Vector((fan*.145, .440, .595 + (.022 if index%2 else -.015)))
    return root+Vector((fan*.46*t, (.43-.045*abs(fan))*t,
                       (.20 if index%2 else .095)*math.sin(math.pi*t)-.13*t*t))


def import_part(path):
    before=set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes=[obj for obj in bpy.context.scene.objects if obj not in before and obj.type=='MESH']
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    if len(meshes)>1:
        bpy.ops.object.join()
    obj=meshes[0]
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    return obj


def canonical_part(obj, length, width):
    """Align a generated elongated organ, preserving its complete HIGH surface."""
    points=np.array([tuple(v.co) for v in obj.data.vertices])
    center=points.mean(axis=0)
    _,vectors=np.linalg.eigh(np.cov((points-center).T))
    axis=Vector(vectors[:,-1])
    rotation=axis.rotation_difference(Vector((0,1,0)))
    for vertex in obj.data.vertices:
        vertex.co=rotation@(vertex.co-Vector(center))
    low=min(v.co.y for v in obj.data.vertices)
    high=max(v.co.y for v in obj.data.vertices)
    # Broad root versus tapered tip, measured away from rounded terminal caps.
    def spread(a,b):
        pts=[v.co for v in obj.data.vertices if a<=v.co.y<=b]
        return max(p.x for p in pts)-min(p.x for p in pts)
    span=high-low
    if spread(low+.08*span,low+.22*span)<spread(high-.22*span,high-.08*span):
        rotate=Matrix.Rotation(math.pi,3,'Z')
        for vertex in obj.data.vertices:
            vertex.co=rotate@vertex.co
        low,high=-high,-low
    # Preserve curvature, but subtract its measured center line during fitting.
    bins=[]
    for i in range(41):
        t=i/40
        pts=[v.co for v in obj.data.vertices if abs((v.co.y-low)/span-t)<.045]
        bins.append(sum(pts,Vector())/len(pts))
    residual=[]
    for vertex in obj.data.vertices:
        t=max(0,min(1,(vertex.co.y-low)/span))
        k=min(39,int(t*40))
        c=bins[k].lerp(bins[k+1],t*40-k)
        residual.append(vertex.co-c)
    transverse=max(max(p.x for p in residual)-min(p.x for p in residual),
                   max(p.z for p in residual)-min(p.z for p in residual))
    parameters=[]
    for vertex in obj.data.vertices:
        t=max(0,min(1,(vertex.co.y-low)/span))
        location=t*40
        k=min(39,int(location))
        c=bins[k].lerp(bins[k+1],location-k)
        vertex.co=Vector(((vertex.co.x-c.x)*width/transverse,t*length,(vertex.co.z-c.z)*width/transverse))
        parameters.append(t)
    obj.data.update()
    return parameters


def split_hooves(body):
    # The four cloven feet are the new generated anatomical feet themselves.
    # Split at a shared edge ring and use identical foot weights on that seam.
    hooves=[]
    for front in (True,False):
        for side in (-1,1):
            leg=f'{"front" if front else "back"}_{"l" if side==1 else "r"}'
            bm=bmesh.new()
            bm.from_mesh(body.data)
            keep=[f for f in bm.faces if all(v.co.z<.083 and (v.co.y<0)==front and v.co.x*side>0 for v in f.verts)]
            if not keep:
                raise RuntimeError(f'Missing generated hoof {leg}')
            retained=set(keep)
            remove=[f for f in bm.faces if f not in retained]
            bmesh.ops.delete(bm,geom=remove,context='FACES')
            bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
            mesh=bpy.data.meshes.new(leg+' generated cloven hoof')
            bm.to_mesh(mesh)
            bm.free()
            for mat in body.data.materials:
                mesh.materials.append(mat)
            obj=bpy.data.objects.new('boyi_hoof_'+leg,mesh)
            bpy.context.collection.objects.link(obj)
            points=[v.co for v in obj.data.vertices]
            cx=(min(p.x for p in points)+max(p.x for p in points))/2
            cy=(min(p.y for p in points)+max(p.y for p in points))/2
            # Deepen the natural interdigital cleft in the generated hoof;
            # retain its rounded heel, fetlock and both original horn toes.
            finish_cut(obj,lambda p: abs(p.x-cx)<.0045 and p.y<cy+.005 and p.z<.044)
            obj.data.materials.clear()
            obj.data.materials.append(material(leg+' dark ovine horn',(.065,.053,.037)))
            for polygon in obj.data.polygons:
                polygon.material_index=0
            hooves.append(obj)
    bm=bmesh.new()
    bm.from_mesh(body.data)
    remove=[f for f in bm.faces if all(v.co.z<.083 for v in f.verts)]
    bmesh.ops.delete(bm,geom=remove,context='FACES')
    bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
    bm.to_mesh(body.data)
    bm.free()
    return hooves


def assemble(args):
    body=load(args.input)
    if args.yaw:
        turn=Matrix.Rotation(math.radians(args.yaw),3,'Z')
        for vertex in body.data.vertices:
            vertex.co=turn@vertex.co
    body.name='boyi_high_sheep_body'
    body.data.update()
    # Accepted HIGH-v2 keeps the continuous eye-free head and its own albedo.
    # Level each generated sole locally without replacing any leg anatomy.
    for front in (True,False):
        for side in (-1,1):
            foot=[v for v in body.data.vertices if v.co.z<.16 and (v.co.y<0)==front and v.co.x*side>0]
            bottom=min(v.co.z for v in foot)
            for vertex in foot:
                vertex.co.z-=bottom*max(0,min(1,(.16-vertex.co.z)/.07))
                if vertex.co.z<.008:
                    vertex.co.z=0
    objects=[body]+split_hooves(body)
    ear=import_part(args.ear)
    canonical_part(ear,.225,.09)
    for side,pair in EARS:
        obj=ear.copy()
        obj.data=ear.data.copy()
        bpy.context.collection.objects.link(obj)
        obj.name=f'boyi_ear_{side}_{pair}_outer'
        direction=Vector((side*.19, -.07 if pair==0 else .115, -.045 if pair==0 else .015)).normalized()
        rotation=Vector((0,1,0)).rotation_difference(direction)
        for vertex in obj.data.vertices:
            vertex.co=rotation@(vertex.co-Vector((0,.026,0)))+ear_root(side,pair)
        objects.append(obj)
    bpy.data.objects.remove(ear,do_unlink=True)
    tail=import_part(args.tail)
    parameters=canonical_part(tail,1,.095)
    for index in range(9):
        obj=tail.copy()
        obj.data=tail.data.copy()
        obj.name=f'boyi_tail_{index:02}'
        bpy.context.collection.objects.link(obj)
        for vertex,t in zip(obj.data.vertices,parameters):
            tangent=(tail_center(index,min(1,t+.001))-tail_center(index,max(0,t-.001))).normalized()
            u=tangent.cross(Vector((0,0,1))).normalized()
            v=u.cross(tangent).normalized()
            vertex.co=tail_center(index,t)+u*vertex.co.x+v*vertex.co.z
        objects.append(obj)
    bpy.data.objects.remove(tail,do_unlink=True)
    rim=material('boyi_dorsal_socket',(.32,.26,.18))
    sclera=material('boyi_dorsal_sclera',(.76,.66,.45))
    iris=material('boyi_dorsal_iris',(.47,.28,.075))
    pupil=material('boyi_dorsal_pupil',(.018,.014,.010))
    bpy.context.view_layer.update()
    for side in (-1,1):
        x=side*.105
        hit,location,_,_=body.ray_cast(Vector((x,.005,1.3)),Vector((0,0,-1)))
        if not hit:
            raise RuntimeError('Missing dorsal eye mounting surface')
        for name,dz,size,mat in [('socket',-.004,(.060,.080,.007),rim),
                                 ('sclera',.001,(.049,.066,.006),sclera),
                                 ('iris',.006,(.031,.037,.003),iris),
                                 ('pupil',.009,(.026,.007,.002),pupil)]:
            eye=ellipsoid(f'boyi_dorsal_{side}_{name}',(x,.005,location.z+dz),size,mat)
            for vertex in eye.data.vertices:
                p=vertex.co+eye.location
                found,surface,_,_=body.ray_cast(Vector((p.x,p.y,1.3)),Vector((0,0,-1)))
                if found:
                    vertex.co.z+=surface.z-location.z
            eye.data.update()
            objects.append(eye)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=body
    bpy.ops.export_scene.gltf(filepath=args.output,export_format='GLB',use_selection=True,export_animations=False)
    print('ASSEMBLED',len(objects),'meshes',sum(sum(len(p.vertices)-2 for p in o.data.polygons) for o in objects),'triangles')
    render_all(objects,args.views,only_view=args.view)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('part', choices=['body','ear','tail','assemble'])
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    parser.add_argument('--view', choices=['34','side','front','back'])
    parser.add_argument('--ear')
    parser.add_argument('--tail')
    parser.add_argument('--yaw', type=float, default=0)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.part=='assemble':
        if not args.ear or not args.tail:
            parser.error('assemble requires --ear and --tail HIGH masters')
        return assemble(args)
    obj=load(args.input)
    {'body':medium_body,'ear':medium_ear,'tail':medium_tail}[args.part](obj)
    bpy.context.view_layer.update()
    obj.data.update()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output,export_format='GLB',use_selection=True,export_animations=False)
    print('CORRECTED',args.part,'bounds',[(min(v.co[i] for v in obj.data.vertices),max(v.co[i] for v in obj.data.vertices)) for i in range(3)])
    render_all([obj],args.views,only_view=args.view)


if __name__=='__main__':
    main()
