// Candidate-only offline Three.js + actual Gongbi shader review. No server.
// node scripts/qa-xingxing.mjs CANDIDATE/body.glb NEW_EVIDENCE_DIR
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join, dirname } from 'node:path'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { chromium } from 'playwright-core'

const [candidate, outputArg] = process.argv.slice(2)
assert(candidate && outputArg, 'Candidate GLB and new evidence directory required')
const output = resolve(outputArg), rootDir = resolve(import.meta.dirname, '..')
await mkdir(output, { recursive: false })
const source = await readFile(resolve(candidate))
const audit = JSON.parse(await readFile(join(dirname(resolve(candidate)), 'audit.json'), 'utf8'))
assert.equal(audit.sourceSha256, 'af138ac179b91c5217977cb59fe0f13bd8bedcb522429ac1c7a42c00ee5adeca')
const raw = await readFile(audit.source)
assert.equal(createHash('sha256').update(raw).digest('hex'), audit.sourceSha256)
const report = { candidate: resolve(candidate), candidateSha256: createHash('sha256').update(source).digest('hex'),
  bytes: source.length, sourceSha256: audit.sourceSha256, sourceUnchanged: true, productionAccepted: false,
  runtimeContract: audit.runtimeContract, errors: [] }
const jsonLength = source.readUInt32LE(12)
const gltfJSON = JSON.parse(source.subarray(20, 20 + jsonLength).toString('utf8'))
report.container = { extensions: gltfJSON.extensionsUsed, images: gltfJSON.images?.map(i => ({ name: i.name, mimeType: i.mimeType })),
  materials: gltfJSON.materials?.map(m => ({ name: m.name, alphaMode: m.alphaMode ?? 'OPAQUE', doubleSided: m.doubleSided ?? false,
    baseColorFactor: m.pbrMetallicRoughness?.baseColorFactor ?? [1,1,1,1], metallicFactor: m.pbrMetallicRoughness?.metallicFactor ?? 1,
    roughnessFactor: m.pbrMetallicRoughness?.roughnessFactor ?? 1, normalScale: m.normalTexture?.scale ?? 1 })) }
assert(source.length < 15 * 1024 * 1024)
assert(report.container.images.every(i => i.mimeType === 'image/webp'))
const { build } = createRequire(import.meta.resolve('vite'))('esbuild')
const code = `
import * as T from 'three';
import {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js';
import {MeshoptDecoder} from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import {createInkMaterial} from './src/systems/ink/inkMaterial.ts';
import {createOutline} from './src/systems/ink/inkify.ts';
const audit=${JSON.stringify(audit)};
const renderer=new T.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setSize(1440,1000);renderer.setPixelRatio(1);document.body.append(renderer.domElement);
const scene=new T.Scene();scene.background=new T.Color('#efe6d2');scene.add(new T.HemisphereLight('#ffffff','#7d7460',2.1));const sun=new T.DirectionalLight('#ffffff',2.5);sun.position.set(3,5,4);scene.add(sun);
const camera=new T.OrthographicCamera(-1,1,.7,-.7,.01,30),root=new T.Group();scene.add(root);
const ground=new T.Mesh(new T.PlaneGeometry(200,200),new T.MeshStandardMaterial({color:'#efe6d2',roughness:1}));ground.rotation.x=-Math.PI/2;ground.position.y=-.002;scene.add(ground);
const loader=new GLTFLoader();loader.setMeshoptDecoder(MeshoptDecoder);const gltf=await loader.loadAsync('/candidate.glb');root.add(gltf.scene);scene.updateMatrixWorld(true);
const meshes=[];root.traverse(n=>{if(n.isSkinnedMesh)meshes.push(n)});if(meshes.length!==1)throw new Error('Exactly one source skinned mesh required');
const mesh=meshes[0],g=mesh.geometry.attributes;mesh.skeleton.update();const rootBone=mesh.skeleton.bones.find(b=>b.name==='root'),ri=mesh.skeleton.bones.indexOf(rootBone);
const restMatrix=mesh.matrixWorld.clone().multiply(mesh.bindMatrixInverse).multiply(rootBone.matrixWorld).multiply(mesh.skeleton.boneInverses[ri]).multiply(mesh.bindMatrix);
const h=mesh.userData.restHeight,scale=audit.sourceToRig.reviewToFinalUniformScale;
if(Math.abs(h-1.35)>.00001)throw new Error('Final height metadata missing');
const feet={l:[],r:[]},soles={l:[],r:[]},hands={},arms={},head=[],chest=[],rest=[];
const smooth=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t)};
const graph=Array.from({length:g.position.count},()=>new Set()),indices=mesh.geometry.index;
const edge=(a,b)=>{graph[a].add(b);graph[b].add(a)};
for(let i=0;i<(indices?.count??g.position.count);i+=3){const a=indices?indices.getX(i):i,b=indices?indices.getX(i+1):i+1,c=indices?indices.getX(i+2):i+2;edge(a,b);edge(b,c);edge(c,a)}
const coincident=new Map();
for(let i=0;i<g.position.count;i++){
 const p=new T.Vector3().fromBufferAttribute(g.position,i).applyMatrix4(restMatrix);rest.push(p);const side=p.x>0?'l':'r';
 const key=p.toArray().map(v=>v.toFixed(5)).join('/');if(coincident.has(key))edge(i,coincident.get(key));else coincident.set(key,i);
 if(p.y<h*.105-.00001){feet[side].push(i);if(p.y<mesh.userData.restAnatomicalSoleMaxHeight-.00001)soles[side].push(i)}
 const floor=.802-.062*(1-smooth(-.025,.065,-p.z/scale));if(p.y/h>floor+.00001)head.push(i);
 if(Math.abs(p.x)<.115*scale&&p.y>h*.46&&p.y<h*.69)chest.push(i);
}
const flood=(seeds,allowed)=>{const seen=new Set(seeds),pending=[...seen];while(pending.length)for(const i of graph[pending.pop()])if(!seen.has(i)&&allowed(rest[i])){seen.add(i);pending.push(i)}return [...seen]};
const lower=flood(rest.flatMap((p,i)=>p.y<h*.15?[i]:[]),p=>p.y<h*.46);
const convert=p=>new T.Vector3(p[0],p[2],-p[1]);
for(const [side,sign]of [['l',1],['r',-1]]){
 const wrist=convert(audit.landmarks[side].wrist),elbow=convert(audit.landmarks[side].elbow),axis=wrist.clone().sub(elbow).normalize();
 hands[side]=flood(rest.flatMap((p,i)=>sign*p.x>.40*scale?[i]:[]),p=>p.clone().sub(wrist).dot(axis)>-.008*scale&&sign*p.x>.285*scale);
 arms[side]=flood(hands[side],p=>sign*p.x>(.185-.030*smooth(.55,.74,p.y/h))*scale&&p.y<h*.775);
 if(hands[side].length<500||feet[side].length<100||soles[side].length<8)throw new Error('Anatomical selection empty');
}
const weight=(i,name)=>{let sum=0;for(let k=0;k<4;k++)if(mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name===name)sum+=g.skinWeight.getComponent(i,k);return sum};
for(const side of ['l','r']){
 for(const i of feet[side])if(weight(i,'leg_'+side+'_foot')<.9999)throw new Error('Whole foot/toe not rigid '+i);
 for(const i of hands[side])if(weight(i,'arm_'+side+'_hand')<.9999)throw new Error('Whole palm/finger not rigid '+i);
}
for(const i of head)if(weight(i,'head')<.9999)throw new Error('Head/ear not rigid '+i);
for(const i of [...lower,...chest])for(let k=0;k<4;k++)if(g.skinWeight.getComponent(i,k)>.0001&&mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name.startsWith('arm_'))throw new Error('Arm/leg/torso weight contamination '+i);
const mixer=new T.AnimationMixer(gltf.scene),clips=Object.fromEntries(gltf.animations.map(c=>[c.name,mixer.clipAction(c)]));for(const name of ['idle','walk','special'])if(!clips[name])throw new Error('Missing clip '+name);
const originalMaterial=mesh.material;const materialMaps=['map','normalMap','roughnessMap','metalnessMap'].flatMap(k=>originalMaterial[k]?[{slot:k,width:originalMaterial[k].image.width,height:originalMaterial[k].image.height}]:[]);
mesh.frustumCulled=false;const ink=createInkMaterial({map:originalMaterial.map??null,tint:'#ffffff',saturation:.65});ink.side=T.DoubleSide;const outline=createOutline(mesh,.0014);mesh.parent.add(outline);
const qa=window.xingxingQA={T,scene,camera,renderer,root,mesh,g,mixer,clips,feet,soles,hands,arms,head,chest,rest,h,lower,materialMaps};
qa.set=(name,t,world=true,endpoint=false)=>{mixer.stopAllAction();const a=clips[name];a.setLoop(T.LoopOnce,1);a.clampWhenFinished=true;a.reset().play();mixer.setTime(endpoint?t:t%a.getClip().duration);root.position.set(0,0,0);root.rotation.set(0,0,0);if(name==='walk'&&world){const angle=Math.PI/2-.06*t;root.position.set(Math.cos(angle),0,Math.sin(angle));root.rotation.y=Math.PI-angle}scene.updateMatrixWorld(true);mesh.skeleton.update()};
qa.points=ids=>ids.map(i=>{const p=new T.Vector3();mesh.getVertexPosition(i,p);mesh.localToWorld(p);return p.toArray()});
qa.draw=(name,t,target,direction,size,material='ink',world=false)=>{qa.set(name,t,world);mesh.material=material==='pbr'?originalMaterial:ink;outline.visible=material!=='pbr';camera.left=-size*.72;camera.right=size*.72;camera.top=size*.5;camera.bottom=-size*.5;camera.updateProjectionMatrix();const c=new T.Vector3(...target);camera.position.copy(c).add(new T.Vector3(...direction).normalize().multiplyScalar(4));camera.lookAt(c);renderer.render(scene,camera)};
qa.draw('idle',0,[0,.65,0],[.6,.2,1],1.6);console.info('[beast] ready xingxing candidate');
`
const bundled = await build({ stdin: { contents: code, resolveDir: rootDir, sourcefile: 'xingxing-review.ts', loader: 'ts' }, bundle: true, write: false, format: 'esm', target: 'es2022', logLevel: 'silent' })
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
await page.route('https://xingxing.invalid/**', async route => {
  const path = new URL(route.request().url()).pathname
  if (path === '/candidate.glb') await route.fulfill({ body: source, contentType: 'model/gltf-binary' })
  else if (path === '/review.js') await route.fulfill({ body: bundled.outputFiles[0].text, contentType: 'text/javascript' })
  else if (path === '/') await route.fulfill({ contentType: 'text/html', body: '<!doctype html><html><head><meta charset="utf-8"><title>Xingxing candidate review</title><style>body{margin:0;background:#efe6d2}canvas{display:block}</style></head><body><script type="module" src="/review.js"></script></body></html>' })
  else if (path === '/favicon.ico') await route.fulfill({ status: 204, body: '' })
  else await route.fulfill({ status: 404, body: '' })
})
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready xingxing candidate'), timeout: 60000 })
  await page.goto('https://xingxing.invalid/')
  await ready
  report.baseline = await page.evaluate(() => {
    const q=window.xingxingQA
    let invalid=0,maxWeightSumError=0,minNormalLength=Infinity,maxNormalLength=0
    for(const name of ['position','normal','skinWeight'])if(!Array.from(q.g[name].array).every(Number.isFinite))invalid++
    for(let i=0;i<q.g.position.count;i++){
      let sum=0;for(let k=0;k<4;k++)sum+=q.g.skinWeight.getComponent(i,k);maxWeightSumError=Math.max(maxWeightSumError,Math.abs(sum-1))
      const length=Math.hypot(q.g.normal.getX(i),q.g.normal.getY(i),q.g.normal.getZ(i));minNormalLength=Math.min(minNormalLength,length);maxNormalLength=Math.max(maxNormalLength,length)
    }
    const materialMaps=q.materialMaps
    for(const name of ['idle','walk','special']){q.set(name,1.6,false);for(let i=0;i<q.g.position.count;i++){const p=new q.T.Vector3();q.mesh.getVertexPosition(i,p);if(!p.toArray().every(Number.isFinite))invalid++}}
    return {invalid,maxWeightSumError,minNormalLength,maxNormalLength,materialMaps,
      triangles:(q.mesh.geometry.index?.count??q.g.position.count)/3,vertices:q.g.position.count,
      bones:q.mesh.skeleton.bones.map(b=>b.name),clips:Object.fromEntries(Object.entries(q.clips).map(([name,a])=>[name,a.getClip().duration])),
      masks:{feet:Object.fromEntries(Object.entries(q.feet).map(([k,v])=>[k,v.length])),soles:Object.fromEntries(Object.entries(q.soles).map(([k,v])=>[k,v.length])),hands:Object.fromEntries(Object.entries(q.hands).map(([k,v])=>[k,v.length])),head:q.head.length,chest:q.chest.length,lower:q.lower.length},
      height:q.h,restAnatomicalFootMaxHeight:q.mesh.userData.restAnatomicalFootMaxHeight,solePatchRestMaxHeight:q.mesh.userData.restAnatomicalSoleMaxHeight,
      solePatchBounds:Object.fromEntries(['l','r'].map(side=>[side,{min:[0,1,2].map(k=>Math.min(...q.soles[side].map(i=>q.rest[i].getComponent(k)))),max:[0,1,2].map(k=>Math.max(...q.soles[side].map(i=>q.rest[i].getComponent(k))))}])),
      restBounds:{min:[0,1,2].map(k=>Math.min(...q.rest.map(p=>p.getComponent(k)))),max:[0,1,2].map(k=>Math.max(...q.rest.map(p=>p.getComponent(k))))}}
  })
  assert.equal(report.baseline.invalid,0)
  assert.equal(report.baseline.triangles,50000)
  assert(report.baseline.maxWeightSumError<.0001)
  assert(!report.baseline.bones.some(n=>n.includes('tail')))
  assert(report.baseline.materialMaps.every(m=>m.width<=2048&&m.height<=2048))
  report.contact = await page.evaluate(() => {
    const q=window.xingxingQA,result={},distance=(a,b)=>Math.hypot(...a.map((x,k)=>x-b[k]))
    for(const [name,seconds] of [['idle',4],['walk',4.8],['special',4]]){
      const plants={},plantQuaternions={},ranges=[],footShapes={},handShapes={},headShapes={}
      let maxAngularDrift=0,maxDrift=0,maxOrientationDrift=0,maxFootShapeDrift=0,maxHandShapeDrift=0,maxHeadShapeDrift=0,invalid=0,minAllFootHeight=Infinity
      for(let n=0;n<=Math.round(seconds*60);n++){
        const t=n/60;q.set(name,t)
        for(const side of ['l','r']){
          const whole=q.points(q.feet[side]),shape=whole.map(p=>distance(p,whole[0]));footShapes[side]??=shape
          maxFootShapeDrift=Math.max(maxFootShapeDrift,...shape.map((v,i)=>Math.abs(v-footShapes[side][i])))
          minAllFootHeight=Math.min(minAllFootHeight,...whole.map(p=>p[1]))
          const hp=q.points(q.hands[side]),hs=hp.map(p=>distance(p,hp[0]));handShapes[side]??=hs
          maxHandShapeDrift=Math.max(maxHandShapeDrift,...hs.map((v,i)=>Math.abs(v-handShapes[side][i])))
          const raw=t/2.4+(side==='l'?0:.5),phase=raw%1
          if(name==='walk'&&(phase<.025||phase>.635))continue
          ranges.push(...q.points(q.soles[side]).map(p=>p[1]))
          const p=whole,key=side+'/'+(name==='walk'?Math.floor(raw):0);plants[key]??=p
          const rotation=q.mesh.skeleton.bones.find(b=>b.name==='leg_'+side+'_foot').getWorldQuaternion(new q.T.Quaternion()).normalize()
          plantQuaternions[key]??=rotation.clone();maxAngularDrift=Math.max(maxAngularDrift,rotation.angleTo(plantQuaternions[key]))
          for(let i=0;i<p.length;i++){
            if(!p[i].every(Number.isFinite))invalid++
            maxDrift=Math.max(maxDrift,distance(p[i],plants[key][i]))
            maxOrientationDrift=Math.max(maxOrientationDrift,distance(p[i].map((v,k)=>v-p[0][k]),plants[key][i].map((v,k)=>v-plants[key][0][k])))
          }
        }
        const hp=q.points(q.head),shape=hp.map(p=>distance(p,hp[0]));headShapes.initial??=shape
        maxHeadShapeDrift=Math.max(maxHeadShapeDrift,...shape.map((v,i)=>Math.abs(v-headShapes.initial[i])))
      }
      result[name]={maxDrift,maxOrientationDrift,maxAngularDrift,maxFootShapeDrift,maxHandShapeDrift,maxHeadShapeDrift,minSoleHeight:Math.min(...ranges),maxSoleHeight:Math.max(...ranges),minAllFootHeight,plantIntervals:Object.keys(plants).length,invalid,samplingHz:60}
    }
    return result
  })
  for(const [name,data] of Object.entries(report.contact)){
    assert.equal(data.invalid,0,name)
    assert(data.maxDrift<.001,`${name} sole drift ${data.maxDrift}`)
    assert(data.maxOrientationDrift<.001&&data.maxAngularDrift<.002,`${name} horizontal support ${data.maxOrientationDrift}; angular ${data.maxAngularDrift}`)
    assert(data.maxFootShapeDrift<.0001&&data.maxHandShapeDrift<.0001&&data.maxHeadShapeDrift<.0001,`${name} rigid anatomy`)
    assert(data.minSoleHeight>-.001&&data.maxSoleHeight<report.baseline.solePatchRestMaxHeight+.001,`${name} sole bounds`)
    assert(data.minAllFootHeight>-.001,`${name} foot ground penetration`)
  }
  report.seams = await page.evaluate(() => {
    const q=window.xingxingQA,result={},ids=Array.from({length:q.g.position.count},(_,i)=>i)
    for(const [name,action] of Object.entries(q.clips)){
      const duration=action.getClip().duration,dt=1/30
      const p=[];for(const t of [0,dt,duration-dt,duration]){q.set(name,t,false,true);p.push(q.points(ids))}
      let maxPositionGap=0,maxVelocityGap=0
      for(let i=0;i<ids.length;i++){
        maxPositionGap=Math.max(maxPositionGap,Math.hypot(...p[0][i].map((x,k)=>x-p[3][i][k])))
        maxVelocityGap=Math.max(maxVelocityGap,Math.hypot(...p[0][i].map((x,k)=>(p[1][i][k]-x-p[3][i][k]+p[2][i][k])/dt)))
      }
      result[name]={duration,allVertexMaxPositionGap:maxPositionGap,oneFrameVelocityGap:maxVelocityGap}
    }
    return result
  })
  for(const [name,data]of Object.entries(report.seams)){
    assert(data.allVertexMaxPositionGap<.0001,`${name} actual endpoint seam`)
    assert(data.oneFrameVelocityGap<.01,`${name} loop velocity seam ${data.oneFrameVelocityGap}`)
  }
  report.images=[]
  const h=report.baseline.height
  const shots=[
    ['idle','idle',0,[0,.65,0],[.6,.2,1],1.65],
    ['idle-front','idle',0,[0,.65,0],[0,0,1],1.65],
    ['idle-back','idle',0,[0,.65,0],[0,0,-1],1.65],
    ['idle-pbr','idle',0,[0,.65,0],[.6,.2,1],1.65,'pbr'],
    ['special','special',1.6,[0,.65,0],[.6,.2,1],1.65],
    ['special-side','special',1.6,[0,.65,0],[1,.05,.2],1.65],
    ['special-head','special',1.6,[0,h*.86,.02],[.5,.08,1],h*.40],
    ['special-feet','special',1.6,[0,h*.07,.02],[.4,.3,1],h*.64],
  ]
  for(let n=0;n<6;n++)shots.push(['walk-'+n,'walk',n*.4,[0,.65,0],[.6,.2,1],1.65])
  for(const [side,sign]of [['l',1],['r',-1]])shots.push(['special-hand-'+side,'special',1.6,[sign*.58,.54,.075],[sign*.1,.1,1],h*.43])
  for(const [tag,name,t,target,direction,size,material='ink']of shots){
    await page.evaluate(o=>window.xingxingQA.draw(o.name,o.t,o.target,o.direction,o.size,o.material),{name,t,target,direction,size,material})
    const path=join(output,tag+'.png');await page.screenshot({path});report.images.push(path)
  }
  // World-composed support sequence: camera/ground remain fixed across a stance.
  const center=[.06,.11,1]
  for(let n=0;n<7;n++){
    const t=.12+n*.20
    await page.evaluate(({t,center})=>window.xingxingQA.draw('walk',t,center,[.6,.5,1],1.15,'ink',true),{t,center})
    const path=join(output,`stance-${n}.png`);await page.screenshot({path});report.images.push(path)
  }
  assert.equal(report.errors.length,0,report.errors.join('\n'))
  report.passed=true
} finally {
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n')
  await browser.close()
}
console.log(JSON.stringify(report))
