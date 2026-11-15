"""Native High registration and bounded shared-tissue assembly research.
Preserves the four mothers' major geometry/UV/PBR; only local root proxies are
resampled into disclosed authored patches. Never submits API jobs. The earlier
full-voxel candidate is not an input. Outputs remain candidates until reviewed.
"""
import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('tianwu_reference',HERE/'reference_tianwu_parts.py')
REF=importlib.util.module_from_spec(spec);spec.loader.exec_module(REF)
P=REF.P

# Fixed positive-uniform registrations of the four SHA-verified native mothers.
# Research ICP remains available, but production reconstruction needs no ignored
# reference mesh or saved .blend state.
NATIVE_REGISTRATION={
 'trunk':('318a79a034eefc81dcafb88786e10640115c298c73ffe510dd6527942d9284cc',[
  [1.19268123494055,-.004056078312989458,.003120922198543337,.570793564881085],
  [.004752212990020853,1.147687472465568,-.32450824661826433,.0034794471981320556],
  [-.001899578465855293,.32451769424837507,1.1476930677787236,.6793588913549792],[0,0,0,1]]),
 'leg':('cf1714e0506c3e23d9698f10bafc1026e6ca6fb808a8c77a94a949f939c642ab',[
  [.290362437399966,-.18895356838167582,-.0014389858446650441,-.40072354668533644],
  [.1888122886842394,.29023246613446896,-.011441240343716552,-.131646886387487],
  [.007445893247234539,.00880518793749554,.34624109241454165,.3379331829693824],[0,0,0,1]]),
 'headneck':('7f8df400a021a101f202b5d70ccf7b5605109776f98d40a2aa4e1e5970129d07',[
  [.22439896906831755,.42889536574872483,-.04706099452015209,-.689155710095446],
  [-.4312437924233437,.22465920599603298,-.008826207704671832,-.27731790374796284],
  [.01395576806521812,.04580257291224615,.4839713112749661,.8959419808210487],[0,0,0,1]]),
 'tail':('ee38dde788a160cde3e28e3b95ad4031b18e14b6d354011587e18482a6e6e954',[
  [.39986427031198024,-.3485168680201767,-.23769909387335866,1.7277415508972367],
  [.2834935203252955,.46453189725359756,-.2042004935412401,-.47415776995297276],
  [.3124040499999644,.024544048857544545,.48954836370295424,.5310362565374737],[0,0,0,1]])}

def points(obj):
    return np.array([v.co[:] for v in obj.data.vertices],dtype=float)

def tree_for(q):
    tree=KDTree(len(q))
    for i,p in enumerate(q):tree.insert(p,i)
    tree.balance();return tree

def align(source,target,kind):
    """Try proper PCA orientations, then similarity ICP, never mirror a source."""
    a=points(source);b=points(target)
    # Deterministic samples include all major volumes without topology edits.
    aa=a[np.linspace(0,len(a)-1,min(1800,len(a)),dtype=int)]
    bb=b[np.linspace(0,len(b)-1,min(6500,len(b)),dtype=int)]
    ca=aa.mean(0);cb=bb.mean(0)
    _,va=np.linalg.eigh(np.cov((aa-ca).T));_,vb=np.linalg.eigh(np.cov((bb-cb).T))
    va=va[:,::-1];vb=vb[:,::-1]
    scale=np.linalg.norm(bb-cb)/math.sqrt(len(bb))*math.sqrt(len(aa))/np.linalg.norm(aa-ca)
    tree=tree_for(bb);best=None;rotations=[]
    # Upright face/paw semantics prevent a one-sided ICP minimum that places
    # a dense human face into the similarly sized cylindrical basal root.
    semantic=np.zeros(len(aa),dtype=bool);semantic_tree=tree
    if kind=='headneck':
        semantic=aa[:,2]>aa[:,2].min()+.62*np.ptp(aa[:,2])
        semantic_tree=tree_for(bb[bb[:,2]>bb[:,2].min()+.62*np.ptp(bb[:,2])])
    elif kind=='leg':
        semantic=aa[:,2]<aa[:,2].min()+.20*np.ptp(aa[:,2])
        semantic_tree=tree_for(bb[bb[:,2]<bb[:,2].min()+.20*np.ptp(bb[:,2])])
    if kind in ['headneck','leg']:
        rotations=[np.array(Matrix.Rotation(math.radians(angle),3,'Z')) for angle in range(0,360,15)]
    else:
        for perm in itertools.permutations(range(3)):
            for signs in itertools.product([-1.,1.],repeat=3):
                r=vb[:,perm]@np.diag(signs)@va.T
                if np.linalg.det(r)>0:rotations.append(r)
    for r in rotations:
        s=scale;t=cb-s*(r@ca)
        for iteration in range(15):
            moved=s*aa@r.T+t
            nearest=np.array([(semantic_tree if semantic[i] else tree).find(v)[0][:] for i,v in enumerate(moved)]);dist=np.linalg.norm(moved-nearest,axis=1)
            keep=dist<=np.quantile(dist,.95)
            x=aa[keep];y=nearest[keep];cx=x.mean(0);cy=y.mean(0)
            u,sigma,vt=np.linalg.svd((x-cx).T@(y-cy));rr=vt.T@u.T
            if np.linalg.det(rr)<0:vt[-1]*=-1;rr=vt.T@u.T
            if kind in ['headneck','leg'] and rr[2,2]<.80:break
            ss=float(sigma.sum()/np.sum((x-cx)**2));ss=float(np.clip(ss,scale*.70,scale*1.30))
            r=rr;s=ss;t=cy-s*(r@cx)
        moved=s*aa@r.T+t
        score=float(np.mean([(semantic_tree if semantic[i] else tree).find(v)[2]**2 for i,v in enumerate(moved)]))
        if best is None or score<best[0]:best=(score,s,r,t)
    score,s,r,t=best
    transform=np.eye(4);transform[:3,:3]=s*r;transform[:3,3]=t
    source.matrix_world=Matrix(transform)
    bpy.context.view_layer.objects.active=source
    bpy.ops.object.select_all(action='DESELECT');source.select_set(True)
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    return {'rmsM':math.sqrt(score),'uniformScale':s,'matrix':transform.tolist(),'mirrored':False}

def clone_at(source,name,transform):
    obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj);obj.name=name
    obj.matrix_world=Matrix(transform)
    bpy.context.view_layer.objects.active=obj;bpy.ops.object.select_all(action='DESELECT');obj.select_set(True)
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    return obj

def layout():
    heads=[];tails=[]
    for row in range(2):
        for col,y in enumerate([-.42,-.14,.14,.42]):
            rotation=Matrix.Rotation(-math.pi/2-math.radians([-24,-8,8,24][col]),4,'Z')@Matrix.Rotation(math.radians(8 if row==0 else 2),4,'X')
            r=np.array(rotation.to_3x3());target=np.array([[-.96,-.65][row],y,[.9884,1.2934][row]])
            root=np.array([-.29 if row==0 else .14,y*.15,.64 if row==0 else .72])
            control=np.array([root,root+[-.25,y*.45,.09],target-r[:,2]*.19,target])
            heads.append({'control':control.tolist(),'headRotation':r.tolist(),'headCenter':(target+r[:,2]*.17).tolist()})
            root=np.array([1.40,[-.12,-.04,.04,.12][col],[.62,.78][row]])
            yaw=math.radians(([-40,-14,14,40] if row==0 else [-32,-10,10,32])[col]);pitch=math.radians(([-12,-8,-8,-12] if row==0 else [10,14,14,10])[col])
            direction=np.array([math.cos(yaw)*math.cos(pitch),math.sin(yaw)*math.cos(pitch),math.sin(pitch)])
            control=np.array([root,root+direction*.36+[0,0,.05],root+direction*.81+[0,(-1 if col<2 else 1)*.10,-.17 if row==0 else .17],root+direction*1.16+[0,(-1 if col<2 else 1)*.08,.04]])
            tails.append({'control':control.tolist()})
    return {'heads':heads,'tails':tails}

def chain_weights(q,record,head=False):
    centers=np.array([P.bezier(np.array(record['control']),t)[0] for t in np.linspace(0,1,6)])
    ds=[]
    for a,b in zip(centers[:-1],centers[1:]):
        d=b-a;t=np.clip((q-a)@d/(d@d),0,1);ds.append(np.linalg.norm(q-a-t[:,None]*d,axis=1))
    ds=np.array(ds).T;order=np.argsort(ds,axis=1)[:,:2];w=np.zeros((len(q),6 if head else 5))
    raw=1/np.maximum(np.take_along_axis(ds,order,axis=1),.012)**4;raw/=raw.sum(1)[:,None]
    np.put_along_axis(w,order,raw,axis=1)
    if head:
        # This is the approved registered High mother, not the old donor face.
        # Its complete ears/nose/chin extend beyond the old spherical/axial mask.
        # Keep the entire cranial section rigid, fading only in the lower neck.
        blend=P.smooth((q[:,2]-.94)/.06)
        w*=1-blend[:,None];w[:,5]=blend
    return centers,w

def chain_matrices(source,target,head=False):
    src=np.array([P.bezier(np.array(source['control']),t)[0] for t in np.linspace(0,1,6)])
    dst=np.array([P.bezier(np.array(target['control']),t)[0] for t in np.linspace(0,1,6)])
    result=[]
    for a,b,c,d in zip(src[:-1],src[1:],dst[:-1],dst[1:]):
        rot=Vector(b-a).rotation_difference(Vector(d-c)).to_matrix().to_4x4()
        scale=np.linalg.norm(d-c)/np.linalg.norm(b-a)
        result.append(np.array(Matrix.Translation(Vector(c))@rot@Matrix.Scale(scale,4)@Matrix.Translation(Vector(-a))))
    if head:
        rot=np.array(target['headRotation'])@np.array(source['headRotation']).T
        m=np.eye(4);m[:3,:3]=rot;m[:3,3]=dst[-1]-rot@src[-1];result.append(m)
    return np.array(result)

def deform_native(source,name,weights,matrices):
    obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj);obj.name=name;obj.hide_set(False);obj.hide_render=False
    q=points(source);m=np.einsum('vb,bij->vij',weights,matrices)
    moved=np.einsum('vij,vj->vi',m[:,:3,:3],q)+m[:,:3,3]
    obj.data.vertices.foreach_set('co',moved.astype(np.float32).ravel())
    # Transport imported corner normals by the local inverse transpose. Never
    # recompute donor normals after a spatially varying/nonuniform deformation.
    normal=np.array([n.vector[:] for n in source.data.corner_normals]);ids=np.array([loop.vertex_index for loop in source.data.loops])
    normal_matrix=np.linalg.inv(m[:,:3,:3]).transpose(0,2,1)
    transformed=np.einsum('lij,lj->li',normal_matrix[ids],normal);transformed/=np.maximum(np.linalg.norm(transformed,axis=1)[:,None],1e-12)
    obj.data.normals_split_custom_set(transformed.tolist())
    return obj

class SurfaceSampler:
    images={}
    def __init__(self,obj):
        self.q=points(obj);obj.data.calc_loop_triangles()
        self.tri=np.array([t.vertices[:] for t in obj.data.loop_triangles]);self.loops=np.array([t.loops[:] for t in obj.data.loop_triangles]);self.materials=np.array([t.material_index for t in obj.data.loop_triangles])
        self.uv=np.array([v.uv[:] for v in obj.data.uv_layers.active.data])
        self.normals=np.array([n.vector[:] for n in obj.data.corner_normals])
        self.tree=BVHTree.FromPolygons(self.q.tolist(),self.tri.tolist(),all_triangles=True)
        self.maps=[]
        for material in obj.data.materials:
            bs=material.node_tree.nodes.get('Principled BSDF');image=None
            if bs and bs.inputs['Base Color'].is_linked:image=getattr(bs.inputs['Base Color'].links[0].from_node,'image',None)
            if image:
                if image.name not in self.images:
                    small=image.copy();small.scale(1024,1024);data=np.empty(1024*1024*4,dtype=np.float32);small.pixels.foreach_get(data);self.images[image.name]=data.reshape(1024,1024,4);bpy.data.images.remove(small)
                self.maps.append(self.images[image.name])
            else:self.maps.append(None)
    def barycentric(self,point,index):
        a,b,c=self.q[self.tri[index]];d0=b-a;d1=c-a;d2=np.array(point)-a;den=max((d0@d0)*(d1@d1)-(d0@d1)**2,1e-30)
        u=((d1@d1)*(d2@d0)-(d0@d1)*(d2@d1))/den;w=((d0@d0)*(d2@d1)-(d0@d1)*(d2@d0))/den
        return np.array([1-u-w,u,w])
    def normal(self,point,index):
        normal=self.barycentric(point,index)@self.normals[self.loops[index]]
        return normal/max(np.linalg.norm(normal),1e-12)
    def color(self,point,index):
        image=self.maps[self.materials[index]]
        if image is None:return np.array([.25,.35,.25])
        uv=self.barycentric(point,index)@self.uv[self.loops[index]];x,y=np.clip(uv*1023,0,1023).astype(int)
        rgb=image[y,x,:3]
        return np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)

def junction_patch(body,material_index,samplers):
    polygons=[p for p in body.data.polygons if p.material_index==material_index]
    assert polygons,'No bounded root fillet was generated'
    ids=sorted({i for p in polygons for i in p.vertices});mapping={v:i for i,v in enumerate(ids)}
    patch=P.mesh('Disclosed_bounded_shared_junction_tissue',[body.data.vertices[i].co[:] for i in ids],[[mapping[i] for i in p.vertices] for p in polygons])
    import bmesh
    bm=bmesh.new();bm.from_mesh(patch.data);boundary={v.index for edge in bm.edges if edge.is_boundary for v in edge.verts};bm.free()
    group=patch.vertex_groups.new(name='Derived_patch_interior_only')
    interior=[v.index for v in patch.data.vertices if v.index not in boundary]
    if interior:
        group.add(interior,1.,'REPLACE');modifier=patch.modifiers.new('Local_tissue_only_fairing','SMOOTH');modifier.factor=.45;modifier.iterations=8;modifier.vertex_group=group.name
        bpy.context.view_layer.objects.active=patch;bpy.ops.object.modifier_apply(modifier=modifier.name)
    colors=[]
    for v in patch.data.vertices:
        hits=[]
        for sampler in samplers:
            point,normal,index,dist=sampler.tree.find_nearest(v.co)
            hits.append((dist,sampler,point,index))
        hits.sort(key=lambda hit:hit[0]);selected=hits[:2]
        weights=1/np.maximum([hit[0] for hit in selected],.00015)**2;weights/=weights.sum()
        color=sum(weight*sampler.color(point,index) for weight,(dist,sampler,point,index) in zip(weights,selected))
        colors.append([*np.clip(color,0,1),1])
    attr=patch.data.color_attributes.new(name='Junction_pigment',type='FLOAT_COLOR',domain='POINT');attr.data.foreach_set('color',np.array(colors,dtype=np.float32).ravel())
    material=bpy.data.materials.new('Authored_local_shared_tissue_not_native_High');material.use_nodes=True;vertex=material.node_tree.nodes.new('ShaderNodeVertexColor');vertex.layer_name=attr.name;bs=material.node_tree.nodes['Principled BSDF'];bs.inputs['Roughness'].default_value=.85;material.node_tree.links.new(vertex.outputs['Color'],bs.inputs['Base Color']);patch.data.materials.append(material)
    print('BOUNDED_TISSUE_PATCH',json.dumps({'faces':len(patch.data.polygons),'vertices':len(patch.data.vertices),'nativeSourceFacesResampled':False}),flush=True)
    return patch

def local_union(parts):
    # Exact union touches only actual crossing faces; the native distal mesh,
    # UVs and material images remain. This is never a full-surface voxel pass.
    originals=parts;samplers=[SurfaceSampler(obj) for obj in originals];parts=[]
    for i,source in enumerate(originals):
        obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj);parts.append(obj)
        for slot in obj.material_slots:
            if slot.material:
                slot.material=slot.material.copy();slot.material.name='Native_region_%02d'%i
    body=parts[0];body.hide_set(False);body.hide_render=False
    for i,obj in enumerate(parts[1:]):
        bpy.context.view_layer.objects.active=body
        modifier=body.modifiers.new('Bounded_root_union_%02d'%i,'BOOLEAN');modifier.operation='UNION';modifier.solver='EXACT';modifier.material_mode='TRANSFER';modifier.object=obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        bpy.data.objects.remove(obj,do_unlink=True)
        print('LOCAL_NATIVE_UNION',i,len(body.data.polygons),flush=True)
    neighbors=[[] for edge in body.data.edges]
    for polygon in body.data.polygons:
        for loop_index in polygon.loop_indices:neighbors[body.data.loops[loop_index].edge_index].append(polygon.material_index)
    attr=body.data.attributes.get('bevel_weight_edge') or body.data.attributes.new(name='bevel_weight_edge',type='FLOAT',domain='EDGE')
    weights=np.array([float(len(set(ids))>1) for ids in neighbors],dtype=np.float32);attr.data.foreach_set('value',weights)
    derived=bpy.data.materials.new('Temporary_crossing_fillet_marker');body.data.materials.append(derived);marker=len(body.data.materials)-1
    modifier=body.modifiers.new('Only_anatomical_crossing_fillet','BEVEL');modifier.limit_method='WEIGHT';modifier.width=.025;modifier.segments=5;modifier.affect='EDGES';modifier.use_clamp_overlap=False;modifier.loop_slide=False;modifier.material=marker
    bpy.context.view_layer.objects.active=body;bpy.ops.object.modifier_apply(modifier=modifier.name)
    print('LOCAL_NATIVE_FILLET',int(weights.sum()),len(body.data.polygons),flush=True)
    patch=junction_patch(body,marker,samplers)
    bpy.data.objects.remove(body,do_unlink=True)
    # Keep only this bounded authored surface, above the concave native root
    # crossings. All original major geometry/UV/PBR stays in the four mothers.
    return originals,patch

def bounded_volume_tissue(parts):
    import bmesh
    samplers=[SurfaceSampler(obj) for obj in parts];patches=[]
    regions=[('shoulder',[-.80,-.66,.19],[.36,.66,1.13],[-.60,-.53,.34],[.22,.53,1.01]),
             ('mid_hips',[.08,-.55,.17],[1.16,.55,.94],[.23,-.43,.34],[1.02,.43,.69]),
             ('sacrum',[.99,-.64,.17],[2.01,.64,1.12],[1.16,-.51,.34],[1.86,.51,.99])]
    for name,lo,hi,inner_lo,inner_hi in regions:
        clipped=[]
        for source in parts:
            q=points(source)
            if np.any(q.max(0)<lo) or np.any(q.min(0)>hi):continue
            bm=bmesh.new();bm.from_mesh(source.data);bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
            for axis in range(3):
                normal=np.zeros(3);normal[axis]=1;position=np.zeros(3);position[axis]=lo[axis]
                bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-6,plane_co=position,plane_no=normal,clear_inner=True)
                position[axis]=hi[axis]
                bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-6,plane_co=position,plane_no=normal,clear_outer=True)
            boundary=[edge for edge in bm.edges if edge.is_boundary]
            if boundary:bmesh.ops.holes_fill(bm,edges=boundary,sides=0)
            if not bm.faces:bm.free();continue
            bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
            data=bpy.data.meshes.new('Bounded_proxy_'+name);bm.to_mesh(data);bm.free();obj=bpy.data.objects.new('Bounded_proxy_'+name,data);bpy.context.collection.objects.link(obj);clipped.append(obj)
        proxy=P.join(clipped);bpy.context.view_layer.objects.active=proxy
        mod=proxy.modifiers.new('Only_bounded_root_chunk_volume','REMESH');mod.mode='VOXEL';mod.voxel_size=.004;mod.use_smooth_shade=True;bpy.ops.object.modifier_apply(modifier=mod.name)
        q=points(proxy);inside=np.all((q>inner_lo)&(q<inner_hi),axis=1);group=proxy.vertex_groups.new(name='Only_local_intersections')
        for i in np.flatnonzero(inside):
            distances=sorted(sampler.tree.find_nearest(q[i])[3] for sampler in samplers)
            weight=float(P.smooth((.075-(distances[1]-distances[0]))/.045))
            if weight>0:group.add([int(i)],weight,'REPLACE')
        mod=proxy.modifiers.new('Local_concave_tissue_rounding','SMOOTH');mod.factor=.60;mod.iterations=180;mod.vertex_group=group.name;bpy.ops.object.modifier_apply(modifier=mod.name)
        q=points(proxy);inside=np.all((q>inner_lo)&(q<inner_hi),axis=1);keep=np.zeros(len(q),dtype=bool);records={}
        for i in np.flatnonzero(inside):
            hits=[]
            for sampler in samplers:
                point,normal,index,dist=sampler.tree.find_nearest(q[i]);hits.append((dist,sampler,np.array(point),np.array(normal),index))
            hits.sort(key=lambda hit:hit[0]);a,b=hits[:2];gap=b[0]-a[0]
            if gap>=.060:continue
            keep[i]=True;point=q[i].copy()
            # The new surface covers concave crossings. Push only points still
            # inside either nearby native surface out of that surface.
            for dist,sampler,hit,normal,index in (a,b):
                signed=float((point-hit)@normal)
                if signed<.0008:point+=(.0008-signed)*normal
            margin=float(np.minimum(q[i]-inner_lo,np.array(inner_hi)-q[i]).min())
            blend=float(P.smooth((.060-gap)/.025)*P.smooth(margin/.035))
            nearest_normal=a[1].normal(a[2],a[4])
            # Fade below the native skin rather than terminate above it as a
            # visible cuff. Only the fully internal fillet stays offset outward.
            point=blend*point+(1-blend)*(a[2]-nearest_normal*.0006)
            w=1/np.maximum([a[0],b[0]],.0002)**2;w/=w.sum();w[1]*=blend;w[0]=1-w[1]
            color=w[0]*a[1].color(a[2],a[4])+w[1]*b[1].color(b[2],b[4])
            records[int(i)]=(point,np.r_[np.clip(color,0,1),1],blend,nearest_normal)
        polygons=[p for p in proxy.data.polygons if all(keep[i] for i in p.vertices)];ids=sorted({i for p in polygons for i in p.vertices});mapping={i:j for j,i in enumerate(ids)}
        patch=P.mesh('Authored_bounded_'+name,[records[i][0] for i in ids],[[mapping[i] for i in p.vertices] for p in polygons])
        smooth=np.array([v.normal[:] for v in patch.data.vertices]);blend=np.array([records[i][2] for i in ids])[:,None]
        normals=blend*smooth+(1-blend)*np.array([records[i][3] for i in ids]);normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-12)
        patch.data.normals_split_custom_set_from_vertices(normals.tolist())
        attr=patch.data.color_attributes.new(name='Junction_pigment',type='FLOAT_COLOR',domain='POINT');attr.data.foreach_set('color',np.array([records[i][1] for i in ids],dtype=np.float32).ravel())
        material=bpy.data.materials.new('Authored_local_shared_tissue_'+name);material.use_nodes=True;vertex=material.node_tree.nodes.new('ShaderNodeVertexColor');vertex.layer_name=attr.name;bs=material.node_tree.nodes['Principled BSDF'];bs.inputs['Roughness'].default_value=.85;material.node_tree.links.new(vertex.outputs['Color'],bs.inputs['Base Color']);patch.data.materials.append(material)
        bpy.data.objects.remove(proxy,do_unlink=True);patches.append(patch)
        print('BOUNDED_ROOT_VOLUME',name,len(patch.data.vertices),len(patch.data.polygons),flush=True)
    return parts,P.join(patches)

def authored_microfur(material,human=False):
    # Local art, explicitly not Rodin detail. Millimeter length / submillimeter
    # width, layered over the untouched source PBR normal texture.
    if not material or not material.use_nodes:return
    nodes=material.node_tree.nodes;links=material.node_tree.links;bs=nodes.get('Principled BSDF')
    if not bs:return
    coord=nodes.new('ShaderNodeTexCoord');stretch=nodes.new('ShaderNodeVectorMath');stretch.operation='MULTIPLY';stretch.inputs[1].default_value=(500,2200,2200);links.new(coord.outputs['Object'],stretch.inputs[0])
    noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=1;noise.inputs['Detail'].default_value=1;noise.inputs['Roughness'].default_value=.35;links.new(stretch.outputs['Vector'],noise.inputs['Vector'])
    bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.28;bump.inputs['Distance'].default_value=.0003;links.new(noise.outputs['Fac'],bump.inputs['Height'])
    if bs.inputs['Normal'].is_linked:links.new(bs.inputs['Normal'].links[0].from_socket,bump.inputs['Normal'])
    if human:
        xyz=nodes.new('ShaderNodeSeparateXYZ');links.new(coord.outputs['Object'],xyz.inputs[0]);mask=nodes.new('ShaderNodeMapRange');mask.inputs['From Min'].default_value=.94;mask.inputs['From Max'].default_value=1.;mask.inputs['To Min'].default_value=.28;mask.inputs['To Max'].default_value=0.;mask.clamp=True;links.new(xyz.outputs['Z'],mask.inputs['Value']);links.new(mask.outputs['Result'],bump.inputs['Strength'])
    links.new(bump.outputs['Normal'],bs.inputs['Normal'])

def mirror_native_y(obj):
    normals={(p.index,obj.data.loops[i].vertex_index):np.array(obj.data.corner_normals[i].vector) for p in obj.data.polygons for i in p.loop_indices}
    for vertex in obj.data.vertices:vertex.co.y*=-1
    obj.data.flip_normals();reflected=[]
    for p in obj.data.polygons:
        for i in p.loop_indices:
            normal=normals[p.index,obj.data.loops[i].vertex_index]*[1,-1,1];reflected.append(normal/max(np.linalg.norm(normal),1e-12))
    obj.data.normals_split_custom_set(np.array(reflected).tolist())

def export_mother_skin(source,path,weights,bone_names,metadata=None,mirror=False):
    """Independent identity-deformation bones; runtime owns cloned skeletons.

    Bone rest axes are exported normally. Runtime applies each deformation to
    its imported rest matrix, so coincident bind heads are unambiguous.
    """
    obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj);obj.hide_set(False);obj.hide_render=False
    obj.name=path.stem;obj.parent=None;obj.matrix_world=Matrix.Identity(4)
    data=bpy.data.armatures.new(path.stem+'_owned_rig');arm=bpy.data.objects.new(path.stem+'_rig',data);bpy.context.collection.objects.link(arm)
    bpy.ops.object.select_all(action='DESELECT');arm.select_set(True);bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    for name in bone_names:
        bone=data.edit_bones.new(name);bone.head=(0,0,0);bone.tail=(0,0,.10)
    bpy.ops.object.mode_set(mode='OBJECT')
    for j,name in enumerate(bone_names):
        group=obj.vertex_groups.new(name=name)
        for i in np.flatnonzero(weights[:,j]>1e-7):group.add([int(i)],float(weights[i,j]),'REPLACE')
    modifier=obj.modifiers.new('Native_mother_skin','ARMATURE');modifier.object=arm;obj.parent=arm
    if metadata is not None:arm['tianwuNativePlan']=json.dumps(metadata,separators=(',',':'))
    other=None
    if mirror:
        obj.name='leg_negative_y';other=obj.copy();other.data=obj.data.copy();other.name='leg_positive_y';bpy.context.collection.objects.link(other);mirror_native_y(other)
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);arm.select_set(True);bpy.context.view_layer.objects.active=arm
    if other is not None:other.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_animations=False,export_yup=True,export_extras=True)
    if other is not None:bpy.data.objects.remove(other,do_unlink=True)
    bpy.data.objects.remove(obj,do_unlink=True);bpy.data.objects.remove(arm,do_unlink=True)

def canonical_junction_pigment(obj,white=False):
    values=np.ones((len(obj.data.vertices),4),dtype=np.float32)
    if not white:
        for attribute in obj.data.color_attributes:
            colors=np.array([v.color[:] for v in attribute.data],dtype=np.float32)
            if not np.any(colors[:,:3]<.95):continue
            if attribute.domain=='POINT':values=colors
            else:
                values=np.zeros((len(obj.data.vertices),4),dtype=np.float32);counts=np.zeros(len(values))
                for loop,color in zip(obj.data.loops,colors):values[loop.vertex_index]+=color;counts[loop.vertex_index]+=1
                values/=np.maximum(counts,1)[:,None]
            break
    for attribute in list(obj.data.color_attributes):obj.data.color_attributes.remove(attribute)
    attribute=obj.data.color_attributes.new(name='Native_junction_pigment',type='FLOAT_COLOR',domain='POINT');attribute.data.foreach_set('color',values.ravel())
    obj.data.color_attributes.active_color=attribute;obj.data.color_attributes.render_color_index=0
    if not white:
        for material in obj.data.materials:
            node=material.node_tree.nodes.new('ShaderNodeVertexColor');node.layer_name=attribute.name
            material.node_tree.links.new(node.outputs['Color'],material.node_tree.nodes['Principled BSDF'].inputs['Base Color'])

def export_modular_mothers(mothers,patch,out,anatomy):
    """Four native source types; no duplicated eightfold asset storage."""
    export_dir=out/'modular';export_dir.mkdir(exist_ok=True)
    basis=np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]],dtype=float)
    metadata={'version':1,'axis':'native X-front-negative / glTF Y-up','heads':[],'tails':[],'legAnchors':[-.368,.3765,.732,1.4765]}
    for kind,key,head in [('headneck','heads',True),('tail','tails',False)]:
        source=mothers[kind];centers,weights=chain_weights(points(source),anatomy[key][0],head)
        names=['segment_'+str(i) for i in range(5)]+(['cranium'] if head else [])
        for record in anatomy[key]:
            matrices=chain_matrices(anatomy[key][0],record,head)
            pivots=np.array([P.bezier(np.array(record['control']),t)[0] for t in np.linspace(0,1,6)])
            metadata[key].append({'deformation':[(basis@m@basis.T).tolist() for m in matrices], 'pivots':(pivots@basis[:3,:3].T).tolist()})
        export_mother_skin(source,export_dir/(kind+'_norm.glb'),weights,names)
    trunk=mothers['trunk'].copy();trunk.data=mothers['trunk'].data.copy();bpy.context.collection.objects.link(trunk);trunk.hide_set(False);trunk.hide_render=False
    local=patch.copy();local.data=patch.data.copy();bpy.context.collection.objects.link(local)
    canonical_junction_pigment(trunk,white=True);canonical_junction_pigment(local)
    body=P.join([trunk,local]);body.name='Native_trunk_with_authored_bounded_roots'
    export_mother_skin(body,export_dir/'body_norm.glb',np.ones((len(body.data.vertices),1)),['core'],metadata)
    bpy.data.objects.remove(body,do_unlink=True)
    # Two offline mirrored prototypes share source maps and four bone slots.
    # Each mounted clone selects one prototype and owns its skeleton.
    source=mothers['leg'];z=points(source)[:,2];root=P.smooth((z-.32)/.10);upper=P.smooth((z-.22)/.12);sole=1-P.smooth((z-.08)/.035)
    weights=np.column_stack([root,(1-root)*upper,(1-root)*(1-upper)*(1-sole),(1-root)*(1-upper)*sole])
    assert np.max(abs(weights.sum(1)-1))<1e-10
    export_mother_skin(source,export_dir/'leg_norm.glb',weights,['anchor','upper','lower','sole'],mirror=True)
    (export_dir/'native-plan.json').write_text(json.dumps(metadata,indent=2))
    print('MODULAR_MOTHER_EXPORT',str(export_dir),'four source types; runtime acceptance pending',flush=True)

def local_claw_mask(q):
    # The actual returned toes project along -Y, with the two pale tips at
    # these registered X sections. The old -X mask affected heel tissue.
    lateral=np.minimum(abs(q[:,0]+.464),abs(q[:,0]+.414))
    return P.smooth((.021-lateral)/.008)*P.smooth((-.184-q[:,1])/.018)*P.smooth((.060-q[:,2])/.020)

def shorten_local_claws(obj):
    q=points(obj)
    def deform(v):
        result=v.copy();result[:,1]+=.40*local_claw_mask(v)*np.maximum(-.192-v[:,1],0)
        return result
    jacobian=np.empty((len(q),3,3));epsilon=1e-5
    for axis in range(3):
        delta=np.zeros(3);delta[axis]=epsilon;jacobian[:,:,axis]=(deform(q+delta)-deform(q-delta))/(2*epsilon)
    inverse=np.linalg.inv(jacobian).transpose(0,2,1);ids=np.array([loop.vertex_index for loop in obj.data.loops]);normals=np.array([n.vector[:] for n in obj.data.corner_normals])
    transported=np.einsum('lij,lj->li',inverse[ids],normals);transported/=np.maximum(np.linalg.norm(transported,axis=1)[:,None],1e-12)
    obj.data.vertices.foreach_set('co',deform(q).astype(np.float32).ravel());obj.data.normals_split_custom_set(transported.tolist())

def paint_local_atlas(obj,label,mask,target_color):
    """Bounded local art in an owned copy of the original diffuse atlas."""
    obj.data.calc_loop_triangles();q=points(obj);uv=np.array([v.uv[:] for v in obj.data.uv_layers.active.data])
    for slot in obj.material_slots:
        original=slot.material
        if not original or not original.use_nodes:continue
        material=original.copy();slot.material=material;bs=material.node_tree.nodes.get('Principled BSDF')
        if not bs or not bs.inputs['Base Color'].is_linked:continue
        node=bs.inputs['Base Color'].links[0].from_node;source=getattr(node,'image',None)
        if source is None:continue
        image=source.copy();image.name=label;node.image=image;width,height=image.size
        data=np.empty(width*height*4,dtype=np.float32);image.pixels.foreach_get(data);data=data.reshape(height,width,4)
        slot_index=list(obj.data.materials).index(material);affected=0
        for triangle in obj.data.loop_triangles:
            if triangle.material_index!=slot_index:continue
            positions=q[np.array(triangle.vertices)];tip=mask(positions)
            if tip.max()<=0:continue
            coordinates=uv[np.array(triangle.loops)]*np.array([width-1,height-1]);lo=np.maximum(np.floor(coordinates.min(0)).astype(int),0);hi=np.minimum(np.ceil(coordinates.max(0)).astype(int),[width-1,height-1])
            if np.any(hi<lo):continue
            a,b,c=coordinates;v0=b-a;v1=c-a;den=v0[0]*v1[1]-v0[1]*v1[0]
            if abs(den)<1e-9:continue
            xx,yy=np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1));delta=np.stack([xx-a[0],yy-a[1]],axis=-1)
            u=(delta[...,0]*v1[1]-delta[...,1]*v1[0])/den;v=(v0[0]*delta[...,1]-v0[1]*delta[...,0])/den
            inside=(u>=0)&(v>=0)&(u+v<=1);amount=((1-u-v)*tip[0]+u*tip[1]+v*tip[2])*inside
            pixels=data[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3]
            pixels[:]=pixels*(1-.88*amount[...,None])+np.array(target_color)*(.88*amount[...,None]);affected+=int(np.count_nonzero(amount))
        image.pixels.foreach_set(data.ravel());image.update();image.pack()
        print('LOCAL_ATLAS_REPAIR',label,affected,'native atlas dimensions',width,height,flush=True)

def repair_local_claw_color(obj):
    paint_local_atlas(obj,'Authored_local_short_dark_claws',local_claw_mask,[.18,.22,.20])

def repair_local_irises(obj):
    record=layout()['heads'][0];origin=np.array(record['control'][-1]);rotation=np.array(record['headRotation'])
    def mask(q):
        local=(q-origin)@rotation
        distance=np.minimum(((local[:,0]+.030)/.0048)**2,((local[:,0]-.058)/.0048)**2)+((local[:,2]-.092)/.0038)**2
        return P.smooth((1-distance)/.45)*P.smooth((-.08-local[:,1])/.025)
    paint_local_atlas(obj,'Authored_local_iris_contrast',mask,[.07,.10,.085])

def assemble_preview(mothers,out,fuse=False,modular=False,recipe=False):
    assert not modular or fuse,'Modular body requires the reviewed bounded root tissue'
    anatomy=layout();parts=[];repair_local_irises(mothers['headneck'])
    trunk=mothers['trunk'].copy();trunk.data=mothers['trunk'].data.copy();bpy.context.collection.objects.link(trunk);trunk.hide_set(False);trunk.hide_render=False;parts.append(trunk)
    for kind,key in [('headneck','heads'),('tail','tails')]:
        source=mothers[kind];centers,weights=chain_weights(points(source),anatomy[key][0],kind=='headneck')
        for i,record in enumerate(anatomy[key]):parts.append(deform_native(source,kind+'_'+str(i),weights,chain_matrices(anatomy[key][0],record,kind=='headneck')))
    source=mothers['leg'];repair_local_claw_color(source);shorten_local_claws(source);q=points(source);minimum=q[:,2].min()
    # Only two bounded projecting tips change; complete imported normals are
    # transported through that deformation, then the sole receives translation.
    for v in source.data.vertices:v.co.z-=minimum
    for pair,x in enumerate([-.368,.3765,.732,1.4765]):
        for side in [-1,1]:
            obj=source.copy();obj.data=source.data.copy();bpy.context.collection.objects.link(obj);obj.name='native_leg_'+str(pair)+'_'+str(side);obj.hide_set(False);obj.hide_render=False
            translation=np.array([x+.368,0,0]);moved=points(source)+translation
            obj.data.vertices.foreach_set('co',moved.astype(np.float32).ravel())
            if side>0:mirror_native_y(obj)
            parts.append(obj)
    for obj in mothers.values():obj.hide_set(True);obj.hide_render=True
    if fuse:
        parts,patch=bounded_volume_tissue(parts)
        canonical_junction_pigment(patch)
        P.export(patch,out/'shared-root-tissue.glb')
        if modular:export_modular_mothers(mothers,patch,out,anatomy)
        parts.append(patch)
        if recipe:
            for kind in ['body','leg','headneck','tail']:(out/'modular'/(kind+'_norm.glb')).replace(out/(kind+'_norm.glb'))
            (out/'anatomy.json').write_text(json.dumps(anatomy,indent=2));return
    actual=P.join(parts);actual.name='Native_High_static_assembly_local_junctions_pending'
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'native-assembly.blend'))
    P.render(actual,out)
    (out/'anatomy.json').write_text(json.dumps(anatomy,indent=2))
    P.export(actual,out/'native-assembly.glb')
    print('NATIVE_ASSEMBLY',json.dumps({'faces':len(actual.data.polygons),'fullVoxelRemesh':False,'junctionFairing':'pending bounded root tissue'}),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--raw-root',required=True);ap.add_argument('--reference-root',default='');ap.add_argument('--output-dir',required=True);ap.add_argument('--register-only',action='store_true');ap.add_argument('--from-registered');ap.add_argument('--native-layout',action='store_true');ap.add_argument('--fuse',action='store_true');ap.add_argument('--export-mothers',action='store_true');ap.add_argument('--recipe',action='store_true');ap.add_argument('--trunk');ap.add_argument('--leg');ap.add_argument('--headneck');ap.add_argument('--tail');a=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    raw=Path(a.raw_root).resolve();refs=Path(a.reference_root).resolve();out=Path(a.output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    if a.recipe:a.native_layout=True;a.fuse=True;a.export_mothers=True
    if a.from_registered:
        bpy.ops.wm.open_mainfile(filepath=str(Path(a.from_registered).resolve()))
        mothers={kind:bpy.data.objects['Native_High_'+kind] for kind in ['trunk','leg','headneck','tail']}
        assemble_preview(mothers,out,a.fuse,a.export_mothers,a.recipe);return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mothers={};receipts={};registrations={}
    # Versioned public source records travel with the recipe. Rebuilds require
    # only the four declared raw GLBs, never ignored per-download sidecars.
    manifest=Path(__file__).resolve().parents[1]/'provenance'/'tianwu-native-sources.json'
    public_sources=json.loads(manifest.read_text())['sources']
    for kind in ['trunk','leg','headneck','tail']:
        path=Path(getattr(a,kind)).resolve() if getattr(a,kind) else raw/('tianwu-production-20261115-'+kind+'-high')/'base_high_pbr.glb'
        receipt=public_sources[kind];sha=hashlib.sha256(path.read_bytes()).hexdigest()
        assert sha==receipt['sourceSha256']==NATIVE_REGISTRATION[kind][0],'Native source SHA mismatch: '+kind
        assert receipt['tier']=='Gen-2.5-Extreme-High' and path.stat().st_size==receipt['bytes']
        native=P.join(P.load(path));native.name='Native_High_'+kind
        if a.native_layout:
            expected,transform=NATIVE_REGISTRATION[kind]
            assert sha==expected,'Native layout source SHA mismatch: '+kind
            matrix=np.array(transform);singular=np.linalg.svd(matrix[:3,:3],compute_uv=False)
            assert np.linalg.det(matrix[:3,:3])>0 and np.ptp(singular)<1e-9
            native.matrix_world=Matrix(matrix)
            bpy.context.view_layer.objects.active=native;bpy.ops.object.select_all(action='DESELECT');native.select_set(True)
            bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
            registrations[kind]={'matrix':transform,'uniformScale':float(singular[0]),'mirrored':False,'sourceDefined':True}
        else:
            reference=P.join(P.load(refs/kind/'reference.glb'));reference.name='Registration_reference_'+kind
            registrations[kind]=align(native,reference,kind)
            bpy.data.objects.remove(reference,do_unlink=True)
        receipts[kind]=receipt
        mothers[kind]=native
        native.hide_render=True;native.hide_set(True)
        print('NATIVE_REGISTRATION',kind,json.dumps(registrations[kind]),flush=True)
    # Registration evidence contains the original textured topology only.
    if not a.recipe:
        for kind,obj in mothers.items():
            obj.hide_set(False);REF.render(obj,out/'registered'/kind,closeups=True);obj.hide_set(True)
        bpy.ops.wm.save_as_mainfile(filepath=str(out/'registered-mothers.blend'))
    (out/'native-source-registration.json').write_text(json.dumps({'sources':receipts,'registration':registrations,'fullVoxelRemesh':False,'apiCalls':0},indent=2))
    if a.register_only:return
    if a.native_layout:
        assemble_preview(mothers,out,a.fuse,a.export_mothers,a.recipe);return
    raise RuntimeError('Assembly requires source-defined native layout or reviewed registered mothers')

if __name__=='__main__':main()
