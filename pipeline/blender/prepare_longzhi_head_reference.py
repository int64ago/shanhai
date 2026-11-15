"""Extract the actual reconstructed Longzhi neck/skull and soften only its nape.
No paid calls; new bounded output directory is required.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import bpy
import bmesh
import numpy as np
from mathutils import Matrix,Vector


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--blend',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True)
    args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(args.blend),load_ui=False)
    reference=bpy.data.objects['source_surface_for_texture_transfer']
    obj=reference.copy();obj.data=reference.data.copy();obj.name='longzhi_complete_skull_muscular_neck_reference';bpy.context.collection.objects.link(obj)
    keep={i for i,m in enumerate(obj.data.materials) if m and m.name.startswith('equal_fox_head_08__')}
    assert keep
    bm=bmesh.new();bm.from_mesh(obj.data);bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.material_index not in keep],context='FACES');bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS');bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
    manifest=json.loads(args.manifest.read_text());item=next(n for n in manifest['nodes'] if n['name']=='equal_fox_head_08');matrix=Matrix(item['worldBlenderMatrix']);inv=matrix.inverted();rot=matrix.to_3x3().normalized();pivot=Vector(item['targetEmbeddedAnchor'])
    # Local original nape mask. No muzzle, jaw, ears or upper skull is smoothed.
    group=obj.vertex_groups.new(name='only_transverse_nape_ridge')
    for vertex in obj.data.vertices:
        raw=inv@vertex.co;z=raw.z*.5261648629514518+.5001471812547346;y=raw.y*.5261648629514518-.00022119526734331785
        weight=math.exp(-((z-.53)/.065)**4)*max(0,min(1,(y-.07)/.1))
        if weight>.001:group.add([vertex.index],weight,'REPLACE')
    for o in bpy.context.scene.objects:o.select_set(False)
    obj.hide_set(False);obj.hide_render=False;obj.select_set(True);bpy.context.view_layer.objects.active=obj
    mod=obj.modifiers.new('soften_native_transverse_nape_fold','SMOOTH');mod.vertex_group=group.name;mod.factor=1.;mod.iterations=10;bpy.ops.object.modifier_apply(modifier=mod.name)
    # Re-sculpt the back of the lower cranium into a convex neck transition.
    # This removes the inherited transverse ledge rather than asking High to hide it.
    for vertex in obj.data.vertices:
        raw=inv@vertex.co;z=raw.z*.5261648629514518+.5001471812547346;y=raw.y*.5261648629514518-.00022119526734331785;x=raw.x*.5261648629514518+.0002773643760646963
        if y>.10:
            factor=1-.50*math.exp(-((z-.44)/.145)**2)
            raw.y=((.10+(y-.10)*factor)+.00022119526734331785)/.5261648629514518
            vertex.co=matrix@raw
    # Remove tiny import cracks and generate a single closed mother surface.
    donor=obj.copy();donor.data=obj.data.copy();donor.name='complete_original_skull_projection_reference';bpy.context.collection.objects.link(donor);donor.hide_render=True;donor.hide_set(True)
    remesh=obj.modifiers.new('mother_closed_continuous_volume','REMESH');remesh.mode='VOXEL';remesh.voxel_size=.00125;remesh.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=remesh.name)
    decimate=obj.modifiers.new('mother_geometry_budget','DECIMATE');decimate.ratio=.28;bpy.ops.object.modifier_apply(modifier=decimate.name)
    # Simplified short-coat mother: colors are new reference paint, no stretched
    # Medium throat UVs are submitted as High texture guidance.
    mat=bpy.data.materials.new('uniform_short_coat_reference');mat.use_nodes=True;shader=mat.node_tree.nodes.get('Principled BSDF');shader.inputs['Base Color'].default_value=(.48,.19,.066,1);shader.inputs['Roughness'].default_value=.9
    obj.data.materials.clear();obj.data.materials.append(mat)
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform
    mesh=donor.data;mesh.calc_loop_triangles();triangles=list(mesh.loop_triangles);coords=[v.co.copy() for v in mesh.vertices];tree=BVHTree.FromPolygons(coords,[list(t.vertices) for t in triangles],all_triangles=True);layer=mesh.uv_layers.active
    uv=obj.data.uv_layers.new(name='protected_face_uv')
    # Keep the eyes, nose, lips and face paint readable. All posterior skull and
    # throat is new plain short coat, so the old nape fold is not in a texture.
    for face in obj.data.polygons:
        hit,normal,index,distance=tree.find_nearest(face.center);tri=triangles[index];q=inv@hit;z=q.z*.5261648629514518+.5001471812547346;y=q.y*.5261648629514518-.00022119526734331785
        source_material=mesh.materials[tri.material_index]
        if z>=.44 and y<.14 and not source_material.name.endswith('__1'):
            if source_material.name not in obj.data.materials:
                obj.data.materials.append(source_material)
            face.material_index=obj.data.materials.find(source_material.name)
            ps=[coords[i] for i in tri.vertices];uvs=[Vector((*layer.data[i].uv,0)) for i in tri.loops]
            for loop in face.loop_indices:
                point=obj.data.vertices[obj.data.loops[loop].vertex_index].co;value=barycentric_transform(point,*ps,*uvs);uv.data[loop].uv=value.xy
        else:face.material_index=0
        face.use_smooth=True
    # Bake a continuous concept color directly into corners. A smooth face/nape
    # blend avoids projecting the old stretched neck atlas or a rectangular decal.
    images={}
    for material in mesh.materials:
        if not material or not material.use_nodes:continue
        bsdf=next((n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if bsdf and bsdf.inputs['Base Color'].is_linked:
            tex=bsdf.inputs['Base Color'].links[0].from_node
            if tex.type=='TEX_IMAGE':
                im=tex.image;pixels=np.empty(im.size[0]*im.size[1]*4,np.float32);im.pixels.foreach_get(pixels);images[material.name]=(pixels.reshape(im.size[1],im.size[0],4),im.size[:])
    colors=obj.data.color_attributes.new(name='ContinuousConceptCoat',type='FLOAT_COLOR',domain='CORNER')
    plain=np.array([.48,.19,.066])
    vertex_colors=[]
    for vertex in obj.data.vertices:
        hit,normal,index,distance=tree.find_nearest(vertex.co);tri=triangles[index];material=mesh.materials[tri.material_index];q=inv@hit;z=q.z*.5261648629514518+.5001471812547346;y=q.y*.5261648629514518-.00022119526734331785
        preserve=max(0,min(1,(.23-y)/.14))*max(0,min(1,(z-.43)/.12));preserve=preserve*preserve*(3-2*preserve)
        color=plain.copy()
        if material.name in images:
            ps=[coords[i] for i in tri.vertices];uvs=[Vector((*layer.data[i].uv,0)) for i in tri.loops];value=barycentric_transform(hit,*ps,*uvs)
            image,(width,height)=images[material.name];source=image[min(height-1,max(0,int(value.y*height))),min(width-1,max(0,int(value.x*width))),:3]
            source=np.where(source<=.04045,source/12.92,((source+.055)/1.055)**2.4);color=plain*(1-preserve)+source*preserve
        vertex_colors.append((*color,1))
    for face in obj.data.polygons:
        for loop in face.loop_indices:colors.data[loop].color=vertex_colors[obj.data.loops[loop].vertex_index]
        face.material_index=0
    obj.data.materials.clear();obj.data.materials.append(mat)
    vertex_color=mat.node_tree.nodes.new('ShaderNodeVertexColor');vertex_color.layer_name=colors.name;mat.node_tree.links.new(vertex_color.outputs['Color'],shader.inputs['Base Color'])
    for vertex in obj.data.vertices:vertex.co=rot.transposed()@(vertex.co-pivot)
    low=min(v.co.z for v in obj.data.vertices)
    bottom=[v.co.copy() for v in obj.data.vertices if v.co.z<low+.008]
    rootcenter=sum(bottom,Vector())/len(bottom)
    rx=max(abs(q.x-rootcenter.x) for q in bottom);ry=max(abs(q.y-rootcenter.y) for q in bottom)
    for vertex in obj.data.vertices:
        q=vertex.co
        if q.z<low+.03:
            radius=math.sqrt(((q.x-rootcenter.x)/rx)**2+((q.y-rootcenter.y)/ry)**2)
            q.z-=.017*max(0,1-min(1,radius)**2)*(1-(q.z-low)/.03)**2
    low=min(v.co.z for v in obj.data.vertices)
    for vertex in obj.data.vertices:vertex.co.z-=low
    obj.data.update()
    for o in list(bpy.context.scene.objects):
        if o is not obj:bpy.data.objects.remove(o,do_unlink=True)
    obj.hide_set(False);obj.hide_render=False
    bpy.ops.export_scene.gltf(filepath=str(out/'headneck-reference.glb'),export_format='GLB',use_selection=True,export_animations=False)
    bm=bmesh.new();bm.from_mesh(obj.data);audit={'sourceBlend':str(args.blend),'sourceBlendSha256':hashlib.sha256(args.blend.read_bytes()).hexdigest(),'boundaryEdges':sum(e.is_boundary for e in bm.edges),'nonManifoldEdges':sum(not e.is_manifold for e in bm.edges),'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons),'paidCalls':0,'accepted':False,'disclosure':'Medium skull shape retained; reconstructed neck/root, locally softened nape, voxel closed derivative. Simplified new plain coat on neck/nape; original face/eye/nose paint only retained for concept.'};bm.free();(out/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True;scene.render.resolution_x=scene.render.resolution_y=1000;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='AgX';world=bpy.data.worlds.new('neutral');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.55,.57,.60,1);world.node_tree.nodes['Background'].inputs[1].default_value=.8;scene.world=world
    points=[v.co for v in obj.data.vertices];lo=Vector(tuple(min(p[i] for p in points) for i in range(3)));hi=Vector(tuple(max(p[i] for p in points) for i in range(3)));center=(lo+hi)*.5;extent=max(hi-lo)*1.15
    for i,(loc,energy) in enumerate([((2,-3,4),240),((-3,1,2),210),((1,3,3),180)]):
        light=bpy.data.objects.new('softbox'+str(i),bpy.data.lights.new('softbox'+str(i),'AREA'));scene.collection.objects.link(light);light.location=loc;light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler();light.data.energy=energy;light.data.size=3
    for name,direction in [('34',(.8,-1,.25)),('side',(1,0,0)),('front',(0,-1,0)),('back',(0,1,0))]:
        camera=bpy.data.objects.new(name,bpy.data.cameras.new(name));scene.collection.objects.link(camera);camera.location=center+Vector(direction).normalized()*3;camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.type='ORTHO';camera.data.ortho_scale=extent;scene.camera=camera;scene.render.filepath=str(out/('view_'+name+'.png'));bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'headneck-reference.blend'))

if __name__=='__main__':main()
