"""Xiangliu continuous co-root authoring. Preserve native High human faces; rebuild lower tissue.
No paid API. Inputs are explicit files; all outputs belong to this worktree.
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
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

TISSUE_COLOUR=np.array([.21,.40,.34])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mesh_object(name, points, faces, material=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if material:
        mesh.materials.append(material)
    return obj


def tube(name, centers, radii, sides=48):
    points, faces = [], []
    for j, (center, radius) in enumerate(zip(centers, radii)):
        tangent = Vector(centers[min(j+1,len(centers)-1)])-Vector(centers[max(0,j-1)])
        tangent.normalize()
        ref = Vector((1,0,0))
        if abs(tangent.dot(ref))>.95:
            ref = Vector((0,1,0))
        a = (ref-tangent*tangent.dot(ref)).normalized()
        b = tangent.cross(a).normalized()
        for i in range(sides):
            angle = 2*math.pi*i/sides
            points.append(Vector(center)+float(radius)*(math.cos(angle)*a+math.sin(angle)*b))
    for j in range(len(centers)-1):
        for i in range(sides):
            a=j*sides+i;b=j*sides+(i+1)%sides
            faces.append((a,b,b+sides,a+sides))
    faces.extend([tuple(range(sides-1,-1,-1)),tuple((len(centers)-1)*sides+i for i in range(sides))])
    return mesh_object(name, points, faces)


def body_path(t):
    # +Y anterior, -Y tail. The shallow S never turns back onto itself.
    return Vector((.34*math.sin(2*math.pi*t)*math.sin(math.pi*t),1.9-7.0*t,.75-.45*t+.045*math.sin(math.pi*t)))


def body_radius(t):
    # A single smooth beta profile from rounded anterior pole to tail. There is
    # no cap-to-cylinder junction, radius clamp shoulder, or straight underside.
    s=float(t)
    return max(.009,.59*math.sqrt(s/.2173913)*((1-s)/.7826087)**1.8)


def sculpt_material():
    mat=bpy.data.materials.new('Qing_serpent_rebuilt_UV_tissue')
    mat.use_nodes=True
    nodes=mat.node_tree.nodes;links=mat.node_tree.links
    bs=nodes.get('Principled BSDF');bs.inputs['Roughness'].default_value=.82
    coord=nodes.new('ShaderNodeTexCoord')
    sep=nodes.new('ShaderNodeSeparateXYZ');links.new(coord.outputs['Position'] if 'Position' in coord.outputs else coord.outputs['Generated'],sep.inputs[0])
    noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=18;noise.inputs['Detail'].default_value=2
    links.new(coord.outputs['Object'],noise.inputs['Vector'])
    ramp=nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color=(.055,.155,.135,1)
    ramp.color_ramp.elements[1].color=(.20,.37,.30,1)
    links.new(noise.outputs['Fac'],ramp.inputs[0]);links.new(ramp.outputs[0],bs.inputs['Base Color'])
    return mat


def export(path, objects):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_animations=False,export_yup=True,export_normals=True,export_materials='EXPORT',export_attributes=True)


def render_views(objects, output, prefix='', center=None, scale=None):
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True
    scene.render.resolution_x=1100;scene.render.resolution_y=900;scene.render.resolution_percentage=100
    scene.view_settings.view_transform='AgX'
    world=bpy.data.worlds.new('Review_world');world.use_nodes=True
    world.node_tree.nodes['Background'].inputs[0].default_value=(.57,.59,.60,1)
    world.node_tree.nodes['Background'].inputs[1].default_value=.7;scene.world=world
    for old in list(scene.objects):
        if old.name.startswith('Review_light_'):bpy.data.objects.remove(old,do_unlink=True)
    for i,(loc,power,size) in enumerate([((3,-4,8),1200,6),((-5,0,5),900,5),((0,5,7),1000,5)]):
        light=bpy.data.objects.new('Review_light_'+str(i),bpy.data.lights.new('Review_light_'+str(i),'AREA'))
        scene.collection.objects.link(light);light.location=loc;light.data.energy=power;light.data.size=size
        light.rotation_euler=(Vector((0,0,1))-light.location).to_track_quat('-Z','Y').to_euler()
    allp=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
    low=Vector([min(p[k] for p in allp) for k in range(3)]);high=Vector([max(p[k] for p in allp) for k in range(3)])
    center=Vector(center) if center else (low+high)/2
    scale=scale or max(high-low)*1.15
    for name, direction in [('34',(1,1,.65)),('front',(0,1,.12)),('side',(1,0,.15)),('back',(0,-1,.2))]:
        camera=bpy.data.objects.new('Review_camera',bpy.data.cameras.new('Review_camera'))
        scene.collection.objects.link(camera);camera.location=center+Vector(direction).normalized()*15
        camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type='ORTHO';camera.data.ortho_scale=scale;scene.camera=camera
        scene.render.filepath=str(output/(prefix+'view_'+name+'.png'));bpy.ops.render.render(write_still=True)


def native_head(path, cut=.40):
    old=set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(path),disable_bone_shape=True)
    source=next(o for o in bpy.context.scene.objects if o not in old and o.type=='MESH')
    source_sha=digest(path)
    if source_sha=='454cee9efe4a0f60324ccb3d6cfb69c2bf217e34c44d2df6f2835c21ae429c9e':
        source.matrix_world=Matrix.Translation((-.00009106728248298168,-.001028126454912126,.3384270668029785))@Matrix.Scale(.5257589420802049,4)@source.matrix_world
    else:
        assert source_sha=='282651c399d5a2012dc855f0eb4fb023e412eaeae38d4bb3ee7049be3c87c4c8','Unknown native High human-head source'
    mesh=source.data
    # Source has an already recorded positive uniform normalization.
    points=[source.matrix_world@v.co for v in mesh.vertices]
    normals=[source.matrix_world.to_3x3().normalized()@n.vector for n in mesh.corner_normals]
    uv=[v.uv.copy() for v in mesh.uv_layers.active.data]
    records=[];boundary=[]
    for face in mesh.polygons:
        poly=[(points[mesh.loops[i].vertex_index],uv[i],normals[i]) for i in face.loop_indices]
        clipped=[]
        for a,b in zip(poly,poly[1:]+poly[:1]):
            if a[0].z>=cut:clipped.append(a)
            if (a[0].z-cut)*(b[0].z-cut)<0:
                t=(cut-a[0].z)/(b[0].z-a[0].z)
                p=a[0].lerp(b[0],t);p.z=cut
                c=(p,a[1].lerp(b[1],t),a[2].lerp(b[2],t).normalized());clipped.append(c);boundary.append(p)
        for i in range(1,len(clipped)-1):records.append([clipped[0],clipped[i],clipped[i+1]])
    material=mesh.materials[0].copy();material.name='Native_High_human_face_preserved'
    for node in material.node_tree.nodes:
        if node.type in {'UVMAP','NORMAL_MAP'}:node.uv_map='Native_UV'
    uvnode=material.node_tree.nodes.new('ShaderNodeUVMap');uvnode.uv_map='Native_UV'
    for node in material.node_tree.nodes:
        if node.type=='TEX_IMAGE':
            for link in list(node.inputs['Vector'].links):material.node_tree.links.remove(link)
            material.node_tree.links.new(uvnode.outputs['UV'],node.inputs['Vector'])
    patch_throat_colour(material,records)
    # Rebuilt lower surface does not use the source tangent basis or source normal map.
    # Native face keeps its original texture and normal map.
    center=Vector((sum(p.x for p in boundary)/len(boundary),sum(p.y for p in boundary)/len(boundary),cut))
    bpy.data.objects.remove(source,do_unlink=True)
    return records,material,center


def patch_throat_colour(material,records):
    """Repaint only the preserved lower throat UV islands, blending before the human jaw."""
    bs=material.node_tree.nodes.get('Principled BSDF')
    colour=next((l.from_node for l in material.node_tree.links if l.to_node==bs and l.to_socket==bs.inputs['Base Color'] and l.from_node.type=='TEX_IMAGE'),None)
    if colour is None:return
    source=colour.image;w,h=source.size
    pixels=np.array(source.pixels[:],dtype=np.float32).reshape(h,w,4)
    blend=np.zeros((h,w),np.float32)
    normal_blend=np.zeros((h,w),np.float32)
    for rec in records:
        if min(c[0].z for c in rec)>.58:continue
        uv=np.array([c[1][:] for c in rec])*[w-1,h-1]
        lo=np.maximum(0,np.floor(uv.min(axis=0)).astype(int));hi=np.minimum([w-1,h-1],np.ceil(uv.max(axis=0)).astype(int))
        if np.any(hi<lo):continue
        a,b,c=uv
        denom=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(denom)<1e-8:continue
        yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denom
        wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denom;wc=1-wa-wb
        mask=(wa>=-.03)&(wb>=-.03)&(wc>=-.03)
        z=wa*rec[0][0].z+wb*rec[1][0].z+wc*rec[2][0].z
        amount=np.clip((.57-z)/.17,0,1)*mask
        region=blend[lo[1]:hi[1]+1,lo[0]:hi[0]+1];np.maximum(region,amount,out=region)
        region=normal_blend[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        np.maximum(region,np.clip((.49-z)/.09,0,1)*mask,out=region)
    # The actual cut reaches the same flat colour as the rebuilt tissue. Above
    # it the native scales and human skin return continuously in their own UVs.
    lum=pixels[:,:,:3].mean(axis=2)
    neckcolour=(pixels[:,:,1]>=pixels[:,:,0]*.98)&(pixels[:,:,2]>=pixels[:,:,0]*.98)&(lum>.13)
    blend*=neckcolour
    target=TISSUE_COLOUR[None,None,:]
    pixels[:,:,:3]=pixels[:,:,:3]*(1-blend[:,:,None])+target*blend[:,:,None]
    image=bpy.data.images.new('Native_High_face_local_throat_colour',width=w,height=h,alpha=True)
    image.pixels.foreach_set(pixels.ravel());image.pack();colour.image=image
    for node in material.node_tree.nodes:
        if node.type!='NORMAL_MAP':continue
        for link in node.inputs['Color'].links:
            texture=link.from_node
            if texture.type!='TEX_IMAGE':continue
            original=texture.image;nw,nh=original.size
            values=np.array(original.pixels[:],dtype=np.float32).reshape(nh,nw,4)
            iy=np.rint(np.linspace(0,h-1,nh)).astype(int);ix=np.rint(np.linspace(0,w-1,nw)).astype(int)
            amount=normal_blend[iy[:,None],ix[None,:]][:,:,None]
            values[:,:,:3]=values[:,:,:3]*(1-amount)+np.array([.5,.5,1])*amount
            patched=bpy.data.images.new('Native_High_throat_normal_fade',width=nw,height=nh,alpha=True)
            patched.colorspace_settings.name='Non-Color';patched.pixels.foreach_set(values.ravel());patched.pack();texture.image=patched


def fit_native_neck_rims(bm,records,center,plan,scale=1.38):
    """Match only the last .30m to the enlarged native rim and its surface tangent."""
    samples={}
    for record in records:
        for point,uv,normal in record:
            if abs(point.z-center.z)>1e-6:continue
            key=tuple(round(float(v),6) for v in point)
            samples[key]=(point-center,normal)
    polar=[]
    for delta,normal in samples.values():
        radial=Vector((delta.x,delta.y,0));radius=radial.length*scale
        angle=math.atan2(delta.y,delta.x)%math.tau
        slope=max(-.20,min(.20,-normal.z/max(.2,normal.dot(radial.normalized()))))
        polar.append((angle,radius,slope))
    polar=np.array(sorted(polar));assert len(polar)>30
    angles=np.linspace(0,math.tau,256,endpoint=False)
    radii=np.interp(angles,polar[:,0],polar[:,1],period=math.tau)
    slopes=np.interp(angles,polar[:,0],polar[:,2],period=math.tau)
    # Native individual scale facets must not become long ridges. Fit the
    # anatomical tangent around the entire rim, keeping its low-frequency oval.
    smooth_r=np.fft.rfft(radii);smooth_r[5:]=0
    smooth_s=np.fft.rfft(slopes);smooth_s[3:]=0
    radii=np.fft.irfft(smooth_r,n=256);slopes=np.clip(np.fft.irfft(smooth_s,n=256),-.10,.10)
    result=[]
    for head in plan:
        rotation=Matrix.Rotation(math.pi/2+head['yaw'],3,'Z');inverse=rotation.transposed()
        top=Vector(head['top']);changed=0
        for vertex in bm.verts:
            d=top.z-vertex.co.z
            if d<-.05 or d>.30:continue
            t=max(0,min(1,(vertex.co.z-.72)/(top.z-.72)));e=t*t*(3-2*t)
            cx=head['seatx']+(top.x-head['seatx'])*e+.07*math.sin(math.pi*t)*math.sin(head['number']*1.7)
            cy=head['seaty']+(top.y-head['seaty'])*e-.08*math.sin(math.pi*t)
            old=Vector((vertex.co.x-cx,vertex.co.y-cy,0))
            if old.length>.26:continue
            local=inverse@old;angle=math.atan2(local.y,local.x)%math.tau
            smooth_radius=float(np.interp(angle,angles,radii,period=math.tau))
            exact_radius=float(np.interp(angle,polar[:,0],polar[:,1],period=math.tau))
            radius=smooth_radius+(exact_radius-smooth_radius)*math.exp(-max(0,d)/.018)
            slope=float(np.interp(angle,angles,slopes,period=math.tau))
            radius=max(.055,radius-slope*max(0,d))
            target=top+rotation@Vector((radius*math.cos(angle),radius*math.sin(angle),-d))
            q=max(0,min(1,(.30-d)/.22));weight=q*q*(3-2*q)
            vertex.co.x=vertex.co.x*(1-weight)+target.x*weight
            vertex.co.y=vertex.co.y*(1-weight)+target.y*weight;changed+=1
        result.append(dict(head=head['number'],fittedVertices=changed,nativeRimSamples=len(polar),headScale=scale,blendDepth=.30,fullMatchDepth=.08))
    return result


def make_head(records,material,center,number,top,scale=1.38,yaw=0):
    rotation=Matrix.Rotation(math.pi/2+yaw,3,'Z')
    verts=[];faces=[];uvs=[];normals=[]
    for rec in records:
        face=[]
        for p,uv,n in rec:
            face.append(len(verts));verts.append(rotation@((p-center)*scale)+Vector(top));uvs.append(uv);normals.append(rotation@n)
        faces.append(face)
    obj=mesh_object('human_head_%02d'%number,verts,faces,material)
    layer=obj.data.uv_layers.new(name='Native_UV')
    for i,loop in enumerate(obj.data.loops):layer.data[i].uv=uvs[loop.vertex_index]
    for p in obj.data.polygons:p.use_smooth=True
    obj.data.normals_split_custom_set_from_vertices(normals)
    return obj


def load_native_body(path,mat):
    """Retain the actual High posterior mesh/UVs; remesh only anterior root tissue."""
    global TISSUE_COLOUR
    assert digest(path)=='f0122ffce404437474bd7ce5aaa4edae776a027ba5d8f833d950d3665a8f7a75'
    bpy.ops.import_scene.gltf(filepath=str(path),disable_bone_shape=True)
    source=next(o for o in bpy.context.scene.objects if o.type=='MESH')
    pp=[source.matrix_world@v.co for v in source.data.vertices]
    lo=Vector([min(v[k] for v in pp) for k in range(3)]);hi=Vector([max(v[k] for v in pp) for k in range(3)])
    scale=7/(hi.x-lo.x)
    transform=Matrix.Translation((0,-1.6,-lo.z*scale))@Matrix.Rotation(math.pi/2,4,'Z')@Matrix.Scale(scale,4)@Matrix.Translation((-(hi.x+lo.x)/2,-(hi.y+lo.y)/2,0))
    source.matrix_world=transform@source.matrix_world
    bpy.context.view_layer.objects.active=source;source.select_set(True);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    lateral_center=float(np.median([v.co.x for v in source.data.vertices if .3<v.co.y<1.3]))
    source.data.transform(Matrix.Translation((-lateral_center,0,0)))
    source.data.calc_loop_triangles()
    points=[v.co.copy() for v in source.data.vertices];triangles=[tuple(t.vertices) for t in source.data.loop_triangles]
    uv=source.data.uv_layers.active
    uvs=[[Vector((*uv.data[li].uv,0)) for li in t.loops] for t in source.data.loop_triangles]
    bvh=BVHTree.FromPolygons(points,triangles,all_triangles=True)
    original=source.data.materials[0];original.name='Actual_High_body_original_UV_TBN'
    bs=original.node_tree.nodes.get('Principled BSDF')
    colour=next((l.from_node for l in original.node_tree.links if l.to_node==bs and l.to_socket==bs.inputs['Base Color'] and l.from_node.type=='TEX_IMAGE'),None)
    image_pixels=None
    if colour:
        w,h=colour.image.size
        image_pixels=np.array(colour.image.pixels[:],dtype=np.float32).reshape(h,w,4)
        pixels=image_pixels.reshape(-1,4)[::32,:3]
        TISSUE_COLOUR=np.median(pixels[pixels.mean(axis=1)>.06],axis=0)
    diffuse=original.copy();diffuse.name='Actual_High_body_diffuse_transfer_new_normals'
    for link in list(diffuse.node_tree.links):
        if link.to_node.type=='BSDF_PRINCIPLED' and link.to_socket.name=='Normal':diffuse.node_tree.links.remove(link)
    back=source.copy();back.data=source.data.copy();back.name='actual_high_posterior_retained';bpy.context.scene.collection.objects.link(back)
    bm=bmesh.new();bm.from_mesh(back.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,plane_co=(0,.10,0),plane_no=(0,1,0),clear_outer=True,clear_inner=False)
    bm.to_mesh(back.data);bm.free();back.data.update()
    bm=bmesh.new();bm.from_mesh(source.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
    bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,plane_co=(0,.02,0),plane_no=(0,1,0),clear_outer=False,clear_inner=True)
    boundary=[e for e in bm.edges if e.is_boundary]
    bmesh.ops.holes_fill(bm,edges=boundary,sides=0)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(source.data);bm.free();source.data.update()
    source.data.materials.clear();source.data.materials.append(mat)
    for face in source.data.polygons:face.material_index=0
    return source,back,dict(points=points,triangles=triangles,uvs=uvs,bvh=bvh,diffuse=diffuse,imagePixels=image_pixels,sourceTriangles=len(triangles),retainedPosteriorTriangles=len(back.data.polygons),uniformScale=scale,rotationZ=math.pi/2,lateralCenterShift=-lateral_center,palette=TISSUE_COLOUR.tolist())


def native_scale_patch(data,output):
    """Read a reliable original flank in metres, preserving its real scale ink."""
    width,height=512,1024;span_y=1.2;span_arc=.4
    source=data['imagePixels'];sh,sw=source.shape[:2];points=np.array([p[:] for p in data['points']])
    pixels=np.ones((height,width,4),np.float32)
    for row,y in enumerate(np.linspace(-1.8,-.6,height)):
        section=points[np.abs(points[:,1]-y)<.035]
        lo=section.min(axis=0);hi=section.max(axis=0)
        center=Vector(((lo[0]+hi[0])/2,y,(lo[2]+hi[2])/2));radius=float(((hi[0]-lo[0])+(hi[2]-lo[2]))/4)
        for col,arc in enumerate(np.linspace(0,span_arc,width)):
            theta=math.pi/2+(arc-span_arc/2)/radius;direction=Vector((math.cos(theta),0,math.sin(theta)))
            location,normal,index,distance=data['bvh'].ray_cast(center+direction*2,-direction,4)
            if location is None:location,normal,index,distance=data['bvh'].find_nearest(center+direction*radius)
            corners=[data['points'][i] for i in data['triangles'][index]]
            uv=barycentric_transform(location,*corners,*data['uvs'][index])
            x=max(0,min(sw-1,uv.x*(sw-1)));z=max(0,min(sh-1,uv.y*(sh-1)))
            ix=int(x);iz=int(z);fx=x-ix;fz=z-iz
            pixels[row,col,:3]=(source[iz,ix,:3]*(1-fx)+source[iz,min(sw-1,ix+1),:3]*fx)*(1-fz)+(source[min(sh-1,iz+1),ix,:3]*(1-fx)+source[min(sh-1,iz+1),min(sw-1,ix+1),:3]*fx)*fz
    image=bpy.data.images.new('Native_High_flank_metre_sample',width=width,height=height,alpha=True)
    image.pixels.foreach_set(pixels.ravel());image.filepath_raw=str(output/'native-scale-patch.png');image.file_format='PNG';image.save()
    return pixels,span_y,span_arc


def dark_line_density(rgb,length):
    luminance=np.asarray(rgb)[:,:3]@np.array([.2126,.7152,.0722])
    smoothed=np.convolve(luminance,np.ones(5)/5,mode='valid')
    dark=smoothed<np.median(smoothed)-.035
    starts=np.flatnonzero(dark[1:]&~dark[:-1]);accepted=[]
    minimum=max(1,round(.015/length*len(luminance)))
    for index in starts:
        if not accepted or index-accepted[-1]>=minimum:accepted.append(int(index))
    return dict(darkLines=len(accepted),lengthMetres=float(length),linesPerMetre=len(accepted)/length,contrast90to10=float(np.percentile(luminance,90)-np.percentile(luminance,10)))


def audit_neck_texture_density(mesh,layer,atlas,plan,arc_tables,sample_patch,patch,patch_length,patch_arc,output):
    triangles=[t for t in mesh.loop_triangles if mesh.polygons[t.polygon_index].material_index==0]
    tree=BVHTree.FromPolygons([v.co for v in mesh.vertices],[tuple(t.vertices) for t in triangles],all_triangles=True)
    head=plan[-1];actual=[];reference=[];locations=[];size=atlas.shape[0]
    for z in np.linspace(1.55,head['z']-.35,1024):
        t=(z-.72)/(head['z']-.72);e=t*t*(3-2*t)
        cx=head['seatx']+(head['x']-head['seatx'])*e+.07*math.sin(math.pi*t)*math.sin(head['number']*1.7)
        cy=head['seaty']+(head['y']-head['seaty'])*e-.08*math.sin(math.pi*t)
        location,normal,index,distance=tree.ray_cast(Vector((cx+.45,cy,z)),Vector((-1,0,0)),.9)
        if location is None:continue
        tri=triangles[index];corners=[mesh.vertices[i].co for i in tri.vertices]
        uv=barycentric_transform(location,*corners,*[Vector((*layer.data[li].uv,0)) for li in tri.loops])
        x=max(0,min(size-1,uv.x*(size-1)));y=max(0,min(size-1,uv.y*(size-1)))
        ix=int(x);iy=int(y);fx=x-ix;fy=y-iy
        colour=(atlas[iy,ix,:3]*(1-fx)+atlas[iy,min(size-1,ix+1),:3]*fx)*(1-fy)+(atlas[min(size-1,iy+1),ix,:3]*(1-fx)+atlas[min(size-1,iy+1),min(size-1,ix+1),:3]*fx)*fy
        length=float(np.interp(t,*arc_tables[head['number']]))
        reference.append(sample_patch(np.array([[length]]),np.array([[0.]]))[0,0]);actual.append(colour);locations.append(location[:])
    distance=float(np.linalg.norm(np.diff(np.array(locations),axis=0),axis=1).sum())
    source=dark_line_density(reference,distance);exported=dark_line_density(actual,distance)
    ratio=exported['linesPerMetre']/max(.01,source['linesPerMetre'])
    source_columns=[dark_line_density(patch[:,round(u*(patch.shape[1]-1)),:3],patch_length) for u in [.1,.3,.5,.7,.9]]
    report=dict(head=head['number'],probe='Actual new-neck positive-X surface raycast; bilinear atlas UV sampling, before meshopt/WebP',sourcePatch=dict(yRange=[-1.8,-.6],arcMetres=patch_arc,axialMetres=patch_length,columns=source_columns),nativeReferenceAlongSamePhysicalProbe=source,actualAtlasAlongSamePhysicalProbe=exported,atlasToNativeLineDensityRatio=ratio,rootProjection='Metre-space triplanar; original projection only within Y=.10 to .45 at retained posterior junction',threshold='Five-sample smoothing, median luminance minus .035; distinct dark runs separated by at least 15mm')
    (output/'texture-density-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def bake_native_local_tissue(obj,data,plan,output,size=2048):
    """A fresh atlas smoothly mixes projected native High diffuse into new neck skin.
    No inherited tangent-space normal map is used on rebuilt tissue.
    """
    mesh=obj.data;mesh.calc_loop_triangles();layer=mesh.uv_layers.new(name='Local_Tissue_Atlas')
    atlas=np.empty((size,size,4),np.float32);atlas[:,:,:3]=TISSUE_COLOUR;atlas[:,:,3]=1
    filled=np.zeros((size,size),bool)
    original=data['imagePixels'];height,width=original.shape[:2]
    patch,patch_length,patch_arc=native_scale_patch(data,output);ph,pw=patch.shape[:2]
    def sample_patch(length,arc):
        py=(patch_length-np.abs(np.mod(length,2*patch_length)-patch_length))/patch_length*(ph-1)
        px=(patch_arc-np.abs(np.mod(arc,2*patch_arc)-patch_arc))/patch_arc*(pw-1)
        iy=py.astype(int);ix=px.astype(int);fy=(py-iy)[:,:,None];fx=(px-ix)[:,:,None]
        return (patch[iy,ix,:3]*(1-fx)+patch[iy,np.minimum(pw-1,ix+1),:3]*fx)*(1-fy)+(patch[np.minimum(ph-1,iy+1),ix,:3]*(1-fx)+patch[np.minimum(ph-1,iy+1),np.minimum(pw-1,ix+1),:3]*fx)*fy
    arc_tables={}
    for head in plan:
        ts=np.linspace(0,1,256);e=ts*ts*(3-2*ts)
        cx=head['seatx']+(head['x']-head['seatx'])*e+.07*np.sin(math.pi*ts)*math.sin(head['number']*1.7)
        cy=head['seaty']+(head['y']-head['seaty'])*e-.08*np.sin(math.pi*ts)
        z=.72+(head['z']-.72)*ts
        lengths=np.r_[0,np.cumsum(np.linalg.norm(np.diff(np.c_[cx,cy,z],axis=0),axis=1))]
        arc_tables[head['number']]=(ts,lengths)
    authored=0;native=0
    for tri in mesh.loop_triangles:
        if mesh.polygons[tri.polygon_index].material_index!=0:continue
        points=np.array([mesh.vertices[i].co[:] for i in tri.vertices]);center=Vector(points.mean(axis=0))
        corner_normals=np.array([mesh.corner_normals[li].vector[:] for li in tri.loops])
        location,normal,index,distance=data['bvh'].find_nearest(center)
        neck=None
        if distance>.075 or center.z>1.40:
            candidates=[]
            for head in plan:
                t=max(0,min(1,(center.z-.72)/(head['z']-.72)));e=t*t*(3-2*t)
                c=Vector((head['seatx']+(head['x']-head['seatx'])*e+.07*math.sin(math.pi*t)*math.sin(head['number']*1.7),head['seaty']+(head['y']-head['seaty'])*e-.08*math.sin(math.pi*t),center.z))
                candidates.append(((center-c).length_squared,head))
            neck=min(candidates,key=lambda x:x[0])[1]
        mix=[];coordinates=[]
        for xyz in points:
            point=Vector(xyz)
            d=data['bvh'].find_nearest(point)[3]
            # Only the junction with retained posterior needs native projection.
            # The original anterior pole has sparse diffuse and must not remain
            # as a pale mask over the newly authored common root volume.
            q=max(0,min(1,(point.y-.10)/.35));mix.append(1-q*q*(3-2*q))
            if neck:
                t=max(0,min(1,(point.z-.72)/(neck['z']-.72)));e=t*t*(3-2*t)
                cx=neck['seatx']+(neck['x']-neck['seatx'])*e+.07*math.sin(math.pi*t)*math.sin(neck['number']*1.7)
                cy=neck['seaty']+(neck['y']-neck['seaty'])*e-.08*math.sin(math.pi*t)
                u=math.atan2(point.y-cy,point.x-cx)/math.tau%1;v=t
            else:u=math.atan2(point.z-.65,point.x)/math.tau%1;v=(point.y-.1)/1.82
            coordinates.append([u,max(0,min(1,v))])
        coordinates=np.array(coordinates)
        if coordinates[:,0].max()-coordinates[:,0].min()>.5:coordinates[coordinates[:,0]<.5,0]+=1
        coordinates=.04+.90*coordinates
        if neck:
            col=(neck['number']-1)%3;row=(neck['number']-1)//3
            coordinates[:,0]=.5+(col+coordinates[:,0])/6;coordinates[:,1]=(row+coordinates[:,1])/3
        else:coordinates[:,0]*=.46
        for li,uv in zip(tri.loops,coordinates):layer.data[li].uv=uv
        xy=coordinates*(size-1);low=np.maximum(0,np.floor(xy.min(axis=0)).astype(int));high=np.minimum(size-1,np.ceil(xy.max(axis=0)).astype(int))
        if np.any(high<low):continue
        a,b,c=xy;denom=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(denom)<1e-10:continue
        yy,xx=np.mgrid[low[1]:high[1]+1,low[0]:high[0]+1]
        wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denom
        wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denom;wc=1-wa-wb
        valid=(wa>=0)&(wb>=0)&(wc>=0)
        xyz=wa[:,:,None]*points[0]+wb[:,:,None]*points[1]+wc[:,:,None]*points[2]
        weight=np.clip(wa*mix[0]+wb*mix[1]+wc*mix[2],0,1)
        native_rgb=np.zeros_like(xyz)
        for py,px in np.argwhere(valid&(weight>.001)):
            point=Vector(xyz[py,px]);location,normal,index,distance=data['bvh'].find_nearest(point)
            corners=[data['points'][i] for i in data['triangles'][index]]
            uv=barycentric_transform(location,*corners,*data['uvs'][index])
            sx=max(0,min(width-1,round(uv.x*(width-1))));sy=max(0,min(height-1,round(uv.y*(height-1))))
            native_rgb[py,px]=original[sy,sx,:3]
        if neck:
            t=np.clip((xyz[:,:,2]-.72)/(neck['z']-.72),0,1);e=t*t*(3-2*t)
            cx=neck['seatx']+(neck['x']-neck['seatx'])*e+.07*np.sin(math.pi*t)*math.sin(neck['number']*1.7)
            cy=neck['seaty']+(neck['y']-neck['seaty'])*e-.08*np.sin(math.pi*t)
            angle=np.arctan2(xyz[:,:,1]-cy,xyz[:,:,0]-cx)/math.tau
        else:angle=np.arctan2(xyz[:,:,2]-.65,xyz[:,:,0])/math.tau
        if neck:
            length=np.interp(t,*arc_tables[neck['number']])
            radius=np.hypot(xyz[:,:,0]-cx,xyz[:,:,1]-cy)
        else:length=np.maximum(0,xyz[:,:,2]-.72);radius=np.full_like(length,.18)
        # Root tissue uses metre-space triplanar sampling, avoiding stretching
        # at a round anterior pole and covering the complete new root surface.
        normal=wa[:,:,None]*corner_normals[0]+wb[:,:,None]*corner_normals[1]+wc[:,:,None]*corner_normals[2]
        axes=np.abs(normal)**4;axes/=np.maximum(axes.sum(axis=2,keepdims=True),1e-8)
        body_colour=sample_patch(xyz[:,:,1]-.10,xyz[:,:,2])*axes[:,:,0,None]+sample_patch(xyz[:,:,2],xyz[:,:,0])*axes[:,:,1,None]+sample_patch(xyz[:,:,1]-.10,xyz[:,:,0])*axes[:,:,2,None]
        u=angle%1;arc=math.tau*radius*np.minimum(u,1-u)
        neck_colour=sample_patch(length+.025*np.sin(angle*math.tau*2),arc)
        neck_mix=np.clip((xyz[:,:,2]-1.25)/.30,0,1) if neck else np.zeros_like(length)
        neck_mix=neck_mix*neck_mix*(3-2*neck_mix)
        painted=body_colour*(1-neck_mix[:,:,None])+neck_colour*neck_mix[:,:,None]
        fade=np.clip(((neck['z'] if neck else 3)-xyz[:,:,2])/.10,0,1);fade=fade*fade*(3-2*fade)
        painted=painted*fade[:,:,None]+TISSUE_COLOUR[None,None,:]*(1-fade[:,:,None])
        weight=np.clip(wa*mix[0]+wb*mix[1]+wc*mix[2],0,1)
        rgb=native_rgb*weight[:,:,None]+painted*(1-weight[:,:,None])
        region=atlas[low[1]:high[1]+1,low[0]:high[0]+1,:3];region[valid]=rgb[valid]
        filled[low[1]:high[1]+1,low[0]:high[0]+1]|=valid
        authored+=1;native+=int(max(mix)>.5)
    # Extend the actual edge texels into gutters. Blank padding otherwise gives
    # a pale line under bilinear filtering even when both UV edge colours match.
    for _ in range(8):
        previous=filled.copy();expanded=filled.copy()
        for axis,shift in [(0,1),(0,-1),(1,1),(1,-1)]:
            mask=np.roll(previous,shift,axis=axis)&~expanded
            if axis==0:mask[0 if shift==1 else -1,:]=False
            else:mask[:,0 if shift==1 else -1]=False
            rolled=np.roll(atlas,shift,axis=axis);atlas[mask]=rolled[mask];expanded|=mask
        filled=expanded
    density=audit_neck_texture_density(mesh,layer,atlas,plan,arc_tables,sample_patch,patch,patch_length,patch_arc,output)
    image=bpy.data.images.new('Actual_High_local_tissue_diffuse_atlas',width=size,height=size,alpha=True)
    image.pixels.foreach_set(atlas.ravel());image.filepath_raw=str(output/'local-tissue-atlas.png');image.file_format='PNG';image.save();image.pack()
    material=mesh.materials[0];nodes=material.node_tree.nodes;links=material.node_tree.links
    nodes.clear();out=nodes.new('ShaderNodeOutputMaterial');bs=nodes.new('ShaderNodeBsdfPrincipled');bs.inputs['Roughness'].default_value=.82
    uvnode=nodes.new('ShaderNodeUVMap');uvnode.uv_map='Local_Tissue_Atlas';tex=nodes.new('ShaderNodeTexImage');tex.image=image
    links.new(uvnode.outputs['UV'],tex.inputs['Vector']);links.new(tex.outputs['Color'],bs.inputs['Base Color']);links.new(bs.outputs[0],out.inputs[0])
    seams={}
    for face in mesh.polygons:
        if face.material_index!=0:continue
        ids=list(face.loop_indices)
        for a,b in zip(ids,ids[1:]+ids[:1]):
            key=tuple(sorted((mesh.loops[a].vertex_index,mesh.loops[b].vertex_index)))
            uv=(layer.data[a].uv+layer.data[b].uv)*.5
            seams.setdefault(key,[]).append(tuple(uv))
    deltas=[];seam_samples=[]
    for vertices,uvpair in seams.items():
        if len(uvpair)!=2 or np.linalg.norm(np.array(uvpair[0])-uvpair[1])<.02:continue
        colours=[]
        for uv in uvpair:
            x,y=np.clip(np.rint(np.array(uv)*(size-1)).astype(int),0,size-1);colours.append(atlas[y,x,:3])
        delta=float(np.max(np.abs(colours[0]-colours[1])));deltas.append(delta)
        if delta>.1:seam_samples.append(dict(delta=delta,center=list(sum((mesh.vertices[i].co for i in vertices),Vector())/2),uv=uvpair))
    uv_audit=dict(sharedEdgesAcrossIslands=len(deltas),maxEdgeColourDelta=max(deltas,default=0),percentile95=float(np.percentile(deltas,95)) if deltas else 0,edgesOverPointOne=sum(d>.1 for d in deltas),worstSamples=sorted(seam_samples,key=lambda s:-s['delta'])[:20],normalMap=False,normalPolicy='New geometric normals; no tangent normal texture on any local UV island',colourPolicy='Per-texel nearest actual source triangle projection; eight-pixel UV gutters; new necks sample a real native flank patch at metre scale with mirrored periodic circumference and continuous tip fade')
    (output/'local-uv-seam-audit.json').write_text(json.dumps(uv_audit,indent=2)+'\n')
    return dict(authoredTriangles=authored,trianglesWithNativeColourBlend=native,atlasSize=size,normalMap=False,sourceDiffuseProjected=True,posteriorBlendY=[.10,.45],textureDensity=density,uvSeams=uv_audit)


def unify_runtime_uv(obj):
    """Ink shaders read UV0. Preserve each material's coordinates in one layer."""
    mesh=obj.data;runtime=mesh.uv_layers.new(name='Runtime_UV')
    for face in mesh.polygons:
        material=mesh.materials[face.material_index]
        if face.material_index==0:name='Local_Tissue_Atlas'
        elif material.name.startswith('Native_High'):name='Native_UV'
        else:name=mesh.uv_layers[0].name
        source=mesh.uv_layers[name]
        for index in face.loop_indices:runtime.data[index].uv=source.data[index].uv
    for name in [layer.name for layer in mesh.uv_layers if layer.name!='Runtime_UV']:
        mesh.uv_layers.remove(mesh.uv_layers[name])
    mesh.uv_layers.active_index=0;mesh.uv_layers['Runtime_UV'].active_render=True
    for material in mesh.materials:
        if not material or not material.use_nodes:continue
        nodes=material.node_tree.nodes;links=material.node_tree.links
        coord=nodes.new('ShaderNodeUVMap');coord.uv_map='Runtime_UV'
        for node in nodes:
            if node.type=='NORMAL_MAP':node.uv_map='Runtime_UV'
            if node.type!='TEX_IMAGE':continue
            for link in list(node.inputs['Vector'].links):links.remove(link)
            links.new(coord.outputs['UV'],node.inputs['Vector'])


def build(args):
    output=Path(args.out_dir);output.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mat=sculpt_material()
    native_data=None;back=None
    if args.native_body:
        body,back,native_data=load_native_body(args.body_in,mat)
    else:
        samples=np.unique(np.r_[np.linspace(0,.04,24),np.linspace(.04,.94,180),np.linspace(.94,1,24)])
        centers=[body_path(t) for t in samples]
        body=tube('serpent_body_reference',centers,[body_radius(t) for t in samples],64)
        body.data.materials.append(mat)
        for p in body.data.polygons:p.use_smooth=True
    if args.body_reference:
        # A new cylindrical UV atlas, not distorted PBR or carried-over TBN.
        bake_surface(body,output,'body_reference',1536)
        export(output/'body-reference.glb',[body]);render_views([body],output)
        (output/'body-reference-manifest.json').write_text(json.dumps(dict(source=str(Path(args.body_in).resolve()),sourceSha256=digest(args.body_in),sourceTier='Gen-2.5-Medium',geometry='Locally rebuilt elongated shallow-S closed serpent volume; source blue-green palette reference only',uv='New cylindrical atlas and physically scaled painted cells',normalMap=False,paidCalls=0,highGenerated=False),indent=2)+'\n')
        return
    records,face_mat,hcenter=native_head(args.head_in)
    if args.head_out:
        mother=make_head(records,face_mat,hcenter,0,(0,0,0))
        export(Path(args.head_out),[mother]);bpy.data.objects.remove(mother,do_unlink=True)
    # Five anterior and four posterior heads occupy different longitudinal seats.
    plan=[]
    for i,x in enumerate([-1.36,-.68,0,.68,1.36]):
        plan.append(dict(x=x,y=1.16,z=1.85+.22*(1-abs(x)/1.36),seatx=x*.15,seaty=1.10,row='front',yaw=-x*.13))
    for i,x in enumerate([-1.02,-.34,.34,1.02]):
        plan.append(dict(x=x,y=.53,z=2.55+.12*(1-abs(x)/1.02),seatx=x*.15,seaty=.54,row='rear',yaw=-x*.11))
    neck_objects=[];heads=[]
    for i,p in enumerate(plan,1):
        top=Vector((p['x'],p['y'],p['z']))
        start=Vector((p['seatx'],p['seaty'],.72))
        path=[];radii=[]
        for t in np.linspace(0,1,72):
            ease=t*t*(3-2*t)
            c=start.lerp(top,ease);c.z=start.z+(top.z-start.z)*t
            c.y-=.08*math.sin(math.pi*t)
            c.x+=.07*math.sin(math.pi*t)*math.sin(i*1.7)
            q=max(0,min(1,(float(t)-.40)/.45));shrink=.045*q*q*(3-2*q)
            path.append(c);radii.append(.13+.13*(1-t)**1.35-shrink)
        neck=tube('neck_input_%02d'%i,path,radii,40)
        neck.data.materials.append(mat)
        neck_objects.append(neck)
        heads.append(make_head(records,face_mat,hcenter,i,top,scale=1.38,yaw=p['yaw']))
        p.update(number=i,root=list(start),top=list(top),radius=.13)
    # One voxel union produces actual muscle saddles between all nine roots.
    bpy.ops.object.select_all(action='DESELECT');body.select_set(True)
    for o in neck_objects:o.select_set(True)
    bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
    body.name='continuous_serpent_and_nine_necks'
    body.data.remesh_voxel_size=.022;bpy.ops.object.voxel_remesh()
    smooth=body.modifiers.new('Muscle_surface_fairing','SMOOTH');smooth.factor=.65;smooth.iterations=5
    bpy.ops.object.modifier_apply(modifier=smooth.name)
    # Cut each isolated terminal at its actual transverse plane. Native rims are
    # bridged below this plane, so no closed internal cap survives.
    bm=bmesh.new();bm.from_mesh(body.data)
    # A remeshed scale cavity can become an isolated sub-voxel bubble. Remove
    # only tiny disconnected components; never discard an anatomical branch.
    remaining=set(bm.verts);components=[]
    while remaining:
        queue=[remaining.pop()];component=set(queue)
        while queue:
            vertex=queue.pop()
            for edge in vertex.link_edges:
                other=edge.other_vert(vertex)
                if other in remaining:remaining.remove(other);component.add(other);queue.append(other)
        components.append(component)
    for component in sorted(components,key=len,reverse=True)[1:]:
        assert len(component)<32,('Disconnected anatomical volume',len(component))
        bmesh.ops.delete(bm,geom=list(component),context='VERTS')
    if native_data:
        bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,plane_co=(0,.14,0),plane_no=(0,1,0),clear_outer=False,clear_inner=True)
    rim_fit=fit_native_neck_rims(bm,records,hcenter,plan)
    for p in plan:
        top=Vector(p['top']);near=[v for v in bm.verts if (Vector((v.co.x,v.co.y,top.z))-top).length<.22 and v.co.z>top.z-.09]
        geom=set(near)
        for v in near:geom.update(v.link_edges);geom.update(v.link_faces)
        bmesh.ops.bisect_plane(bm,geom=list(geom),dist=.000001,plane_co=top-Vector((0,0,.035)),plane_no=Vector((0,0,1)),clear_outer=True,clear_inner=False)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.00001)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(body.data);bm.free();body.data.update()
    # Join native surfaces only after the voxel union; their UVs/faces are never remeshed.
    bpy.ops.object.select_all(action='DESELECT');body.select_set(True)
    for o in heads:o.select_set(True)
    if back:back.select_set(True)
    bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
    bm=bmesh.new();bm.from_mesh(body.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.000004)
    boundary=[e for e in bm.edges if e.is_boundary]
    loops=[];todo=set(boundary)
    while todo:
        edge=todo.pop();component={edge};verts=set(edge.verts);queue=list(edge.verts)
        while queue:
            v=queue.pop()
            for e in v.link_edges:
                if e in todo:
                    todo.remove(e);component.add(e)
                    for vv in e.verts:
                        if vv not in verts:verts.add(vv);queue.append(vv)
        loops.append((component,verts))
    (output/'boundary-diagnostic.json').write_text(json.dumps([dict(edges=len(e),center=list(sum((v.co for v in vs),Vector())/len(vs)),bounds=[[min(v.co[k] for v in vs),max(v.co[k] for v in vs)] for k in range(3)]) for e,vs in loops],indent=2))
    interfaces=[item for item in loops if any((sum((v.co for v in item[1]),Vector())/len(item[1])-Vector(p['top'])).length<.07 for p in plan)]
    assert len(interfaces)==18,('Need precisely native and authored rims for nine necks',len(interfaces),len(loops))
    body_interfaces=[item for item in loops if all(abs(v.co.y-.10)<1e-5 or abs(v.co.y-.14)<1e-5 for v in item[1])] if native_data else []
    loops=interfaces
    bridges=[]
    if native_data:
        assert len(body_interfaces)==2,('Actual body section interfaces',len(body_interfaces))
        result=bmesh.ops.bridge_loops(bm,edges=list(body_interfaces[0][0]|body_interfaces[1][0]),use_pairs=False,use_cyclic=False)
        for f in result['faces']:f.material_index=0
    for p in plan:
        top=Vector(p['top'])
        pair=sorted(loops,key=lambda item:(sum((v.co for v in item[1]),Vector())/len(item[1])-top).length)[:2]
        for item in pair:loops.remove(item)
        result=bmesh.ops.bridge_loops(bm,edges=list(pair[0][0]|pair[1][0]),use_pairs=False,use_cyclic=False)
        for f in result['faces']:f.material_index=0
        bridges.append(len(result['faces']))
    # Each exported UV corner must belong to one triangle. A voxel quad crossing
    # the angular seam otherwise gets contradictory wraps in its two triangles.
    bmesh.ops.triangulate(bm,faces=[f for f in bm.faces if f.material_index==0])
    bmesh.ops.recalc_face_normals(bm,faces=[f for f in bm.faces if f.material_index==0]);bm.to_mesh(body.data);bm.free();body.data.update()
    for f in body.data.polygons:f.use_smooth=True
    # Regenerate the native face tangent basis on export; authored surface has no normal map.
    if native_data:
        local_bake=bake_native_local_tissue(body,native_data,plan,output)
    else:
        bake_surface(body,output,'continuous_tissue',2048,plan=plan)
        local_bake=None
    audit=audit_mesh(body,plan)
    audit['nativeRimFit']=rim_fit
    if native_data:
        audit['actualHighSourceTriangles']=native_data['sourceTriangles']
        audit['retainedNativePosteriorFaces']=native_data['retainedPosteriorTriangles']
        audit['localAnteriorDiffuseBake']=local_bake
        audit['nativeDiffusePalette']=native_data['palette']
    if native_data:unify_runtime_uv(body)
    export(output/'body_norm.glb',[body])
    (output/'layout.json').write_text(json.dumps(dict(heads=plan,bodyLength=7.0,bridges=bridges,audit=audit,headSource=str(Path(args.head_in).resolve()),headSha256=digest(args.head_in),bodySource=str(Path(args.body_in).resolve()),bodySha256=digest(args.body_in),bodyGeometry=('Actual native High posterior mesh and UVs retained; only anterior Y >= .10 locally fused; native diffuse transferred onto locally remeshed anterior, with new normals and no inherited normal map' if native_data else 'Locally sculpted single exterior union; Medium source provides palette reference only'),headGeometry='Preserved native reused Leishen High complete faces above .40; lower neck newly sculpted and bridged; upper nape colour locally blended',ready=False,paidCalls=0),indent=2)+'\n')
    if args.render:
        bpy.data.objects.remove(body,do_unlink=True)
        bpy.ops.import_scene.gltf(filepath=str(output/'body_norm.glb'),disable_bone_shape=True)
        actual=[o for o in bpy.context.scene.objects if o.type=='MESH']
        render_views(actual,output)
        render_views(actual,output,prefix='roots_',center=(0,.8,1.15),scale=2.8)
        render_views(actual,output,prefix='heads_',center=(0,.85,2.2),scale=3.3)
        render_views(actual,output,prefix='single_',center=(1.36,1.16,2.06),scale=.95)
        clay=bpy.data.materials.new('Geometry_only_review');clay.use_nodes=True
        clay.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.26,.30,.28,1)
        scene=bpy.context.scene;scene.view_layers[0].material_override=clay
        render_views(actual,output,prefix='clay_single_',center=(1.36,1.16,2.06),scale=.95)
        scene.view_layers[0].material_override=None


def bake_surface(obj,output,name,size,plan=None):
    """New UV projection and painted scale texture for newly authored tissue only."""
    mesh=obj.data
    layer=mesh.uv_layers.active or mesh.uv_layers.new(name='TissueUV')
    # Texture tiled in physical coordinates; UV x circumferential, y longitudinal.
    for face in mesh.polygons:
        if face.material_index!=0:continue
        coords=[]
        for li in face.loop_indices:
            p=mesh.vertices[mesh.loops[li].vertex_index].co
            nearest=None
            if plan:
                for h in plan:
                    t=max(0,min(1,(p.z-.72)/(h['z']-.72)));e=t*t*(3-2*t)
                    c=Vector((h['seatx']+(h['x']-h['seatx'])*e,h['seaty']+(h['y']-h['seaty'])*e-.08*math.sin(math.pi*t),p.z))
                    d=(p-c).length
                    if nearest is None or d<nearest[0]:nearest=(d,c,h)
            if nearest and p.z>.90 and nearest[0]<.32:
                c=nearest[1];u=math.atan2(p.y-c.y,p.x-c.x)/(2*math.pi);v=p.z/2
            else:
                t=max(0,min(1,(1.9-p.y)/7.0));c=body_path(t)
                u=math.atan2(p.z-c.z,p.x-c.x)/(2*math.pi);v=t
            coords.append([u%1,v])
        if max(c[0] for c in coords)-min(c[0] for c in coords)>.5:
            for c in coords:
                if c[0]<.5:c[0]+=1
        for li,c in zip(face.loop_indices,coords):layer.data[li].uv=c
    yy,xx=np.mgrid[0:size,0:size];u=(xx+.5)/size;v=(yy+.5)/size
    rows=112;columns=24
    qy=v*rows;qx=u*columns+.5*(np.floor(qy)%2)
    dx=(qx%1)-.5;dy=(qy%1)-.5
    cell=np.sqrt((dx*1.8)**2+(dy*1.55)**2)
    edge=np.clip((cell-.73)*18,0,1)
    light=.94+.07*np.cos(dx*5)+.035*np.sin(dy*7)
    base=TISSUE_COLOUR[None,None,:]*light[:,:,None]
    pole=np.minimum(np.clip(v/.045,0,1),np.clip((1-v)/.045,0,1))
    rgb=base*(1-.32*edge[:,:,None]*pole[:,:,None])
    # The basal neck colour approaches the pale native throat without a black collar.
    rgba=np.concatenate([np.clip(rgb,0,1),np.ones((size,size,1))],axis=2).astype(np.float32)
    image=bpy.data.images.new(name,width=size,height=size,alpha=True);image.pixels.foreach_set(rgba.ravel());image.filepath_raw=str(output/(name+'.png'));image.file_format='PNG';image.save();image.pack()
    mat=obj.data.materials[0];nodes=mat.node_tree.nodes;bs=nodes.get('Principled BSDF')
    for link in list(mat.node_tree.links):
        if link.to_node==bs and link.to_socket==bs.inputs['Base Color']:mat.node_tree.links.remove(link)
    tex=nodes.new('ShaderNodeTexImage');tex.image=image
    mat.node_tree.links.new(tex.outputs['Color'],bs.inputs['Base Color'])
    # Remove any inherited normal connection: this surface has newly generated UVs.
    for link in list(mat.node_tree.links):
        if link.to_node==bs and link.to_socket==bs.inputs['Normal']:mat.node_tree.links.remove(link)


def audit_mesh(obj,plan):
    bm=bmesh.new();bm.from_mesh(obj.data)
    edges=dict(boundary=sum(e.is_boundary for e in bm.edges),nonmanifold=sum(not e.is_manifold for e in bm.edges))
    components=0;todo=set(bm.verts)
    while todo:
        components+=1;queue=[todo.pop()]
        while queue:
            v=queue.pop()
            for e in v.link_edges:
                other=e.other_vert(v)
                if other in todo:todo.remove(other);queue.append(other)
    bm.free()
    mesh=obj.data;mesh.calc_loop_triangles()
    tree=BVHTree.FromPolygons([v.co for v in mesh.vertices],[tuple(t.vertices) for t in mesh.loop_triangles],all_triangles=True)
    pairs=tree.overlap(tree)
    tris=[set(t.vertices) for t in mesh.loop_triangles]
    intersections=[(a,b) for a,b in pairs if a<b and not(tris[a]&tris[b])]
    return dict(vertices=len(mesh.vertices),triangles=len(mesh.loop_triangles),components=components,edges=edges,nonAdjacentTriangleOverlaps=len(intersections),overlapSamples=intersections[:20],scope='Complete actual assembled mesh; BVH triangle overlap screen including native surface',headCount=len(plan))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--body-in',required=True);p.add_argument('--head-in');p.add_argument('--head-out');p.add_argument('--out-dir',required=True)
    p.add_argument('--body-reference',action='store_true');p.add_argument('--native-body',action='store_true');p.add_argument('--render',action='store_true')
    build(p.parse_args(sys.argv[sys.argv.index('--')+1:]))
