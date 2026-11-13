// Technical padding for the same single palette correction; no mapped texels change.
// node scripts/xingxing-pad-uv-gutters.mjs PALETTE_OUTPUT_DIRECTORY
import assert from 'node:assert/strict'
import {readFile,writeFile,readdir} from 'node:fs/promises'
import {dirname,resolve,join} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
import {createHash} from 'node:crypto'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),hash=b=>createHash('sha256').update(b).digest('hex')
assert(process.argv[2],'Existing single-pass palette output directory required')
const out=resolve(process.argv[2])
const pkg=(await readdir(join(root,'node_modules/.pnpm'))).find(n=>n.startsWith('sharp@0.35.5_'))
assert(pkg,'Use installed image encoder, never install')
const sharp=(await import(pathToFileURL(join(root,'node_modules/.pnpm',pkg,'node_modules/sharp/dist/index.mjs')))).default
const audit=JSON.parse(await readFile(join(out,'audit.json'),'utf8')),c=audit.paletteCorrection
assert(!c.uvGutterPadding,'Padding already completed; one correction only')
const original=await readFile(c.input);assert.equal(hash(original),c.inputSha256)
const jl=original.readUInt32LE(12),j=JSON.parse(original.subarray(20,20+jl)),bin=original.subarray(20+jl+8)
const decoded=await sharp(await readFile(join(out,'diffuse-charcoal.png'))).ensureAlpha().raw().toBuffer({resolveWithObject:true})
const rgba=decoded.data,before=Buffer.from(rgba),{width:w,height:h}=decoded.info
const changed=await sharp(join(out,'uv-changed-texels.png')).greyscale().raw().toBuffer()
const ear=await sharp(join(out,'uv-protected-ears.png')).greyscale().raw().toBuffer()
const read=ix=>{const a=j.accessors[ix],v=j.bufferViews[a.bufferView],n={SCALAR:1,VEC2:2}[a.type],s={5123:2,5125:4,5126:4}[a.componentType],stride=v.byteStride??n*s,base=(v.byteOffset??0)+(a.byteOffset??0),o=[];for(let i=0;i<a.count;i++){const row=[];for(let k=0;k<n;k++){const p=base+i*stride+k*s;row.push(a.componentType===5126?bin.readFloatLE(p):a.componentType===5123?bin.readUInt16LE(p):bin.readUInt32LE(p))}o.push(row)}return o}
const p=j.meshes[0].primitives[0],uv=read(p.attributes.TEXCOORD_0),ids=read(p.indices).flat(),covered=new Uint8Array(w*h)
for(let n=0;n<ids.length;n+=3){
 const [a,b,c]=ids.slice(n,n+3).map(i=>[uv[i][0]*w,uv[i][1]*h]),den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);if(Math.abs(den)<1e-9)continue
 const xmin=Math.max(0,Math.floor(Math.min(a[0],b[0],c[0]))),xmax=Math.min(w-1,Math.ceil(Math.max(a[0],b[0],c[0]))),ymin=Math.max(0,Math.floor(Math.min(a[1],b[1],c[1]))),ymax=Math.min(h-1,Math.ceil(Math.max(a[1],b[1],c[1])))
 for(let y=ymin;y<=ymax;y++)for(let x=xmin;x<=xmax;x++){const X=x+.5,Y=y+.5,u=((b[1]-c[1])*(X-c[0])+(c[0]-b[0])*(Y-c[1]))/den,v=((c[1]-a[1])*(X-c[0])+(a[0]-c[0])*(Y-c[1]))/den;if(u>=-.00001&&v>=-.00001&&u+v<=1.00001)covered[y*w+x]=1}
}
const distance=new Uint8Array(w*h),paddingMask=Buffer.alloc(w*h),neighbors=i=>[i%w?i-1:-1,i%w<w-1?i+1:-1,i>=w?i-w:-1,i<w*(h-1)?i+w:-1]
let frontier=[]
for(let i=0;i<covered.length;i++)if(changed[i]&&neighbors(i).some(k=>k>=0&&!covered[k]))frontier.push(i)
let count=0
for(let step=1;step<=8;step++){
 const next=[]
 for(const i of frontier)for(const k of neighbors(i)){
  if(k<0||covered[k]||distance[k]||ear[k])continue
  // Preserve gutters belonging to closer unedited fur/white markings/ears.
  const x=k%w,y=Math.floor(k/w);let blocked=false
  for(let dy=-step;dy<=step&&!blocked;dy++)for(let dx=-step;dx<=step;dx++){
   if(dx*dx+dy*dy>step*step||x+dx<0||x+dx>=w||y+dy<0||y+dy>=h)continue
   const v=(y+dy)*w+x+dx;if(covered[v]&&!changed[v]){blocked=true;break}
  }
  if(blocked)continue
  distance[k]=step;for(let channel=0;channel<4;channel++)rgba[k*4+channel]=rgba[i*4+channel]
  paddingMask[k]=255;next.push(k);count++
 }
 frontier=next
}
let mappedChanges=0,earChanges=0
for(let i=0;i<covered.length;i++)if(!rgba.subarray(i*4,i*4+4).equals(before.subarray(i*4,i*4+4))){if(covered[i])mappedChanges++;if(ear[i])earChanges++}
assert.equal(mappedChanges,0);assert.equal(earChanges,0);assert(count>100)
const png=await sharp(rgba,{raw:{width:w,height:h,channels:4}}).png().toBuffer()
await writeFile(join(out,'diffuse-charcoal.png'),png)
await sharp(paddingMask,{raw:{width:w,height:h,channels:1}}).png().toFile(join(out,'uv-unused-gutter-padding.png'))
const imageIndex=j.textures[j.materials[p.material].pbrMetallicRoughness.baseColorTexture.index].source,image=j.images[imageIndex],view=j.bufferViews[image.bufferView]
const pad4=b=>Buffer.concat([b,Buffer.alloc((4-b.length%4)%4)]),originalBin=pad4(bin),newBin=Buffer.concat([originalBin,pad4(png)])
view.byteOffset=originalBin.length;view.byteLength=png.length;j.buffers[0].byteLength=newBin.length
const jb=Buffer.from(JSON.stringify(j)),json=Buffer.concat([jb,Buffer.alloc((4-jb.length%4)%4,32)]),header=Buffer.alloc(12),jh=Buffer.alloc(8),bh=Buffer.alloc(8)
header.writeUInt32LE(0x46546c67);header.writeUInt32LE(2,4);header.writeUInt32LE(12+8+json.length+8+newBin.length,8);jh.writeUInt32LE(json.length);jh.writeUInt32LE(0x4e4f534a,4);bh.writeUInt32LE(newBin.length);bh.writeUInt32LE(0x004e4942,4)
const result=Buffer.concat([header,jh,json,bh,newBin]);assert(newBin.subarray(0,bin.length).equals(bin))
c.uvGutterPadding={maxSourcePixels:8,changedUnusedTexels:count,mappedTexelChanges:0,protectedEarTexelChanges:0,method:'propagate edited boundary colors only into unmapped atlas gutters; reject texels closer to unedited fur/white/ear UV surfaces; original mapped palette pass unchanged'}
c.unpaddedRiggedSha256=c.outputRiggedSha256;c.outputRiggedSha256=hash(result);c.diffuseAfterSha256=hash(png)
await writeFile(join(out,'rigged.glb'),result)
await writeFile(join(out,'audit.json'),JSON.stringify(audit,null,2)+'\n')
await writeFile(join(out,'texture-correction.json'),JSON.stringify(c,null,2)+'\n')
assert.equal(hash(await readFile(c.input)),c.inputSha256)
console.log(JSON.stringify(c.uvGutterPadding))
