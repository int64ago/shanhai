"""Independent actual GLB topology and spatial intersection evidence; no export."""
import argparse
import json
from pathlib import Path
import sys
import struct
from collections import Counter
import numpy as np
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');p.add_argument('--compare');a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=a.source,disable_bone_shape=True)
objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
bpy.ops.object.select_all(action='DESELECT')
for o in objects:o.select_set(True)
bpy.context.view_layer.objects.active=objects[0];bpy.ops.object.join();obj=objects[0]
bm=bmesh.new();bm.from_mesh(obj.data);bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
components=[];todo=set(bm.verts)
while todo:
    queue=[todo.pop()];vs=set(queue)
    while queue:
        v=queue.pop()
        for e in v.link_edges:
            other=e.other_vert(v)
            if other in todo:todo.remove(other);queue.append(other);vs.add(other)
    faces=set(f for v in vs for f in v.link_faces)
    components.append(dict(vertices=len(vs),faces=len(faces),bounds=[[min(v.co[k] for v in vs),max(v.co[k] for v in vs)] for k in range(3)],materialIndices=sorted(set(f.material_index for f in faces))))
bm.to_mesh(obj.data);bm.free();mesh=obj.data;mesh.calc_loop_triangles()
points=[v.co.copy() for v in mesh.vertices];triangles=[tuple(t.vertices) for t in mesh.loop_triangles]
sets=[set(t) for t in triangles];tree=BVHTree.FromPolygons(points,triangles,all_triangles=True)
pairs=[];counts={}
for i,j in tree.overlap(tree):
    if i>=j or sets[i]&sets[j]:continue
    ma=mesh.polygons[mesh.loop_triangles[i].polygon_index].material_index;mb=mesh.polygons[mesh.loop_triangles[j].polygon_index].material_index
    key=','.join(map(str,sorted([ma,mb])));counts[key]=counts.get(key,0)+1
    if len(pairs)<60:
        coords=[points[k] for k in triangles[i]+triangles[j]]
        pairs.append(dict(triangles=[i,j],materials=[ma,mb],center=list(sum(coords,Vector())/6),maxEdge=max((points[x]-points[y]).length for t in [triangles[i],triangles[j]] for x,y in zip(t,t[1:]+t[:1]))))
head_gaps=[]
layout=Path(a.source).parent/'layout.json'
if layout.exists():
    heads=json.loads(layout.read_text())['heads'];groups={h['number']:[] for h in heads}
    for tri in mesh.loop_triangles:
        material=mesh.materials[mesh.polygons[tri.polygon_index].material_index]
        if not material.name.startswith('Native_High'):continue
        center=sum((points[i] for i in tri.vertices),Vector())/3
        head=min(heads,key=lambda h:(center-Vector(h['top'])-Vector((0,0,.2))).length_squared)
        groups[head['number']].append(tuple(tri.vertices))
    surfaces={}
    for number,faces in groups.items():
        ids=sorted(set(i for f in faces for i in f));lookup={vi:j for j,vi in enumerate(ids)}
        vertices=[points[i] for i in ids]
        surfaces[number]=(vertices,BVHTree.FromPolygons(vertices,[tuple(lookup[i] for i in f) for f in faces],all_triangles=True))
    for i,head in enumerate(heads):
        for other in heads[i+1:]:
            if (Vector(head['top'])-Vector(other['top'])).length>1.2:continue
            vertices,tree=surfaces[head['number']];ov,ot=surfaces[other['number']]
            gap=min(min(ot.find_nearest(v)[3] for v in vertices),min(tree.find_nearest(v)[3] for v in ov))
            head_gaps.append(dict(heads=[head['number'],other['number']],minimumSampledSurfaceGap=gap))
report=dict(source=str(Path(a.source).resolve()),actualImported=True,uvLayers=[layer.name for layer in mesh.uv_layers],components=sorted(components,key=lambda x:-x['vertices']),materials=[m.name for m in mesh.materials],overlapsByMaterial=counts,overlapPairs=pairs,nearbyNativeHeadGaps=head_gaps,headGapScope='Bidirectional native head vertex-to-other-head-triangle distances; triangle overlaps are independently listed above')
if a.compare:
    def load(path):
        data=Path(path).read_bytes();size=struct.unpack_from('<I',data,12)[0]
        return json.loads(data[20:20+size]),data[28+size:]
    def accessor(g,blob,index):
        item=g['accessors'][index];view=g['bufferViews'][item['bufferView']]
        size={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[item['type']]*{5121:1,5123:2,5125:4,5126:4}[item['componentType']]
        offset=view.get('byteOffset',0)+item.get('byteOffset',0);stride=view.get('byteStride',size)
        return b''.join(blob[offset+i*stride:offset+i*stride+size] for i in range(item['count']))
    old,old_blob=load(a.compare);new,new_blob=load(a.source);checks=[]
    for before,after in zip(old['meshes'][0]['primitives'],new['meshes'][0]['primitives']):
        name=old['materials'][before['material']]['name'];same={}
        for key in ['POSITION','NORMAL','TEXCOORD_0']:
            same[key]=accessor(old,old_blob,before['attributes'][key])==accessor(new,new_blob,after['attributes'][key])
        same['indices']=accessor(old,old_blob,before['indices'])==accessor(new,new_blob,after['indices'])
        old_positions=np.frombuffer(accessor(old,old_blob,before['attributes']['POSITION']),dtype='<f4').reshape(-1,3)
        new_positions=np.frombuffer(accessor(new,new_blob,after['attributes']['POSITION']),dtype='<f4').reshape(-1,3)
        old_set=Counter(map(tuple,np.round(old_positions,5)));new_set=Counter(map(tuple,np.round(new_positions,5)))
        position_set_equal=old_set==new_set
        assert position_set_equal,(name,'Geometry vertex positions changed',len(old_set-new_set),len(new_set-old_set))
        checks.append(dict(material=name,identicalAttributeBytes=same,identicalUnorderedVertexPositionsAtMetres=1e-5,vertexPositionsPreserved=position_set_equal))
    report['approvedGeometryComparison']=dict(source=a.compare,allGeometryAndUVBytesIdentical=all(all(c['identicalAttributeBytes'].values()) for c in checks),allVertexPositionsPreserved=True,checks=checks)
Path(a.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
