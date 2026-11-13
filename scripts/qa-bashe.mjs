// Offline candidate review through the existing Vite server. No catalog/Stage edits.
// node scripts/qa-bashe.mjs raw/_build/bashe-UNIQUE/body.glb [http://localhost:5215]
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname, join } from 'node:path'
import { chromium } from 'playwright-core'

const [input, base = 'http://localhost:5215'] = process.argv.slice(2)
assert(input, 'Pass a candidate body.glb')
const root = resolve(import.meta.dirname, '..')
const candidate = resolve(input)
assert(candidate.startsWith(join(root, 'raw', '_build', 'bashe-')), 'Candidate-only raw/_build/bashe-* input')
const out = join(dirname(candidate), 'browser-review')
await mkdir(out, { recursive: true })
const bytes = await readFile(candidate)
const browser = await chromium.launch({ channel: 'chrome', args: ['--use-angle=metal', '--enable-gpu'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', e => errors.push(String(e)))
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
page.on('response', r => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`) })
const report = { candidate, candidateOnly: true, renderer: 'standalone Three.js PBR; no production Stage integration', images: [], errors }
try {
  await page.route('**/__bashe-candidate.glb', route => route.fulfill({ body: bytes, contentType: 'model/gltf-binary' }))
  await page.route('**/__bashe-review', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><title>Bashe candidate review</title><style>body{margin:0;background:#e8deca;font:16px sans-serif;color:#292a27}canvas{display:block}aside{position:fixed;top:20px;left:24px;background:#f7f0ddeb;padding:12px 16px;max-width:380px}small{display:block;margin-top:5px}</style></head><body><aside>Bashe · offline High candidate<small id="label">Loading source mesh…</small></aside><script type="importmap">{"imports":{"three":"/node_modules/.vite/deps/three.js"}}</script><script type="module">
import * as THREE from '/node_modules/.vite/deps/three.js'
import { GLTFLoader } from '/node_modules/three/examples/jsm/loaders/GLTFLoader.js'
import { MeshoptDecoder } from '/node_modules/three/examples/jsm/libs/meshopt_decoder.module.js'
const renderer = new THREE.WebGLRenderer({ antialias:true, preserveDrawingBuffer:true })
renderer.setSize(innerWidth,innerHeight); renderer.setPixelRatio(1)
renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap
renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=1.4
renderer.setClearColor('#e8deca'); document.body.append(renderer.domElement)
const scene=new THREE.Scene(), camera=new THREE.PerspectiveCamera(34,innerWidth/innerHeight,.01,100)
scene.add(new THREE.HemisphereLight(0xdce8ed,0x9a8c72,2.2))
for(const [position,intensity] of [[[4,7,4],3],[[-4,4,-3],1.8]]){
 const light=new THREE.DirectionalLight(0xffffff,intensity); light.position.set(...position)
 light.castShadow=true; light.shadow.mapSize.set(2048,2048)
 Object.assign(light.shadow.camera,{left:-4,right:4,top:4,bottom:-4,near:.1,far:25})
 light.shadow.bias=-.0001; scene.add(light)
}
const ground=new THREE.Mesh(new THREE.PlaneGeometry(100,100),new THREE.MeshStandardMaterial({color:0xe8deca,roughness:1}))
ground.rotation.x=-Math.PI/2; ground.receiveShadow=true; scene.add(ground)
const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder)
const gltf=await loader.loadAsync('/__bashe-candidate.glb')
const model=gltf.scene; scene.add(model)
const meshes=[];model.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;meshes.push(o)}})
const mixer=new THREE.AnimationMixer(model), clips=Object.fromEntries(gltf.animations.map(c=>[c.name,c]))
const {createInkMaterial,createOutlineMaterial}=await import('/src/systems/ink/inkMaterial.ts')
const appearances=meshes.map(mesh=>{
 const pbr=mesh.material, ink=createInkMaterial({map:pbr.map,saturation:.65})
 const outline=new THREE.SkinnedMesh(mesh.geometry,createOutlineMaterial(.004))
 outline.bind(mesh.skeleton,mesh.bindMatrix);outline.position.copy(mesh.position)
 outline.quaternion.copy(mesh.quaternion);outline.scale.copy(mesh.scale)
 outline.frustumCulled=false;outline.visible=false;outline.userData.inkOutline=true
 mesh.parent.add(outline);return {mesh,pbr,ink,outline}
})
function appearance(kind){for(const item of appearances){item.mesh.material=kind==='ink'?item.ink:item.pbr;item.outline.visible=kind==='ink';item.mesh.castShadow=kind!=='ink';item.mesh.receiveShadow=kind!=='ink'}}
function pose(name,time){mixer.stopAllAction();const action=mixer.clipAction(clips[name]);action.reset().setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();mixer.setTime(time);model.updateMatrixWorld(true);for(const mesh of meshes)mesh.skeleton?.update();renderer.render(scene,camera)}
function view(name){const target=new THREE.Vector3(0,.14,0);camera.up.set(0,1,0)
 const positions={threeQuarter:[4.8,3.6,4.8],side:[6.5,.8,0],top:[0,7,.001],head:[1.1,.62,3.15],headDorsal:[0,1.65,2.1],headFront:[0,.4,3.8],tail:[1.1,.6,-3.1]}
 if(name==='top')camera.up.set(1,0,0)
 if(name==='head')target.set(0,.16,2.15)
 if(name==='headDorsal'){target.set(0,.13,2.1);camera.up.set(0,0,-1)}
 if(name==='headFront')target.set(0,.16,2.15)
 if(name==='tail')target.set(0,.13,-2)
 camera.position.set(...positions[name]);camera.lookAt(target);camera.updateProjectionMatrix();renderer.render(scene,camera)
}
window.basheReview={THREE,renderer,scene,camera,model,meshes,mixer,clips,pose,view,appearance}
view('threeQuarter');pose('idle',0);window.basheReady=true
</script></body></html>` }))
  await page.goto(`${base}/__bashe-review`)
  await page.waitForFunction(() => window.basheReady, null, { timeout: 60000 })
  report.geometry = await page.evaluate(() => {
    const { model, meshes, clips } = window.basheReview
    let invalid = 0, unweighted = 0, vertices = 0, normalZero = 0
    const bones = []
    model.traverse(o => { if (o.isBone) bones.push(o.name) })
    for (const mesh of meshes) {
      const a = mesh.geometry.attributes
      vertices += a.position.count
      for (const name of ['position', 'normal', 'skinWeight']) {
        if (!a[name] || !Array.from(a[name].array).every(Number.isFinite)) invalid++
      }
      for (let i = 0; i < a.position.count; i++) {
        const sum = a.skinWeight.getX(i) + a.skinWeight.getY(i) + a.skinWeight.getZ(i) + a.skinWeight.getW(i)
        if (Math.abs(sum - 1) > .0001) unweighted++
        if (Math.hypot(a.normal.getX(i), a.normal.getY(i), a.normal.getZ(i)) < .1) normalZero++
      }
    }
    return { meshes: meshes.length, vertices, bones, clips: Object.fromEntries(Object.entries(clips).map(([k,v]) => [k,v.duration])), invalid, unweighted, normalZero }
  })
  assert.equal(report.geometry.invalid, 0)
  assert.equal(report.geometry.unweighted, 0)
  assert.equal(report.geometry.normalZero, 0)
  assert.equal(report.geometry.bones.filter(n => n === 'head' || /^axial_\d\d$/.test(n)).length, 24)
  assert.deepEqual(Object.keys(report.geometry.clips).sort(), ['idle', 'special', 'walk'])
  report.actions = {}
  for (const action of ['idle', 'walk', 'special']) {
    report.actions[action] = await page.evaluate(name => {
      const { THREE, meshes, clips, pose } = window.basheReview
      const q = new THREE.Vector3(), rest = [], samples = []
      let zmin = Infinity, zmax = -Infinity
      for (const mesh of meshes) for (let i=0;i<mesh.geometry.attributes.position.count;i++) {
        const z = mesh.geometry.attributes.position.getZ(i); zmin=Math.min(zmin,z);zmax=Math.max(zmax,z)
      }
      // 29 intervals deliberately sample between Blender's 30 fps keys too.
      for (let f=0;f<=29;f++) {
        const time=clips[name].duration*f/29;pose(name,time)
        let minimum=Infinity,maximum=-Infinity,invalid=0,displacement=0,headPair=0
        const bodyFloors=Array(24).fill(Infinity),headPoints=[]
        let at=0
        for(const mesh of meshes){
          const g=mesh.geometry.attributes
          for(let i=0;i<g.position.count;i++,at++){
            mesh.getVertexPosition(i,q);mesh.localToWorld(q)
            if(!q.toArray().every(Number.isFinite))invalid++
            minimum=Math.min(minimum,q.y);maximum=Math.max(maximum,q.y)
            if(f===0)rest.push(q.clone());else displacement=Math.max(displacement,q.distanceTo(rest[at]))
            const p=(zmax-g.position.getZ(i))/(zmax-zmin),bin=Math.max(0,Math.min(23,Math.floor(p*24)))
            bodyFloors[bin]=Math.min(bodyFloors[bin],q.y)
            if(p<.08&&headPoints.length<20)headPoints.push(q.clone())
          }
        }
        if(headPoints.length>1)headPair=headPoints[0].distanceTo(headPoints.at(-1))
        samples.push({time,minimum,maximum,invalid,displacement,headPair,bodyFloors,torsoMaxFloor:Math.max(...bodyFloors.slice(4,19))})
      }
      return {samples,maxDisplacement:Math.max(...samples.map(s=>s.displacement)),loopSeamDisplacement:samples.at(-1).displacement,minimum:Math.min(...samples.map(s=>s.minimum)),maximumMinimum:Math.max(...samples.map(s=>s.minimum)),headPairDrift:Math.max(...samples.map(s=>s.headPair))-Math.min(...samples.map(s=>s.headPair)),maximumTorsoFloor:Math.max(...samples.map(s=>s.torsoMaxFloor)),maximumPosteriorFloor:Math.max(...samples.flatMap(s=>s.bodyFloors.slice(10,19)))}
    }, action)
    const result = report.actions[action]
    assert(result.samples.every(s => s.invalid === 0), `${action} finite actual deformation`)
    assert(result.minimum > .004 && result.maximumMinimum < .009, `${action} actual ground clearance`)
    assert(result.headPairDrift < .0001, `${action} rigid anterior head`)
    assert(result.loopSeamDisplacement < .00001, `${action} seamless sampled loop`)
    assert((action === 'special' ? result.maximumPosteriorFloor : result.maximumTorsoFloor) < .045, `${action} lower envelope stays near ground across the torso`)
    assert(result.maxDisplacement > (action === 'idle' ? .005 : .05), `${action} measurable deformation`)
    for (const [index, fraction] of [.125,.375,.625].entries()) {
      await page.evaluate(({ action, fraction }) => {
        const r=window.basheReview;r.view('threeQuarter');r.pose(action,r.clips[action].duration*fraction)
        document.querySelector('#label').textContent=action+' · '+Math.round(fraction*100)+'% · PBR candidate'
      }, { action, fraction })
      const path=join(out,`${action}-${index}.png`)
      await page.screenshot({path});report.images.push(path)
    }
  }
  for (const name of ['side','top','head','tail']) {
    await page.evaluate(name => {const r=window.basheReview;r.pose('idle',0);r.view(name);document.querySelector('#label').textContent=name+' · anatomical review'}, name)
    const path=join(out,`anatomy-${name}.png`)
    await page.screenshot({path});report.images.push(path)
  }
  for (const kind of ['pbr','ink']) {
    for (const name of ['head','headDorsal','headFront','top','threeQuarter']) {
      await page.evaluate(({kind,name})=>{const r=window.basheReview;r.appearance(kind);r.pose('idle',0);r.view(name);document.querySelector('#label').textContent=kind+' · '+name+' · head palette review'},{kind,name})
      const path=join(out,`${kind}-${name}.png`)
      await page.screenshot({path});report.images.push(path)
    }
  }
  for (const action of ['walk','special']) {
    await page.evaluate(action=>{const r=window.basheReview;r.appearance('ink');r.view('threeQuarter');r.pose(action,r.clips[action].duration*.375);document.querySelector('#label').textContent='ink · '+action+' · deformation'},action)
    const path=join(out,`ink-${action}.png`)
    await page.screenshot({path});report.images.push(path)
  }
  report.inkAppearance='Existing createInkMaterial/createOutlineMaterial in an isolated viewer; production Stage and postprocessing unchanged'
  assert.equal(errors.length, 0, errors.join('\n'))
  report.passed = true
  console.log(JSON.stringify({geometry:report.geometry,actions:Object.fromEntries(Object.entries(report.actions).map(([k,{samples,...v}])=>[k,v])),images:report.images,errors},null,2))
} finally {
  await writeFile(join(out,'browser-qa.json'),JSON.stringify(report,null,2)+'\n')
  await browser.close()
}
