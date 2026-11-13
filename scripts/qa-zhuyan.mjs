// Candidate-only Three.js/Gongbi review. Does not edit Stage or public models.
// node scripts/qa-zhuyan.mjs http://localhost:5215 CANDIDATE.glb NEW_EVIDENCE_DIR
import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { chromium } from 'playwright-core'

const [base = 'http://localhost:5215', candidate, output] = process.argv.slice(2)
assert(candidate && output, 'Candidate and unique output directory required')
await mkdir(output, { recursive: false })
const source = await readFile(resolve(candidate))
const report = { candidate: resolve(candidate), candidateSha256: createHash('sha256').update(source).digest('hex'), productionAccepted: false, errors: [] }
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
page.on('pageerror', e => report.errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()) })
// The browser imports the project's installed Three.js and actual ink shader.
// The HTML is supplied only to this Playwright page; no files/public routes change.
await page.route('**/__zhuyan-candidate.glb', route => route.fulfill({ body: source, contentType: 'model/gltf-binary' }))
await page.route('**/__zhuyan-candidate-review', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><title>Zhuyan candidate review</title><style>body{margin:0;background:#efe6d2}canvas{display:block}p{position:absolute;left:24px;top:12px;color:#312e28;font:18px sans-serif}</style></head><body><p>Zhuyan · candidate anatomy / deformation review</p><script type="importmap">{"imports":{"three":"/node_modules/.vite/deps/three.js"}}</script><script type="module">
import * as T from '/node_modules/.vite/deps/three.js';
import {GLTFLoader} from '/node_modules/three/examples/jsm/loaders/GLTFLoader.js';
import {MeshoptDecoder} from '/node_modules/three/examples/jsm/libs/meshopt_decoder.module.js';
import {createInkMaterial} from '/src/systems/ink/inkMaterial.ts';
import {createOutline} from '/src/systems/ink/inkify.ts';
const renderer=new T.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setSize(1440,1000);renderer.setPixelRatio(1);document.body.append(renderer.domElement);
const scene=new T.Scene();scene.background=new T.Color('#efe6d2');scene.add(new T.HemisphereLight('#ffffff','#7d7460',2.1));const sun=new T.DirectionalLight('#ffffff',2.5);sun.position.set(3,5,4);scene.add(sun);
const camera=new T.OrthographicCamera(-1.15,1.15,.8,-.8,.01,30);const root=new T.Group();scene.add(root);
const ground=new T.Mesh(new T.PlaneGeometry(200,200),new T.MeshStandardMaterial({color:'#efe6d2',roughness:1}));ground.rotation.x=-Math.PI/2;ground.position.y=-.002;scene.add(ground);
const loader=new GLTFLoader();loader.setMeshoptDecoder(MeshoptDecoder);const gltf=await loader.loadAsync('/__zhuyan-candidate.glb');root.add(gltf.scene);scene.updateMatrixWorld(true);
const meshes=[];root.traverse(n=>{if(n.isSkinnedMesh)meshes.push(n)});if(meshes.length!==1)throw new Error('Exactly one actual source skinned mesh required');
const mesh=meshes[0],g=mesh.geometry.attributes;mesh.skeleton.update();const rootBone=mesh.skeleton.bones.find(b=>b.name==='root');const ri=mesh.skeleton.bones.indexOf(rootBone);if(ri<0)throw new Error('Rest root bone missing');
// Full rest transform includes inverse-bind meshopt dequantization. Selection
// precedes every skin-weight assertion, so an outer toe cannot hide by weight.
const restMatrix=mesh.matrixWorld.clone().multiply(mesh.bindMatrixInverse).multiply(rootBone.matrixWorld).multiply(mesh.skeleton.boneInverses[ri]).multiply(mesh.bindMatrix);
const feet={l:[],r:[]},soles={l:[],r:[]},head=[],chest=[],rest=[];
const height=mesh.userData.restAnatomicalFootMaxHeight/.085;if(!Number.isFinite(height)||height<1||height>2)throw new Error('Reviewed spatial foot bounds missing');
for(let i=0;i<g.position.count;i++){
 const p=new T.Vector3().fromBufferAttribute(g.position,i).applyMatrix4(restMatrix);rest.push(p);const side=p.x>0?'l':'r';
 if(p.y<height*.085-.00001){feet[side].push(i);if(p.y<.003-.00001)soles[side].push(i);let assigned=0;for(let k=0;k<4;k++)if(mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name==='leg_'+side+'_foot')assigned+=g.skinWeight.getComponent(i,k);if(assigned<.9999)throw new Error('Anatomical foot vertex '+i+' has wrong skin '+assigned)}
 if(p.y>height*.90 || (Math.abs(p.x)<.19&&p.y>height*.725&&p.z>.12))head.push(i);
 if(Math.abs(p.x)<.20&&p.y>height*.46&&p.y<height*.69)chest.push(i);
}
// Geodesic hand selection starts in the outer palms and stops at the wrist
// height. It catches inboard thumbs that overlap the thighs in X/Z.
const graph=Array.from({length:g.position.count},()=>new Set()),indices=mesh.geometry.index;
const edge=(a,b)=>{graph[a].add(b);graph[b].add(a)};
for(let i=0;i<(indices?.count??g.position.count);i+=3){const a=indices?indices.getX(i):i,b=indices?indices.getX(i+1):i+1,c=indices?indices.getX(i+2):i+2;edge(a,b);edge(b,c);edge(c,a)}
const coincident=new Map();rest.forEach((p,i)=>{const key=p.toArray().map(v=>v.toFixed(5)).join('/');if(coincident.has(key))edge(i,coincident.get(key));else coincident.set(key,i)});
const hands={};for(const [side,sign]of [['l',1],['r',-1]]){const seen=new Set();rest.forEach((p,i)=>{if(sign*p.x>.39&&p.y>height*.22&&p.y<height*.32)seen.add(i)});const pending=[...seen];while(pending.length)for(const i of graph[pending.pop()]){const p=rest[i];if(!seen.has(i)&&p.y>height*.17&&p.y<height*.385){seen.add(i);pending.push(i)}}hands[side]=[...seen];if(seen.size<300)throw new Error('Whole-hand anatomy selection empty');for(const i of seen){let assigned=0;for(let k=0;k<4;k++)if(mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name==='arm_'+side+'_hand')assigned+=g.skinWeight.getComponent(i,k);if(assigned<.9999)throw new Error('Native palm/finger '+i+' is stretched by skin '+assigned)}}
for(const side of ['l','r'])if(feet[side].length<100||soles[side].length<10)throw new Error('Complete feet and soles missing');
for(const i of head){let w=0;for(let k=0;k<4;k++)if(mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name==='head')w+=g.skinWeight.getComponent(i,k);if(w<.9999)throw new Error('Actual crown/chin not rigid '+i)}
for(const i of chest)for(let k=0;k<4;k++)if(g.skinWeight.getComponent(i,k)>.0001&&mesh.skeleton.bones[g.skinIndex.getComponent(i,k)]?.name.startsWith('arm_'))throw new Error('Chest dragged by arm '+i);
const mixer=new T.AnimationMixer(gltf.scene),clips=Object.fromEntries(gltf.animations.map(c=>[c.name,mixer.clipAction(c)]));for(const name of ['idle','walk','special'])if(!clips[name])throw new Error('Missing clip '+name);
mesh.frustumCulled=false;const mat=mesh.material;mesh.material=createInkMaterial({map:mat.map??null,tint:mat.map?'#ffffff':'#'+mat.color.getHexString(),saturation:.65});mesh.material.side=T.DoubleSide;const outline=createOutline(mesh,.0014);mesh.parent.add(outline);
const qa=window.zhuyanQA={T,scene,camera,renderer,root,mesh,g,mixer,clips,feet,soles,hands,head,chest,rest,height};
qa.set=(action,t,world=true)=>{mixer.stopAllAction();clips[action].reset().play();mixer.setTime(t);root.position.set(0,0,0);root.rotation.set(0,0,0);if(action==='walk'&&world){const a=Math.PI/2-.08*t;root.position.set(Math.cos(a),0,Math.sin(a));root.rotation.y=Math.PI-a}scene.updateMatrixWorld(true);mesh.skeleton.update()};
qa.points=ids=>ids.map(i=>{const p=new T.Vector3();mesh.getVertexPosition(i,p);mesh.localToWorld(p);return p.toArray()});
qa.draw=(action,t,target,direction,size)=>{qa.set(action,t,false);camera.left=-size*.72;camera.right=size*.72;camera.top=size*.5;camera.bottom=-size*.5;camera.updateProjectionMatrix();const c=new T.Vector3(...target);camera.position.copy(c).add(new T.Vector3(...direction).normalize().multiplyScalar(4));camera.lookAt(c);renderer.render(scene,camera)};
qa.draw('idle',0,[0,height*.5,0],[.6,.2,1],height*1.1);console.info('[beast] ready zhuyan candidate');
</script></body></html>` }))
try {
  const ready = page.waitForEvent('console', { predicate: m => m.text().includes('[beast] ready zhuyan candidate'), timeout: 60000 })
  await page.goto(`${base}/__zhuyan-candidate-review`)
  await ready
  report.baseline = await page.evaluate(() => {
    const q = window.zhuyanQA
    let invalid=0,maxWeightSumError=0
    for(const name of ['position','normal','skinWeight'])if(!Array.from(q.g[name].array).every(Number.isFinite))invalid++
    for(let i=0;i<q.g.position.count;i++){let sum=0;for(let k=0;k<4;k++)sum+=q.g.skinWeight.getComponent(i,k);maxWeightSumError=Math.max(maxWeightSumError,Math.abs(sum-1))}
    for(const action of ['idle','walk','special']){q.set(action,1.6);for(let i=0;i<q.g.position.count;i++){const p=new q.T.Vector3();q.mesh.getVertexPosition(i,p);if(!p.toArray().every(Number.isFinite))invalid++}}
    return { invalid, maxWeightSumError, triangles: (q.mesh.geometry.index?.count??q.g.position.count)/3, vertices: q.g.position.count, bones: q.mesh.skeleton.bones.map(b => b.name), clips: Object.keys(q.clips), height: q.height, anatomicalHands: Object.fromEntries(Object.entries(q.hands).map(([k,v]) => [k,v.length])), anatomicalFeet: Object.fromEntries(Object.entries(q.feet).map(([k,v]) => [k,v.length])), anatomicalSoles: Object.fromEntries(Object.entries(q.soles).map(([k,v]) => [k,v.length])), rigidCrownChinVertices: q.head.length, protectedChestVertices: q.chest.length, restSelection: 'spatial anatomy restored with root inverse bind including meshopt dequantization' }
  })
  assert.equal(report.baseline.invalid,0,'Finite geometry, normals, weights and actual deformation')
  assert(report.baseline.maxWeightSumError<.0001,'Normalized skin weights')
  assert(!report.baseline.bones.some(n => n.includes('tail')))
  report.contact = await page.evaluate(() => {
    const q = window.zhuyanQA, result = {}
    const distance = (a,b) => Math.hypot(...a.map((x,k) => x-b[k]))
    for (const [action,seconds] of [['idle',4],['walk',4.8],['special',4]]) {
      const plants = {}, ranges = [], footShapes = {}, handShapes = {}, headShapes = {}
      let maxDrift=0,maxShapeDrift=0,maxFootShapeDrift=0,maxHandShapeDrift=0,maxHeadShapeDrift=0,invalid=0
      for(let n=0;n<=Math.round(seconds*60);n++){
        const t=n/60;q.set(action,t)
        for(const side of ['l','r']){
          const whole=q.points(q.feet[side]),shape=whole.map(p=>distance(p,whole[0]));footShapes[side]??=shape
          maxFootShapeDrift=Math.max(maxFootShapeDrift,...shape.map((v,i)=>Math.abs(v-footShapes[side][i])))
          const hp=q.points(q.hands[side]),hs=hp.map(p=>distance(p,hp[0]));handShapes[side]??=hs
          maxHandShapeDrift=Math.max(maxHandShapeDrift,...hs.map((v,i)=>Math.abs(v-handShapes[side][i])))
          const raw=t/2.4+(side==='l'?0:.5),phase=raw%1
          if(action==='walk'&&(phase<.025||phase>.635))continue
          const p=q.points(q.soles[side]),key=side+'/'+(action==='walk'?Math.floor(raw):0)
          plants[key]??=p
          const a=p[0],b=plants[key][0]
          for(let i=0;i<p.length;i++){
            if(!p[i].every(Number.isFinite))invalid++
            maxDrift=Math.max(maxDrift,distance(p[i],plants[key][i]));ranges.push(p[i][1])
            maxShapeDrift=Math.max(maxShapeDrift,distance(p[i].map((v,k)=>v-a[k]),plants[key][i].map((v,k)=>v-b[k])))
          }
        }
        const hp=q.points(q.head),shape=hp.map(p=>distance(p,hp[0]));headShapes.initial??=shape
        maxHeadShapeDrift=Math.max(maxHeadShapeDrift,...shape.map((v,i)=>Math.abs(v-headShapes.initial[i])))
      }
      result[action]={maxDrift,maxShapeDrift,maxFootShapeDrift,maxHandShapeDrift,maxHeadShapeDrift,minHeight:Math.min(...ranges),maxHeight:Math.max(...ranges),plantIntervals:Object.keys(plants).length,invalid,measured:'actual getVertexPosition on anatomical foot/sole/head masks at 60Hz; runtime circular root composed'}
    }
    return result
  })
  for (const [action, data] of Object.entries(report.contact)) {
    assert.equal(data.invalid,0,action)
    assert(data.maxDrift<.001,`${action} sole drift ${data.maxDrift}`)
    assert(data.maxShapeDrift<.001,`${action} support orientation ${data.maxShapeDrift}`)
    assert(data.maxFootShapeDrift<.0001 && data.maxHandShapeDrift<.0001 && data.maxHeadShapeDrift<.0001,`${action} rigid anatomy`)
    assert(data.minHeight>-.001 && data.maxHeight<.004,`${action} ground height`)
  }
  report.images=[]
  const h=report.baseline.height
  for(const [name,action,t,target,direction,size] of [
    ['idle','idle',0,[0,h*.5,0],[.6,.2,1],h*1.12],
    ['walk-0','walk',0,[0,h*.5,0],[.6,.2,1],h*1.12],
    ['walk-06','walk',.6,[0,h*.5,0],[.6,.2,1],h*1.12],
    ['walk-12','walk',1.2,[0,h*.5,0],[.6,.2,1],h*1.12],
    ['walk-18','walk',1.8,[0,h*.5,0],[.6,.2,1],h*1.12],
    ['special','special',1.6,[0,h*.5,0],[.6,.2,1],h*1.12],
    ['special-joints','special',1.6,[0,h*.69,0],[.6,.1,1],h*.65],
    ['special-chin','special',1.6,[0,h*.80,.05],[1,0,.3],h*.43],
    ['walk-feet','walk',.6,[0,h*.09,0],[.5,.35,1],h*.52],
    ['special-feet','special',1.6,[0,h*.09,0],[.5,.35,1],h*.52],
  ]){
    await page.evaluate(({action,t,target,direction,size})=>window.zhuyanQA.draw(action,t,target,direction,size),{action,t,target,direction,size})
    const path=join(output,`${name}.png`);await page.screenshot({path});report.images.push(path)
  }
  assert.equal(report.errors.length,0,report.errors.join('\n'))
  report.passed=true
} finally {
  await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n')
  await browser.close()
}
console.log(JSON.stringify(report))
