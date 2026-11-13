// One localized palette correction. Run from the repository root, no server.
// node scripts/xingxing-correct-palette.mjs V5_INPUT_DIRECTORY NEW_OUTPUT_DIRECTORY
// Appends only a replacement diffuse PNG to immutable v5 rigged GLB bytes.
import assert from 'node:assert/strict'
import { readFile, writeFile, readdir, access, mkdir } from 'node:fs/promises'
import { resolve, join, dirname } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..')
const [inputDirectory,outputDirectory]=process.argv.slice(2)
assert(inputDirectory&&outputDirectory,'Reviewed v5 input and new empty output directories required')
const out=resolve(outputDirectory),old=resolve(inputDirectory)
assert.notEqual(out,old)
await mkdir(out,{recursive:false})
const hash=b=>createHash('sha256').update(b).digest('hex')
const exists=await access(join(out,'rigged.glb')).then(()=>true,()=>false)
assert(!exists,'One targeted correction only; v6 output already exists')
const packages=await readdir(join(root,'node_modules/.pnpm'))
const pkg=packages.find(n=>n.startsWith('sharp@0.35.5_'))
assert(pkg,'Use installed image encoder, never install')
const sharp=(await import(pathToFileURL(join(root,'node_modules/.pnpm',pkg,'node_modules/sharp/dist/index.mjs')))).default
const input=await readFile(join(old,'rigged.glb')),audit=JSON.parse(await readFile(join(old,'audit.json'),'utf8'))
assert.equal(audit.candidateSha256,'ac6d4b37cc359c72ced1ce207d4fa435ac8dac2c1ff23949ccb909d31f870eda')
assert.equal(hash(await readFile(audit.source)),audit.sourceSha256)
const jsonLen=input.readUInt32LE(12),j=JSON.parse(input.subarray(20,20+jsonLen)),originalJSON=JSON.stringify(j)
const binStart=20+jsonLen+8,bin=input.subarray(binStart)
const primitive=j.meshes[0].primitives[0]
const decode=ix=>{
 const a=j.accessors[ix],v=j.bufferViews[a.bufferView],size={SCALAR:1,VEC2:2,VEC3:3,VEC4:4,MAT4:16}[a.type]
 const bytes={5121:1,5123:2,5125:4,5126:4}[a.componentType],stride=v.byteStride??size*bytes,base=(v.byteOffset??0)+(a.byteOffset??0),out=[]
 const get={5121:o=>bin.readUInt8(o),5123:o=>bin.readUInt16LE(o),5125:o=>bin.readUInt32LE(o),5126:o=>bin.readFloatLE(o)}[a.componentType]
 for(let i=0;i<a.count;i++){const row=[];for(let k=0;k<size;k++)row.push(get(base+i*stride+k*bytes));out.push(row)}return out
}
const pos=decode(primitive.attributes.POSITION),uv=decode(primitive.attributes.TEXCOORD_0),indices=decode(primitive.indices).flat()
assert.equal(indices.length/3,50000)
const material=j.materials[primitive.material],imageIndex=j.textures[material.pbrMetallicRoughness.baseColorTexture.index].source
const image=j.images[imageIndex],view=j.bufferViews[image.bufferView]
const png=bin.subarray(view.byteOffset,view.byteOffset+view.byteLength)
const {data,info}=await sharp(png).ensureAlpha().raw().toBuffer({resolveWithObject:true})
const before=Buffer.from(data),w=info.width,h=info.height,scale=audit.sourceToRig.reviewToFinalUniformScale,height=1.35
const part=new Uint8Array(w*h),ears=new Uint8Array(w*h)
const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
const subtract=(a,b)=>a.map((v,i)=>v-b[i])
const definitions={
 face:{absXMax:.105*scale,minY:.735*height,minForwardZ:.035*scale},
 hands:audit.maskDefinitions.hands,
 feet:{maxY:.105*height},
 ears:{minAbsX:.105*scale,minY:.80*height},
 colorGate:'R-B>6, R-G>2, G>=B, source luminance>55/255; smooth full strength at R-B>=12,R-G>=5,L>=85/255',
 target:'neutral sRGB charcoal = 28 + .32*original_luminance_byte; mix by skin chroma/luminance gate; preserve dark eye/nose pixels and all original luminance variation',
 scope:'only spatial face/hand/foot UV texels passing warm bare-skin chroma and luminance; protected native ear texels override any overlap'
}
const spatial=p=>{
 let bits=0
 if(Math.abs(p[0])<definitions.face.absXMax&&p[1]>definitions.face.minY&&p[2]>definitions.face.minForwardZ)bits|=1
 for(const d of Object.values(definitions.hands))if(d.sign*p[0]>d.allowedSignedXMin&&dot(subtract(p,d.wrist),d.distalAxis)>d.allowedDistalProjectionMin)bits|=2
 if(p[1]<definitions.feet.maxY)bits|=4
 return bits
}
const ear=p=>Math.abs(p[0])>definitions.ears.minAbsX&&p[1]>definitions.ears.minY
let rasterTriangles=0
for(let n=0;n<indices.length;n+=3){
 const ids=indices.slice(n,n+3),ps=ids.map(i=>pos[i])
 if(!ps.some(p=>spatial(p)||ear(p)))continue
 rasterTriangles++
 const t=ids.map(i=>[uv[i][0]*w,uv[i][1]*h]),[a,b,c]=t
 const den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(Math.abs(den)<1e-9)continue
 const xmin=Math.max(0,Math.floor(Math.min(...t.map(p=>p[0])))),xmax=Math.min(w-1,Math.ceil(Math.max(...t.map(p=>p[0]))))
 const ymin=Math.max(0,Math.floor(Math.min(...t.map(p=>p[1])))),ymax=Math.min(h-1,Math.ceil(Math.max(...t.map(p=>p[1]))))
 for(let y=ymin;y<=ymax;y++)for(let x=xmin;x<=xmax;x++){
  const px=x+.5,py=y+.5,u=((b[1]-c[1])*(px-c[0])+(c[0]-b[0])*(py-c[1]))/den,v=((c[1]-a[1])*(px-c[0])+(a[0]-c[0])*(py-c[1]))/den,z=1-u-v
  if(u<-.00001||v<-.00001||z<-.00001)continue
  const p=[0,1,2].map(k=>u*ps[0][k]+v*ps[1][k]+z*ps[2][k]),i=y*w+x
  part[i]|=spatial(p);if(ear(p))ears[i]=1
 }
}
const smooth=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t)}
const changedMask=Buffer.alloc(w*h),partPreview=Buffer.alloc(w*h*3),earPreview=Buffer.from(ears).map(x=>x?255:0)
const stats={face:{pixels:0,changed:0,beforeLum:0,afterLum:0},hands:{pixels:0,changed:0,beforeLum:0,afterLum:0},feet:{pixels:0,changed:0,beforeLum:0,afterLum:0}}
let changed=0,earPixels=0,earChanges=0,outsideChanges=0,maskedPixels=0
for(let i=0;i<w*h;i++){
 const bit=part[i],offset=i*4,[r,g,b]=data.subarray(offset,offset+3),L=.2126*r+.7152*g+.0722*b
 if(ears[i])earPixels++
 if(bit)maskedPixels++
 const gate=bit&&!ears[i]&&g>=b?smooth(6,12,r-b)*smooth(2,5,r-g)*smooth(55,85,L):0
 let edit=false
 if(gate>0){
  const target=28+.32*L
  for(let k=0;k<3;k++){const value=Math.round(data[offset+k]*(1-gate)+target*gate);edit||=value!==data[offset+k];data[offset+k]=value}
 }
 if(edit){changed++;changedMask[i]=255;if(ears[i])earChanges++;if(!bit)outsideChanges++}
 for(const [name,flag]of [['face',1],['hands',2],['feet',4]])if(bit&flag){const s=stats[name];s.pixels++;if(edit){s.changed++;s.beforeLum+=L;s.afterLum+=.2126*data[offset]+.7152*data[offset+1]+.0722*data[offset+2]}}
 partPreview[i*3]=bit&1?220:0;partPreview[i*3+1]=bit&2?220:0;partPreview[i*3+2]=bit&4?220:0
}
assert.equal(earChanges,0);assert.equal(outsideChanges,0);assert(changed>1000)
for(const s of Object.values(stats)){s.meanChangedBeforeLum=s.beforeLum/s.changed;s.meanChangedAfterLum=s.afterLum/s.changed;delete s.beforeLum;delete s.afterLum;assert(s.changed>1000)}
const corrected=await sharp(data,{raw:{width:w,height:h,channels:4}}).png().toBuffer()
await writeFile(join(out,'diffuse-before.png'),png);await writeFile(join(out,'diffuse-charcoal.png'),corrected)
await sharp(partPreview,{raw:{width:w,height:h,channels:3}}).png().toFile(join(out,'uv-skin-regions.png'))
await sharp(changedMask,{raw:{width:w,height:h,channels:1}}).png().toFile(join(out,'uv-changed-texels.png'))
await sharp(earPreview,{raw:{width:w,height:h,channels:1}}).png().toFile(join(out,'uv-protected-ears.png'))
// Preserve every existing byte: append replacement image, changing only its view.
const pad4=b=>Buffer.concat([b,Buffer.alloc((4-b.length%4)%4)])
const originalBin=pad4(bin),replacement=pad4(corrected),newBin=Buffer.concat([originalBin,replacement])
view.byteOffset=originalBin.length;view.byteLength=corrected.length;j.buffers[0].byteLength=newBin.length
const json=Buffer.from(JSON.stringify(j)),jsonPadded=Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)])
const header=Buffer.alloc(12),jh=Buffer.alloc(8),bh=Buffer.alloc(8);header.writeUInt32LE(0x46546c67);header.writeUInt32LE(2,4);header.writeUInt32LE(12+8+jsonPadded.length+8+newBin.length,8);jh.writeUInt32LE(jsonPadded.length);jh.writeUInt32LE(0x4e4f534a,4);bh.writeUInt32LE(newBin.length);bh.writeUInt32LE(0x004e4942,4)
const result=Buffer.concat([header,jh,jsonPadded,bh,newBin])
const afterJSON=structuredClone(j),oldJSON=JSON.parse(originalJSON);afterJSON.bufferViews[image.bufferView]=oldJSON.bufferViews[image.bufferView];afterJSON.buffers=oldJSON.buffers
assert.equal(JSON.stringify(afterJSON),originalJSON,'Every non-diffuse glTF JSON property unchanged')
assert(newBin.subarray(0,bin.length).equals(bin),'All original geometry/UV/skin/animation/normal/ORM BIN bytes unchanged')
await writeFile(join(out,'rigged.glb'),result)
const correction={input:join(old,'rigged.glb'),inputSha256:hash(input),fallbackV5Sha256:audit.candidateSha256,rawSourceSha256:audit.sourceSha256,
 dimensions:[w,h],definitions,rasterTriangles,maskedPixels,changedPixels:changed,protectedEarPixels:earPixels,protectedEarChangedPixels:earChanges,outsideSpatialMaskChangedPixels:outsideChanges,
 stats,diffuseBeforeSha256:hash(png),diffuseAfterSha256:hash(corrected),geometryUVSkinAnimationUnchanged:true,otherMaterialImagesUnchanged:true,allOriginalBinBytesUnchanged:true,
 outputRiggedSha256:hash(result),attempts:1,productionAccepted:false}
audit.paletteCorrection=correction;audit.productionAccepted=false;delete audit.candidateSha256;delete audit.candidateBytes;delete audit.compressedBrowserQA;delete audit.visualReview
await writeFile(join(out,'audit.json'),JSON.stringify(audit,null,2)+'\n')
await writeFile(join(out,'texture-correction.json'),JSON.stringify(correction,null,2)+'\n')
for(const name of ['landmarks.json','masks.json','actions.json','weights.json'])await writeFile(join(out,name),await readFile(join(old,name)))
assert.equal(hash(await readFile(join(old,'rigged.glb'))),correction.inputSha256)
assert.equal(hash(await readFile(audit.source)),audit.sourceSha256)
console.log(JSON.stringify(correction,null,2))
