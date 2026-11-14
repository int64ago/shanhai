"""Bounded offline native Zhulong assessment; rejects fused-coil correction.
Run Blender --background --factory-startup --disable-autoexec --python-exit-code 1.
All imported GLB data stays under raw; recipes remain in pipeline/blender.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
from pathlib import Path
import bpy
import bmesh
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(source):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source), disable_bone_shape=True)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert meshes and not any(o.type == 'ARMATURE' for o in bpy.context.scene.objects)
    points = np.array([tuple(o.matrix_world @ v.co) for o in meshes for v in o.data.vertices])
    lo, hi = points.min(axis=0), points.max(axis=0)
    scale = 1 / max(hi-lo)
    origin = np.array(((lo[0]+hi[0])/2, (lo[1]+hi[1])/2, lo[2]))
    return meshes, scale, origin


def topology(bm):
    pending=set(bm.verts); components=0
    while pending:
        components+=1; stack=[pending.pop()]
        while stack:
            v=stack.pop()
            for e in v.link_edges:
                n=e.other_vert(v)
                if n in pending:
                    pending.remove(n); stack.append(n)
    boundary={e for e in bm.edges if e.is_boundary}
    boundary_components=0
    while boundary:
        boundary_components+=1; stack=[boundary.pop()]
        while stack:
            edge=stack.pop()
            for v in edge.verts:
                for e in v.link_edges:
                    if e in boundary:
                        boundary.remove(e); stack.append(e)
    chi=len(bm.verts)-len(bm.edges)+len(bm.faces)
    return dict(vertices=len(bm.verts), edges=len(bm.edges), faces=len(bm.faces),
                components=components, eulerCharacteristic=chi,
                boundaryEdges=sum(e.is_boundary for e in bm.edges),
                boundaryComponents=boundary_components,
                nonmanifoldInteriorEdges=sum(not e.is_manifold and not e.is_boundary for e in bm.edges),
                orientableGenusIfManifold=(2*components-boundary_components-chi)/2)


def assess(meshes, scale, origin):
    reports = []
    for obj in meshes:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        for v in bm.verts:
            v.co = (np.array(tuple(obj.matrix_world @ v.co))-origin)*scale
        weld_checks=[]
        for tolerance in (1e-8,1e-7,1e-6):
            probe=bm.copy()
            bmesh.ops.remove_doubles(probe,verts=list(probe.verts),dist=tolerance)
            weld_checks.append(dict(tolerance=tolerance,**topology(probe)))
            probe.free()
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
        clipped=[]
        for part,clear_inner,clear_outer in [('body_below_neck',False,True),('upper_neck_and_head',True,False)]:
            probe=bm.copy()
            bmesh.ops.bisect_plane(probe,geom=list(probe.verts)+list(probe.edges)+list(probe.faces),
                dist=1e-8,plane_co=Vector((0,0,.2)),plane_no=Vector((0,0,1)),
                clear_inner=clear_inner,clear_outer=clear_outer)
            clipped.append(dict(region=part,planeZ=.2,**topology(probe)))
            probe.free()
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        pending = set(bm.verts)
        components = []
        while pending:
            stack = [pending.pop()]
            island = []
            while stack:
                v = stack.pop()
                island.append(v)
                for edge in v.link_edges:
                    n = edge.other_vert(v)
                    if n in pending:
                        pending.remove(n)
                        stack.append(n)
            components.append(dict(vertices=len(island), min=[min(v.co[i] for v in island) for i in range(3)],
                                   max=[max(v.co[i] for v in island) for i in range(3)]))
        slices = []
        for z in np.arange(.025, .76, .025):
            # Edge intersections retain topological contour identity; contacts
            # cannot be hidden by projecting to a point cloud or remeshing.
            hits = {}
            edge_graph = {}
            for edge in bm.edges:
                a,b = edge.verts
                if (a.co.z <= z < b.co.z) or (b.co.z <= z < a.co.z):
                    hits[edge] = a.co.lerp(b.co, (z-a.co.z)/(b.co.z-a.co.z))
                    edge_graph[edge] = set()
            for face in bm.faces:
                cross = [e for e in face.edges if e in hits]
                if len(cross) == 2:
                    edge_graph[cross[0]].add(cross[1]); edge_graph[cross[1]].add(cross[0])
            unseen = set(hits)
            contours = []
            while unseen:
                stack = [unseen.pop()]; ring = []
                while stack:
                    e=stack.pop(); ring.append(hits[e])
                    for n in edge_graph[e]:
                        if n in unseen:
                            unseen.remove(n); stack.append(n)
                p=np.array([tuple(v) for v in ring])
                contours.append(dict(points=len(p), min=p.min(axis=0).tolist(), max=p.max(axis=0).tolist(), mean=p.mean(axis=0).tolist()))
            slices.append(dict(z=float(z), contours=sorted(contours, key=lambda c:-c['points'])))
        reports.append(dict(name=obj.name, vertices=len(obj.data.vertices), polygons=len(obj.data.polygons),
            weldedVertices=len(bm.verts), edges=len(bm.edges), faces=len(bm.faces),
            eulerCharacteristic=len(bm.verts)-len(bm.edges)+len(bm.faces),
            boundaryEdges=sum(e.is_boundary for e in bm.edges), nonmanifoldEdges=sum(not e.is_manifold for e in bm.edges),
            components=sorted(components,key=lambda x:-x['vertices']), weldChecks=weld_checks,
            clippedRegionChecks=clipped, slices=slices))
        bm.free()
    return reports


def native_digest(meshes):
    result=hashlib.sha256()
    for obj in meshes:
        mesh=obj.data
        result.update(repr(([tuple(v.co) for v in mesh.vertices],
            [tuple(p.vertices) for p in mesh.polygons],
            [[tuple(v.uv) for v in uv.data] for uv in mesh.uv_layers],
            [tuple(n.vector) for n in mesh.corner_normals],
            [p.material_index for p in mesh.polygons])).encode())
    return result.hexdigest()


def embedded_images(path):
    import struct
    data=path.read_bytes()
    assert data[:4]==b'glTF'
    json_length=struct.unpack_from('<I',data,12)[0]
    doc=json.loads(data[20:20+json_length])
    binary_start=20+json_length+8
    result=[]
    for image in doc.get('images',[]):
        view=doc['bufferViews'][image['bufferView']]
        start=binary_start+view.get('byteOffset',0)
        payload=data[start:start+view['byteLength']]
        result.append(dict(mimeType=image.get('mimeType'),bytes=len(payload),
                           sha256=hashlib.sha256(payload).hexdigest()))
    return result


def world_corners(meshes):
    records=[]
    for obj in meshes:
        mesh=obj.data
        normal_matrix=obj.matrix_world.to_3x3().inverted().transposed()
        for poly in mesh.polygons:
            assert len(poly.vertices)==3
            for li in poly.loop_indices:
                point=obj.matrix_world@mesh.vertices[mesh.loops[li].vertex_index].co
                normal=normal_matrix@mesh.corner_normals[li].vector
                if normal.length>1e-15:
                    normal.normalize()
                records.append(tuple(point)+tuple(mesh.uv_layers[0].data[li].uv)+tuple(normal))
    return np.array(records)


def export_reimport_evidence(source,meshes,scale,origin,out):
    # Preserve the entire source binary payload and all material/mesh JSON.
    # Only serialize a new positive uniform glTF root. Blender's general glTF
    # exporter split native corner normals in the retained diagnostic exports;
    # a source-only evidence copy must avoid that unnecessary round trip.
    import struct
    digest_before=native_digest(meshes)
    imported=list(bpy.context.scene.objects)
    root=bpy.data.objects.new('review_uniform_normalization',None)
    bpy.context.scene.collection.objects.link(root)
    root.scale=(scale,)*3; root.location=Vector(-origin*scale)
    for obj in imported:
        if obj.parent is None:
            obj.parent=root
    bpy.context.view_layer.update()
    expected=world_corners(meshes)
    source_vertices=sum(len(o.data.vertices) for o in meshes)
    data=source.read_bytes()
    json_length=struct.unpack_from('<I',data,12)[0]
    document=json.loads(data[20:20+json_length])
    preserved_chunks=data[20+json_length:]
    for scene in document['scenes']:
        index=len(document['nodes'])
        document['nodes'].append(dict(name='review_uniform_normalization',children=scene['nodes'],
            scale=[scale]*3,translation=[float(-origin[0]*scale),float(-origin[2]*scale),float(origin[1]*scale)]))
        scene['nodes']=[index]
    encoded=json.dumps(document,separators=(',',':')).encode()
    encoded+=b' '*((-len(encoded))%4)
    payload=struct.pack('<III',0x46546c67,2,20+len(encoded)+len(preserved_chunks))
    payload+=struct.pack('<II',len(encoded),0x4e4f534a)+encoded+preserved_chunks
    exported=out/'unmodified_native_evidence.glb'
    exported.write_bytes(payload)
    assert payload[20+len(encoded):]==preserved_chunks
    assert digest_before==native_digest(meshes)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(exported),disable_bone_shape=True)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    actual=world_corners(meshes)
    assert expected.shape==actual.shape, 'Triangle corner count changed'
    errors=np.max(np.abs(expected-actual),axis=0)
    assert float(max(errors))<1e-5, 'Position, UV, winding order or normal changed'
    assert digest_before==native_digest(meshes), 'Native local surface attributes changed'
    return meshes,dict(path=str(exported),sha256=sha(exported),
        nativeSurfaceDigestBefore=digest_before,nativeSurfaceDigestAfterReimport=native_digest(meshes),
        originalBinaryChunksSha256=hashlib.sha256(preserved_chunks).hexdigest(),binaryChunksUnchanged=True,
        sourceVertices=source_vertices,reimportVertices=sum(len(o.data.vertices) for o in meshes),
        triangleCornersCompared=int(len(actual)),
        reimportMaxPositionError=float(max(errors[:3])),reimportMaxUvError=float(max(errors[3:5])),
        reimportMaxNormalComponentError=float(max(errors[5:])),
        geometryEdits='positive uniform root normalization only; direct GLB serialization preserves all original mesh/material JSON and binary chunks',
        deformedCandidate=False,normalRecomputation=False,embeddedImages=embedded_images(exported))


def render_assessment(meshes, scale, origin, out, reimported=False):
    if not reimported:
        # Source geometry and its normals remain untouched. Object root is uniform.
        root=bpy.data.objects.new('review_uniform_normalization', None)
        bpy.context.scene.collection.objects.link(root)
        root.scale=(scale,)*3
        root.location=Vector(-origin*scale)
        for obj in list(bpy.context.scene.objects):
            if obj != root and obj.parent is None:
                obj.parent=root
    scene=bpy.context.scene
    scene.render.engine='CYCLES'; scene.cycles.samples=24
    scene.cycles.use_denoising=True
    scene.render.resolution_x=scene.render.resolution_y=900
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.view_settings.view_transform='AgX'
    scene.world=bpy.data.worlds.new('Neutral assessment world'); scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.55,.57,.60,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.8
    for i,(position,power,size) in enumerate([((2,-3,4),240,3),((-3,1,2),210,3),((1,3,3),180,3)]):
        light=bpy.data.objects.new('Softbox'+str(i),bpy.data.lights.new('Softbox'+str(i),'AREA'))
        scene.collection.objects.link(light); light.location=position
        light.data.energy=power; light.data.size=size
        light.rotation_euler=(Vector((0,0,.3))-light.location).to_track_quat('-Z','Y').to_euler()
    cam=bpy.data.objects.new('Assessment camera',bpy.data.cameras.new('Assessment camera'))
    scene.collection.objects.link(cam); cam.data.type='ORTHO'; scene.camera=cam
    specs=[
        ('source_top',(0,0,.12),(0,0,1),1.15),
        ('source_bottom',(0,0,.12),(0,0,-1),1.15),
        ('source_neck_coil_contact',(0,-.03,.14),(.5,-1,.35),.52),
    ]
    if reimported:
        specs+=[
            ('view_front',(0,0,.348),(0,-1,.04),1.15),
            ('view_back',(0,0,.348),(0,1,.04),1.15),
            ('view_side',(0,0,.348),(1,0,.04),1.15),
            ('view_34',(0,0,.348),(.65,-.75,.3),1.2),
            ('close_face',(-.03,-.30,.56),(0,-1,.04),.34),
            ('close_neck',(-.03,-.25,.33),(1,-.35,.12),.53),
            ('close_whole_body',(0,.02,.105),(.3,-.5,1),1.1),
            ('close_tail',(.32,.025,.055),(0,-.3,1),.94),
        ]
    evidence=[]
    for name,target,direction,ortho in specs:
        target=Vector(target); cam.location=target+Vector(direction).normalized()*3
        cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.ortho_scale=ortho; scene.render.filepath=str(out/(name+'.png'))
        bpy.ops.render.render(write_still=True)
        evidence.append(dict(path=name+'.png',sha256=sha(out/(name+'.png')),
                             target=list(target),direction=list(direction),orthoScale=ortho))
    if reimported:
        import shutil
        import subprocess
        magick=shutil.which('magick')
        if magick:
            contact=out/'contact_four_views.png'
            subprocess.run([magick,'(',str(out/'view_front.png'),str(out/'view_back.png'),'+append',')',
                '(',str(out/'view_side.png'),str(out/'view_34.png'),'+append',')','-append',str(contact)],
                check=True,timeout=60)
            evidence.append(dict(path=contact.name,sha256=sha(contact)))
    return evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True); parser.add_argument('--output-dir',required=True)
    parser.add_argument('--export-source-evidence',action='store_true',
                        help='Export and reimport the unmodified native source, never a corrected candidate')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source=Path(args.source).resolve(strict=True); out=Path(args.output_dir).resolve()
    assert source.is_relative_to(ROOT/'raw') and source.suffix=='.glb'
    assert out.is_relative_to(ROOT/'raw/_build')
    out.mkdir(parents=True,exist_ok=False)
    before=sha(source)
    assert before=='c0d9ee838e590ad85a376d5dcc0c4e01dc94c547037b9feab2154133870c57c9'
    meshes,scale,origin=load(source)
    report=dict(source=str(source), sourceSha256=before, normalization=dict(scale=scale, origin=origin.tolist()),
                assessment=assess(meshes,scale,origin), candidateAttempts=0, apiCalls=0)
    (out/'topology-assessment.json').write_text(json.dumps(report,indent=2)+'\n')
    print('ZHULONG_ASSESSMENT',json.dumps({k:v for k,v in report.items() if k!='assessment'}),flush=True)
    for r in report['assessment']:
        print('TOPOLOGY',json.dumps({k:v for k,v in r.items() if k!='slices'}),flush=True)
    if args.export_source_evidence:
        body=report['assessment'][0]['clippedRegionChecks'][0]
        assert body['region']=='body_below_neck' and body['orientableGenusIfManifold']>=1
        assert body['nonmanifoldInteriorEdges']==0 and body['boundaryComponents']==1
        report['sourceEmbeddedImages']=embedded_images(source)
        meshes,report['unmodifiedExport']=export_reimport_evidence(source,meshes,scale,origin,out)
        assert sorted(i['sha256'] for i in report['sourceEmbeddedImages'])==sorted(
            i['sha256'] for i in report['unmodifiedExport']['embeddedImages'])
        report['renders']=render_assessment(meshes,scale,origin,out,reimported=True)
        report['decision']='REJECT_BOUNDED_WHOLE_BEAST_CORRECTION_FUSED_COIL_TOPOLOGY'
        report['reason']='The lower body contains a native topological handle; positive-orientation injective deformation cannot separate the fused returning coil into an open shallow S without topology surgery.'
        report['candidateAttempts']=0
        report['correctionAttempts']=0
        report['usefulWholeBeastHighReference']=False
        report['acceptanceDecision']=None
        report['preservation']='Complete native head/hair/eyes/ears/chin, single tapered tail, UVs, all original PBR payloads, mesh attributes and local texture density are unchanged. No donor graft, neck shortening or uncoiling was attempted.'
        report['retainedSourceEvidenceDiagnostics']=[
            dict(directory=str(ROOT/'raw/_build/zhulong-native-v3-fused-coil-source-evidence-20261114'),
                 issue='General Blender export retained triangle count but split 20 native corner-normal seam vertices; failed index-count assumption before rendering.'),
            dict(directory=str(ROOT/'raw/_build/zhulong-native-v3-fused-coil-source-reimport-evidence-20261114'),
                 issue='General Blender export failed strict ordered corner-attribute roundtrip verification before rendering; never a deformed candidate.'),
        ]
        report['sourceSha256After']=sha(source)
        report['script']=dict(path=str(Path(__file__).resolve()),sha256=sha(Path(__file__).resolve()))
        (out/'source-evidence-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    else:
        render_assessment(meshes,scale,origin,out)
    assert before==sha(source)

if __name__=='__main__':
    main()
