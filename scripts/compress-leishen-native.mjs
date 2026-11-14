// Offline candidate only. Preserve native topology and all authored animation samples.
// node scripts/compress-leishen-native.mjs INPUT_RIG NEW_RAW_BUILD_DIRECTORY
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve, join, relative } from 'node:path'
import { mkdir, readFile, writeFile, realpath } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
const root=fileURLToPath(new URL('../',import.meta.url))
const require=createRequire(await realpath(join(root,'node_modules/@gltf-transform/cli/package.json')))
const {NodeIO}=require('@gltf-transform/core')
const {ALL_EXTENSIONS}=require('@gltf-transform/extensions')
const {dequantize,meshopt,textureCompress,dedup,prune}=require('@gltf-transform/functions')
const {MeshoptDecoder,MeshoptEncoder}=await import(pathToFileURL(require.resolve('meshoptimizer')).href)
const [inputArg,outArg,precisionArg]=process.argv.slice(2)
assert(!precisionArg||precisionArg==='--weight16')
const highPrecision=precisionArg==='--weight16'
assert(inputArg&&outArg,'Input rig and NEW output required')
const input=resolve(inputArg),out=resolve(outArg)
assert(!relative(join(root,'raw/_build'),out).startsWith('..'))
const hash=b=>createHash('sha256').update(b).digest('hex')
await mkdir(out,{recursive:false})
const candidate=join(out,'body.glb'),decoded=join(out,'decoded-for-qa.glb')
const args=[join(root,'node_modules/@gltf-transform/cli/bin/cli.js'),'optimize',input,candidate,'--compress','meshopt','--meshopt-level','medium','--texture-compress','webp','--texture-size','2048','--simplify','false','--flatten','false','--join','false','--weld','false','--resample','false','--palette','false','--instance','false']
if(highPrecision){
  await Promise.all([MeshoptEncoder.ready,MeshoptDecoder.ready])
  const sharp=require('sharp')
  const highIO=new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.decoder':MeshoptDecoder,'meshopt.encoder':MeshoptEncoder})
  const doc=await highIO.read(input)
  const settings={level:'medium',quantizeWeight:16,textureFormat:'webp',textureSize:2048,simplify:false,flatten:false,join:false,weld:false,resample:false,palette:false,instance:false}
  await writeFile(join(out,'compression-command.json'),JSON.stringify({executable:process.execPath,args:[fileURLToPath(import.meta.url),input,out,'--weight16'],cwd:root,settings,transforms:['dedup','prune','textureCompress(webp2048)','meshopt(medium,quantizeWeight16)']},null,2)+'\n')
  await doc.transform(dedup(),prune(),textureCompress({encoder:sharp,targetFormat:'webp',resize:[2048,2048]}),meshopt({encoder:MeshoptEncoder,level:'medium',quantizeWeight:16}))
  await highIO.write(candidate,doc)
  await writeFile(join(out,'compression.log'),'Meshopt MEDIUM with16-bit skin weights; WebP2048. No simplify/flatten/join/weld/resample/palette/instance.\n')
}else{
  await writeFile(join(out,'compression-command.json'),JSON.stringify({executable:process.execPath,args,cwd:root},null,2)+'\n')
  const result=spawnSync(process.execPath,args,{cwd:root,encoding:'utf8',timeout:180000})
  await writeFile(join(out,'compression.log'),(result.stdout??'')+(result.stderr??''))
  assert.equal(result.status,0,result.stderr)
}
await MeshoptDecoder.ready
const io=new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.decoder':MeshoptDecoder})
const original=await io.read(input),compressed=await io.read(candidate)
function animations(doc){return doc.getRoot().listAnimations().map(a=>({name:a.getName(),channels:a.listChannels().map(c=>({node:c.getTargetNode().getName(),path:c.getTargetPath(),interpolation:c.getSampler().getInterpolation(),input:hash(Buffer.from(c.getSampler().getInput().getArray().buffer,c.getSampler().getInput().getArray().byteOffset,c.getSampler().getInput().getArray().byteLength)),output:hash(Buffer.from(c.getSampler().getOutput().getArray().buffer,c.getSampler().getOutput().getArray().byteOffset,c.getSampler().getOutput().getArray().byteLength))})).sort((a,b)=>(a.node+a.path).localeCompare(b.node+b.path))})).sort((a,b)=>a.name.localeCompare(b.name))}
assert.deepEqual(animations(original),animations(compressed),'Authored cubic samplers must remain exact')
function structure(doc){return {meshes:doc.getRoot().listMeshes().map(m=>m.listPrimitives().map(p=>({vertices:p.getAttribute('POSITION').getCount(),triangles:p.getIndices().getCount()/3,semantics:p.listSemantics().sort()}))),skins:doc.getRoot().listSkins().map(s=>s.listJoints().map(j=>j.getName()))}}
assert.deepEqual(structure(original),structure(compressed),'Topology counts, attributes and bones changed')
function materials(doc){return doc.getRoot().listMaterials().map(m=>{const keys=['getName','getAlphaMode','getAlphaCutoff','getDoubleSided','getBaseColorFactor','getMetallicFactor','getRoughnessFactor','getNormalScale','getOcclusionStrength','getEmissiveFactor'];const d=Object.fromEntries(keys.map(k=>[k,m[k]()]));for(const slot of ['BaseColor','MetallicRoughness','Normal','Occlusion','Emissive']){const t=m['get'+slot+'Texture']();const info=m['get'+slot+'TextureInfo']();d[slot]=t?{name:t.getName(),texCoord:info.getTexCoord(),minFilter:info.getMinFilter(),magFilter:info.getMagFilter(),wrapS:info.getWrapS(),wrapT:info.getWrapT()}:null}return d})}
assert.deepEqual(materials(original),materials(compressed),'Material factors/slots/samplers changed')
const textures=compressed.getRoot().listTextures().map(t=>({name:t.getName(),mime:t.getMimeType(),size:t.getSize(),bytes:t.getImage().byteLength,sha256:hash(t.getImage())}))
assert(textures.length>0&&textures.every(t=>t.mime==='image/webp'&&Math.max(...t.size)<=2048))
const candidateBytes=await readFile(candidate)
assert(candidateBytes.length<15*1024*1024,'Budget exceeded')
// CPU evaluation derivative: decode quantized accessor values, remove only codec
// extensions. Quantization compensation node transforms/inverse binds remain.
await compressed.transform(dequantize())
compressed.disposeExtension('EXT_meshopt_compression')
await io.write(decoded,compressed)
const report={meshoptLevel:'medium',weightPrecisionBits:highPrecision?16:8,sourceRig:input,sourceRigSha256:hash(await readFile(input)),candidate,candidateSha256:hash(candidateBytes),candidateBytes:candidateBytes.length,decoded,decodedSha256:hash(await readFile(decoded)),scriptSha256:hash(await readFile(fileURLToPath(import.meta.url))),animationsPreservedExactly:true,structurePreserved:true,materialParametersSlotsAndSamplersPreserved:true,textures,candidateOnly:true,decodedDerivativeOnly:true}
await writeFile(join(out,'compression-audit.json'),JSON.stringify(report,null,2)+'\n')
console.log(JSON.stringify(report,null,2))
