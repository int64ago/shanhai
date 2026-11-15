"""Bake exact closest-source coat samples to one continuous Longzhi atlas.
No cage rays: at tight limb creases those can hit an unrelated surface.
"""
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform
from types import SimpleNamespace


def smooth(t):
    t=max(0,min(1,t))
    return t*t*(3-2*t)


def bake(obj,reference,regions,size=4096):
    mesh=reference.data
    mesh.calc_loop_triangles()
    # Snapshot Blender RNA before editing any mesh custom data.
    triangles=[SimpleNamespace(vertices=tuple(t.vertices),loops=tuple(t.loops),material_index=int(t.material_index)) for t in mesh.loop_triangles]
    coords=[v.co.copy() for v in mesh.vertices]
    uvs=[Vector((*item.uv,0)) for item in mesh.uv_layers.active.data]
    tree=BVHTree.FromPolygons(coords,[list(t.vertices) for t in triangles],all_triangles=True)
    bodytri=[t for t in triangles if mesh.materials[t.material_index].name.startswith('longzhi_body_high')]
    bodytree=BVHTree.FromPolygons(coords,[list(t.vertices) for t in bodytri],all_triangles=True)
    images={}
    for i,material in enumerate(mesh.materials):
        bsdf=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        texture=bsdf.inputs['Base Color'].links[0].from_node
        image=texture.image
        values=np.empty(image.size[0]*image.size[1]*4,np.float32)
        image.pixels.foreach_get(values)
        images[i]=values.reshape(image.size[1],image.size[0],4)
    def sample(tri,hit):
        uv=barycentric_transform(hit,*[coords[j] for j in tri.vertices],*[uvs[j] for j in tri.loops])
        pixels=images[tri.material_index];h,w=pixels.shape[:2]
        x=max(0,min(w-1,uv.x*w-.5));y=max(0,min(h-1,uv.y*h-.5));ix=int(x);iy=int(y);fx=x-ix;fy=y-iy
        rgb=(pixels[iy,ix,:3]*(1-fx)+pixels[iy,min(ix+1,w-1),:3]*fx)*(1-fy)+(pixels[min(iy+1,h-1),ix,:3]*(1-fx)+pixels[min(iy+1,h-1),min(ix+1,w-1),:3]*fx)*fy
        return np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4),uv
    byname={r['name']:r for r in regions}
    values=[];quality=[]
    for vertex in obj.data.vertices:
        p=vertex.co;hit,normal,index,distance=tree.find_nearest(p);tri=triangles[index];rgb,uv=sample(tri,hit)
        name=mesh.materials[tri.material_index].name.split('__')[0];region=byname.get(name)
        if region:
            root=Vector(region['root']);axis=(Vector(region['collar'] if region['role']=='head' else region['tip'])-root).normalized();height=(p-root).dot(axis)
            if region['role']=='tail':
                weight=smooth((uv.x-.80)/.08);rgb=rgb*(1-weight)+np.array([.78,.73,.64])*weight
            band=.17 if region['role']=='head' else .23 if region['name'] in ('longzhi_tail_06','longzhi_tail_09') else .145
            weight=1-smooth(height/band)
            if weight>0:
                hit,normal,index,distance=bodytree.find_nearest(p);body,_=sample(bodytri[index],hit);rgb=rgb*(1-weight)+body*weight
        # Reserve exact zero for unbaked atlas pixels, including at black claws.
        values.append((*np.maximum(rgb,1e-5),1))
        quality.append(smooth((height/(Vector(region['collar'])-Vector(region['root'])).length-.80)/.20) if region and region['role']=='head' else 0.)
    face_mask=obj.data.color_attributes.new(name='PreserveHighFaceDetail',type='FLOAT_COLOR',domain='CORNER')
    for loop in obj.data.loops:
        value=quality[loop.vertex_index];face_mask.data[loop.index].color=(value,value,value,1)
    colors=obj.data.color_attributes.new(name='ExactClosestSourceCoat',type='FLOAT_COLOR',domain='CORNER')
    for loop in obj.data.loops:colors.data[loop.index].color=values[loop.vertex_index]
    bpy.ops.object.select_all(action='DESELECT');obj.hide_set(False);obj.select_set(True);bpy.context.view_layer.objects.active=obj
    for layer in list(obj.data.uv_layers):obj.data.uv_layers.remove(layer)
    obj.data.uv_layers.new(name='ContinuousCoatAtlas')
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.uv.smart_project(angle_limit=.6,island_margin=.004);bpy.ops.object.mode_set(mode='OBJECT')
    colors=obj.data.color_attributes['ExactClosestSourceCoat'];face_mask=obj.data.color_attributes['PreserveHighFaceDetail']
    material=bpy.data.materials.new('Longzhi_continuous_rebaked_coat');material.use_nodes=True;nodes=material.node_tree.nodes;links=material.node_tree.links;shader=nodes.get('Principled BSDF');shader.inputs['Roughness'].default_value=.9
    attribute=nodes.new('ShaderNodeVertexColor');attribute.layer_name=colors.name;emission=nodes.new('ShaderNodeEmission');links.new(attribute.outputs['Color'],emission.inputs['Color']);output=nodes.get('Material Output');links.new(emission.outputs[0],output.inputs['Surface'])
    image=bpy.data.images.new('Longzhi_exact_source_continuous_diffuse',width=size,height=size,alpha=False);texture=nodes.new('ShaderNodeTexImage');texture.image=image;nodes.active=texture
    obj.data.materials.clear();obj.data.materials.append(material)
    for face in obj.data.polygons:face.material_index=0
    # Conservative rasterization also covers subpixel UV charts. Cycles can
    # entirely miss their samples, leaving whole isolated triangles black.
    pixels=np.zeros((size,size,4),np.float32);pixels[:,:,3]=1;valid=np.zeros((size,size),bool);detail_weight=np.zeros((size,size),np.float32);obj.data.calc_loop_triangles();uv=obj.data.uv_layers.active
    for tri in obj.data.loop_triangles:
        xy=np.array([uv.data[j].uv[:] for j in tri.loops])*size-.5
        rgb=np.array([colors.data[j].color[:3] for j in tri.loops]);quality=np.array([face_mask.data[j].color[0] for j in tri.loops])
        lo=np.maximum(0,np.floor(xy.min(axis=0)-1).astype(int));hi=np.minimum(size-1,np.ceil(xy.max(axis=0)+1).astype(int))
        a,b,c=xy;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-10:
            x,y=np.clip(np.round(xy.mean(axis=0)).astype(int),0,size-1);pixels[y,x,:3]=rgb.mean(axis=0);valid[y,x]=True;continue
        xx,yy=np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1));w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den;w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den;w2=1-w0-w1
        altitude=np.abs(den)/np.maximum(1e-8,np.array([np.linalg.norm(b-c),np.linalg.norm(c-a),np.linalg.norm(a-b)]));inside=(w0>=-.8/altitude[0])&(w1>=-.8/altitude[1])&(w2>=-.8/altitude[2]);weights=np.maximum(0,np.stack([w0[inside],w1[inside],w2[inside]],axis=1));weights/=weights.sum(axis=1)[:,None];pixels[yy[inside],xx[inside],:3]=weights@rgb;detail_weight[yy[inside],xx[inside]]=weights@quality;valid[yy[inside],xx[inside]]=True
    for step in range(4):
        previous=valid.copy()
        for axis,shift in [(0,1),(0,-1),(1,1),(1,-1)]:
            neighbor=np.roll(previous,shift,axis=axis);fill=(~valid)&neighbor;moved=np.roll(pixels,shift,axis=axis);pixels[fill]=moved[fill];valid[fill]=True
    rgb=pixels[:,:,:3];pixels[:,:,:3]=np.where(rgb<=.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
    # Native fox eyes, muzzle and ear paint retain full texel detail; the
    # conservative raster remains the fallback for every missed small chart.
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=8;scene.render.bake.use_selected_to_active=True;scene.render.bake.cage_extrusion=.003;scene.render.bake.max_ray_distance=.012;scene.render.bake.margin=4;scene.render.bake.use_pass_direct=False;scene.render.bake.use_pass_indirect=False;scene.render.bake.use_pass_color=True;reference.hide_set(False);reference.hide_render=False;reference.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.bake(type='DIFFUSE');detail=np.empty(size*size*4,np.float32);image.pixels.foreach_get(detail);detail=detail.reshape(size,size,4);weight=detail_weight*(detail[:,:,:3].max(axis=2)>1e-7);pixels[:,:,:3]=pixels[:,:,:3]*(1-weight[:,:,None])+detail[:,:,:3]*weight[:,:,None];reference.select_set(False);scene.render.bake.use_selected_to_active=False
    image.pixels.foreach_set(pixels.ravel());image.update();image.pack();links.new(shader.outputs[0],output.inputs['Surface']);links.new(texture.outputs['Color'],shader.inputs['Base Color']);nodes.remove(attribute);nodes.remove(emission);obj.data.color_attributes.remove(colors);obj.data.color_attributes.remove(obj.data.color_attributes['PreserveHighFaceDetail']);reference.hide_render=True;reference.hide_set(True)
    return {'atlasSize':size,'rootColorSource':'Actual nearest original High body texels; 17cm neck / 14.5cm tail blend, extended to 23cm only on tails 06 and 09','method':'Exact nearest source triangle, barycentric UV and bilinear linear-color samples, then conservative CPU atlas rasterization including subpixel charts; no selected-to-active cage-ray ambiguity. Surface sampling follows reconstructed 1.8mm geometry.'}
