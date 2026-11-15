"""Bake locally repainted short neck fur onto the actual reviewed v5 High skull.
No geometry generation or paid calls. Explicit original UV sampling preserves
face/eyes; new UV plus tangent normal bake makes the neck coat reproducible.
"""
import argparse,hashlib,json,sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(args.input));objects=[o for o in bpy.context.scene.objects if o.type=='MESH'];bpy.ops.object.select_all(action='DESELECT')
    for o in objects:o.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    if len(objects)>1:bpy.ops.object.join()
    obj=bpy.context.object;bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    p=np.array([v.co[:] for v in obj.data.vertices]);lo=p.min(0);hi=p.max(0);factor=.13/(hi[0]-lo[0]);bottom=p[p[:,2]<lo[2]+.05*(hi[2]-lo[2])];center=bottom.mean(0);center[2]=lo[2]
    for vertex in obj.data.vertices:vertex.co=(vertex.co-Vector(center))*factor
    obj.data.update();source_uv=obj.data.uv_layers.active;source_uv.name='OriginalHighFaceUV'
    target_uv=obj.data.uv_layers.new(name='RepaintedHighAtlas');obj.data.uv_layers.active=target_uv
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.uv.smart_project(angle_limit=1.15,island_margin=.008);bpy.ops.object.mode_set(mode='OBJECT')
    def mathnode(nodes,links,operation,a,b=None):
        n=nodes.new('ShaderNodeMath');n.operation=operation
        for i,value in enumerate((a,b)):
            if value is None:continue
            if isinstance(value,(float,int)):n.inputs[i].default_value=value
            else:links.new(value,n.inputs[i])
        return n.outputs[0]
    def ramp(nodes,links,value,low,high):
        n=nodes.new('ShaderNodeMapRange');n.clamp=True;n.interpolation_type='SMOOTHERSTEP';n.inputs['From Min'].default_value=low;n.inputs['From Max'].default_value=high;links.new(value,n.inputs['Value']);return n.outputs['Result']
    for material in obj.data.materials:
        nodes=material.node_tree.nodes;links=material.node_tree.links;bsdf=next(n for n in nodes if n.type=='BSDF_PRINCIPLED');original=bsdf.inputs['Base Color'].links[0].from_node;old_uv=nodes.new('ShaderNodeUVMap');old_uv.uv_map='OriginalHighFaceUV';links.new(old_uv.outputs['UV'],original.inputs['Vector'])
        coord=nodes.new('ShaderNodeTexCoord');sep=nodes.new('ShaderNodeSeparateXYZ');links.new(coord.outputs['Generated'],sep.inputs[0]);geom=nodes.new('ShaderNodeNewGeometry');normal=nodes.new('ShaderNodeSeparateXYZ');links.new(geom.outputs['Normal'],normal.inputs[0]);front=mathnode(nodes,links,'MULTIPLY',normal.outputs['Y'],-1.);front=ramp(nodes,links,front,.15,.65)
        side=mathnode(nodes,links,'SUBTRACT',sep.outputs['X'],.5);side=mathnode(nodes,links,'ABSOLUTE',side);side=ramp(nodes,links,side,.12,.31);side=mathnode(nodes,links,'SUBTRACT',1.,side);white=mathnode(nodes,links,'MULTIPLY',front,side)
        mapping=nodes.new('ShaderNodeVectorMath');mapping.operation='MULTIPLY';mapping.inputs[1].default_value=(330,330,130);links.new(coord.outputs['Object'],mapping.inputs[0]);noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=1;noise.inputs['Detail'].default_value=2;noise.inputs['Roughness'].default_value=.72;links.new(mapping.outputs['Vector'],noise.inputs['Vector'])
        fur=nodes.new('ShaderNodeMixRGB');fur.inputs[1].default_value=(.31,.105,.03,1);fur.inputs[2].default_value=(.47,.205,.075,1);links.new(noise.outputs['Fac'],fur.inputs[0]);throat=nodes.new('ShaderNodeMixRGB');links.new(white,throat.inputs[0]);links.new(fur.outputs[0],throat.inputs[1]);throat.inputs[2].default_value=(.78,.72,.62,1)
        preserve=ramp(nodes,links,sep.outputs['Z'],.63,.80);mix=nodes.new('ShaderNodeMixRGB');links.new(preserve,mix.inputs[0]);links.new(throat.outputs[0],mix.inputs[1]);links.new(original.outputs['Color'],mix.inputs[2]);links.new(mix.outputs[0],bsdf.inputs['Base Color'])
        for name in ('Roughness','Metallic','Normal'):
            for link in list(bsdf.inputs[name].links):links.remove(link)
        bsdf.inputs['Roughness'].default_value=.88;bsdf.inputs['Metallic'].default_value=0
        bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.15;bump.inputs['Distance'].default_value=.00035;links.new(noise.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs['Normal'],bsdf.inputs['Normal'])
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=8;scene.render.bake.margin=8;scene.render.bake.use_pass_direct=False;scene.render.bake.use_pass_indirect=False;scene.render.bake.use_pass_color=True
    images={}
    for kind in ('DIFFUSE','NORMAL'):
        image=bpy.data.images.new('longzhi_high_neck_'+kind.lower(),width=2048,height=2048,alpha=False)
        if kind=='NORMAL':image.colorspace_settings.name='Non-Color'
        for material in obj.data.materials:
            node=material.node_tree.nodes.new('ShaderNodeTexImage');node.image=image;material.node_tree.nodes.active=node
        bpy.ops.object.bake(type=kind);image.pack();images[kind]=image
    material=bpy.data.materials.new('actual_High_fox_repainted_short_neck_fur');material.use_nodes=True;nodes=material.node_tree.nodes;links=material.node_tree.links;shader=nodes.get('Principled BSDF');shader.inputs['Roughness'].default_value=.88
    tex=nodes.new('ShaderNodeTexImage');tex.image=images['DIFFUSE'];links.new(tex.outputs['Color'],shader.inputs['Base Color']);texn=nodes.new('ShaderNodeTexImage');texn.image=images['NORMAL'];normal=nodes.new('ShaderNodeNormalMap');links.new(texn.outputs['Color'],normal.inputs['Color']);links.new(normal.outputs['Normal'],shader.inputs['Normal']);obj.data.materials.clear();obj.data.materials.append(material)
    obj.data.uv_layers.remove(obj.data.uv_layers['OriginalHighFaceUV']);target_uv=obj.data.uv_layers['RepaintedHighAtlas'];obj.data.uv_layers.active=target_uv;target_uv.active_render=True
    bpy.ops.export_scene.gltf(filepath=str(out/'head.glb'),export_format='GLB',export_animations=False)
    audit={'source':str(args.input),'sourceSha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons),'geometryChanges':'Only uniform normalization and root translation; actual High skull/neck topology retained.','newUv':True,'diffuseBaked':True,'tangentNormalBaked':True,'paidCalls':0,'accepted':False};(out/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    sys.path.insert(0,str(Path(__file__).resolve().parent));from prepare_longzhi_continuous import render;render(obj,out,1000);bpy.ops.wm.save_as_mainfile(filepath=str(out/'head.blend'))

if __name__=='__main__':main()
