"""Source-based Longzhi assembly: reviewed High body, repainted High head/tail.
The explicit placement recipe contains no source geometry. Reconstructs one
continuous skin; preserves donor UVs by local projection and labels skin regions
for the dedicated rig. Paid generation is never invoked here.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix,Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import prepare_longzhi_continuous as shared


def load(path,name):
    before=set(bpy.context.scene.objects);bpy.ops.import_scene.gltf(filepath=str(path));meshes=[o for o in bpy.context.scene.objects if o not in before and o.type=='MESH'];shared.select(meshes)
    if len(meshes)>1:bpy.ops.object.join()
    obj=bpy.context.object;bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);obj.name=name
    return obj


def refine_short_tail_roots(obj,regions,labels):
    """Fair the clay-confirmed basal grooves of tails 06 and 09.
    Vertex order/topology and points outside two 19cm neighborhoods stay fixed.
    """
    before=np.array([v.co[:] for v in obj.data.vertices],np.float64);positions=before.copy();mask=np.zeros(len(before))
    for r in regions:
        if r['name'] not in ('longzhi_tail_06','longzhi_tail_09'):continue
        root=Vector(r['root']);axis=(Vector(r['tip'])-root).normalized();center=root+axis*.065
        for v in obj.data.vertices:
            distance=(v.co-center).length
            mask[v.index]=max(mask[v.index],1-shared.smoothstep(distance/.19))
    edges=np.array([e.vertices[:] for e in obj.data.edges]);a,b=edges.T;degree=np.maximum(1,np.bincount(edges.ravel(),minlength=len(before)))[:,None]
    for iteration in range(240):
        sums=np.zeros_like(positions);np.add.at(sums,a,positions[b]);np.add.at(sums,b,positions[a]);positions+=.50*mask[:,None]*(sums/degree-positions)
    for v,p in zip(obj.data.vertices,positions):v.co=p
    obj.data.update()
    import bmesh
    bm=bmesh.new();bm.from_mesh(obj.data);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
    changed=np.linalg.norm(positions-before,axis=1)
    return {'regions':['longzhi_tail_06','longzhi_tail_09'],'method':'Clay-confirmed groove fairing before atlas bake, confined to two 19cm basal neighborhoods including their adjoining body skin; topology and vertices outside these neighborhoods are unchanged','changedVertices':int(np.sum(changed>1e-9)),'maximumDisplacementM':float(changed.max())}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--body',required=True,type=Path);ap.add_argument('--head',required=True,type=Path);ap.add_argument('--tail',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);ap.add_argument('--evidence-dir',type=Path);ap.add_argument('--voxel',type=float,default=.0018);ap.add_argument('--ratio',type=float,default=.07);args=ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    bpy.ops.wm.read_factory_settings(use_empty=True);plan=json.loads((Path(__file__).parent/'longzhi_layout.json').read_text());body=load(args.body,'longzhi_body_high')
    p=[v.co.copy() for v in body.data.vertices];lo=Vector(tuple(min(q[i] for q in p) for i in range(3)));hi=Vector(tuple(max(q[i] for q in p) for i in range(3)));center=(lo+hi)*.5;center.z=lo.z;factor=1/max(hi-lo)
    for vertex in body.data.vertices:vertex.co=(vertex.co-center)*factor
    body.data.update();master=load(args.head,'head_master');master.hide_render=True;master.hide_set(True);height=max(v.co.z for v in master.data.vertices);collar=.74*height;meshes=[body];anatomy=[]
    for i,item in enumerate(plan['heads'],1):
        obj=master.copy();obj.data=master.data.copy();obj.name=f'longzhi_head_{i:02d}';bpy.context.collection.objects.link(obj);obj.hide_render=False;obj.hide_set(False);rotation=Matrix(item['rotation']);root=Vector(item['root'])+Vector((0,.045,-.082));length=item['length']
        for vertex in obj.data.vertices:
            q=vertex.co.copy();q.z=q.z*length/collar if q.z<collar else q.z-collar+length
            vertex.co=root+rotation@q
        obj.data.update();meshes.append(obj);anatomy.append(dict(role='head',name=obj.name,root=list(root),collar=list(root+rotation@Vector((0,0,length))),tip=list(root+rotation@Vector((0,-.04,length+height-collar))),row=item['row']))
    bpy.data.objects.remove(master,do_unlink=True);master=load(args.tail,'tail_master');master.hide_render=True;master.hide_set(True)
    for i,item in enumerate(plan['tails'],1):
        obj=master.copy();obj.data=master.data.copy();obj.name=f'longzhi_tail_{i:02d}';bpy.context.collection.objects.link(obj);obj.hide_render=False;obj.hide_set(False);matrix=Matrix(item['matrix'])
        for vertex in obj.data.vertices:vertex.co=matrix@vertex.co
        obj.data.update();root=Vector(item['root']);shared.roots(obj,root,'tail',0);meshes.append(obj);anatomy.append(dict(role='tail',name=obj.name,root=list(root),tip=list(matrix@Vector((.8,0,.15)))))
    bpy.data.objects.remove(master,do_unlink=True)
    for obj in meshes:
        for index,material in enumerate(obj.data.materials):
            copied=material.copy();copied.name=obj.name+'__'+str(index);obj.data.materials[index]=copied
    obj,reference=shared.union(meshes,args.voxel,args.ratio);shared.transfer(obj,reference)
    names=['longzhi_body_high']+[region['name'] for region in anatomy];votes=np.zeros((len(obj.data.vertices),len(names)),dtype=np.uint16)
    for face in obj.data.polygons:
        name=obj.data.materials[face.material_index].name.split('__')[0];label=names.index(name)
        for index in face.vertices:votes[index,label]+=1
    labels=votes.argmax(axis=1).tolist();root_refinement=refine_short_tail_roots(obj,anatomy,labels);points=[list(v.co) for v in obj.data.vertices]
    from bake_longzhi_continuous_coat import bake
    coat=bake(obj,reference,anatomy)
    shared.select([obj]);obj.name='longzhi_continuous_skin';obj['source_roles']='High body, High head, High tail; disclosed local shape/coat derivatives';args.output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(args.output),export_format='GLB',use_selection=True,export_animations=False)
    adjacency=[[] for _ in obj.data.vertices]
    for edge in obj.data.edges:
        a,b=edge.vertices;adjacency[a].append(b);adjacency[b].append(a)
    unseen=set(range(len(adjacency)));components=[]
    while unseen:
        stack=[unseen.pop()];count=0
        while stack:
            index=stack.pop();count+=1
            for other in adjacency[index]:
                if other in unseen:unseen.remove(other);stack.append(other)
        components.append(count)
    import bmesh
    bm=bmesh.new();bm.from_mesh(obj.data);topology={'componentVertexCounts':sorted(components,reverse=True),'boundaryEdges':sum(e.is_boundary for e in bm.edges),'nonManifoldEdges':sum(not e.is_manifold for e in bm.edges)};bm.free()
    audit={'rootRefinement':root_refinement,'topology':topology,'beast':'longzhi','sources':{role:{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for role,path in [('body',args.body),('head',args.head),('tail',args.tail)]},'regions':anatomy,'regionNames':names,'restPoints':points,'regionLabels':labels,'coat':coat,'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons),'paidCalls':0,'accepted':False,'rigged':False}
    args.output.with_suffix('.regions.json').write_text(json.dumps(audit,indent=2)+'\n')
    if args.evidence_dir:
        args.evidence_dir.mkdir(parents=True,exist_ok=False);shared.render(obj,args.evidence_dir,1100);bpy.ops.wm.save_as_mainfile(filepath=str(args.evidence_dir/'assembled.blend'))

if __name__=='__main__':main()
