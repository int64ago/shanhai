// Actual rendered anatomy, XYZ sole contact/direction, clone cleanup and audio.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from 'playwright-core'
const [base='http://localhost:5224',out='/tmp/feiyi_snake-qa']=process.argv.slice(2)
await mkdir(out,{recursive:true})
const browser=await chromium.launch({channel:'chrome',args:['--use-angle=metal','--enable-gpu']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[],report={actions:{},remounts:[],angles:[],errors}
page.on('pageerror',e=>errors.push(String(e)))
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`)})
try {
  let ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jingwei')})
  await page.goto(`${base}/?beast=jingwei&action=idle`);await ready
  // Snapshot cached resources before the first Feiyi StrictMode mount.
  await page.evaluate(async()=>{
    const moduleUrl=path=>performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname===path)?.name
    const {useGLTF}=await import(moduleUrl('/node_modules/.vite/deps/@react-three_drei.js'))
    useGLTF.preload('/models/feiyi_snake/body.glb')
    for(;;){try{window.feiyiSource=useGLTF('/models/feiyi_snake/body.glb').scene;break}catch(pending){if(!pending?.then)throw pending;await pending}}
    window.feiyiSourceSnapshot=()=>{
      const rows=[]
      window.feiyiSource.traverse(n=>rows.push({uuid:n.uuid,name:n.name,children:n.children.map(c=>c.uuid),position:n.position.toArray(),quaternion:n.quaternion.toArray(),scale:n.scale.toArray(),geometry:n.geometry?.uuid,skeleton:n.skeleton?.uuid,outline:!!n.userData.inkOutline,materials:(Array.isArray(n.material)?n.material:n.material?[n.material]:[]).map(m=>({uuid:m.uuid,type:m.type,color:m.color?.getHexString(),map:m.map?.uuid,normalMap:m.normalMap?.uuid,roughness:m.roughness,metalness:m.metalness,side:m.side,transparent:m.transparent,opacity:m.opacity,userData:JSON.stringify(m.userData)}))}))
      return JSON.stringify(rows)
    }
    window.feiyiSourceBefore=window.feiyiSourceSnapshot()
    window.feiyiShared=new Set();window.feiyiSharedDisposals=0
    window.feiyiSource.traverse(n=>{if(n.geometry)window.feiyiShared.add(n.geometry);for(const m of Array.isArray(n.material)?n.material:n.material?[n.material]:[]){window.feiyiShared.add(m);for(const v of Object.values(m))if(v?.isTexture)window.feiyiShared.add(v)}})
    for(const r of window.feiyiShared)r.addEventListener('dispose',()=>window.feiyiSharedDisposals++)
  })
  ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready feiyi_snake')})
  await page.evaluate(async()=>{const url=performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname==='/src/app/store.ts').name;const {useApp}=await import(url);useApp.getState().select('feiyi_snake')});await ready
  await page.evaluate(async()=>{
    const urls=performance.getEntriesByType('resource').map(r=>r.name)
    const fiber=await import(urls.find(u=>u.includes('@react-three_fiber.js')))
    const {useApp}=await import(urls.find(u=>new URL(u).pathname==='/src/app/store.ts'))
    window.feiyiQA={state:[...fiber._roots.values()][0].store.getState(),useApp}
  })
  async function snapshot(full=false) {
    return page.evaluate(all=>{
      const {state}=window.feiyiQA;state.scene.updateMatrixWorld(true)
      const root=state.scene.getObjectByName('feiyi_snake_root')
      const meshes=[],bones=[],outlines=[];let invalid=0,nodes=0
      root.traverse(n=>{
        nodes++
        if(![...n.matrixWorld.elements,...n.position,...n.quaternion,...n.scale].every(Number.isFinite)||Math.min(...n.scale)<=0)invalid++
        if(n.isBone)bones.push(n)
        if(!n.isMesh)return
        if(n.userData.inkOutline){outlines.push(n);return}
        meshes.push(n)
        if(all)for(const key of ['position','normal','skinWeight'])if(n.geometry.attributes[key]&&!Array.from(n.geometry.attributes[key].array).every(Number.isFinite))invalid++
        if(n.skeleton){n.skeleton.update();if(!Array.from(n.skeleton.boneMatrices).every(Number.isFinite))invalid++}
      })
      const feet={};const p=root.position.clone()
      for(const mesh of meshes){
        if(!/^feiyi_leg_\d_[lr]$/.test(mesh.name))continue
        const g=mesh.geometry.attributes
        let min=Infinity
        for(let i=0;i<g.position.count;i++){
          if(!all&&g.position.getY(i)>.015)continue
          mesh.getVertexPosition(i,p);mesh.localToWorld(p)
          if(![...p].every(Number.isFinite))invalid++
          min=Math.min(min,p.y)
        }
        feet[mesh.name]=min
      }
      return {nodes,invalid,meshes:meshes.length,outlines:outlines.length,bones:bones.length,
        body:meshes.filter(n=>n.name==='feiyi_snake_body').length,
        legs:meshes.filter(n=>/^feiyi_leg_\d_[lr]$/.test(n.name)).length,
        wings:meshes.filter(n=>/^feiyi_wing_\d_[lr]$/.test(n.name)).length,
        spine:bones.filter(n=>/^serpent_\d\d$/.test(n.name)).length,feet}
    },full)
  }
  await page.waitForTimeout(700)
  report.baseline=await snapshot(true)
  for(const [key,value]of Object.entries({invalid:0,body:1,legs:6,wings:4,spine:24,meshes:11,outlines:11}))assert.equal(report.baseline[key],value,key)
  // Sample the actual loaded body's dorsal UV texels, excluding unused atlas
  // padding. This catches the previous near-black scales under the ink ramp.
  report.palette=await page.evaluate(()=>{
    const mesh=window.feiyiQA.state.scene.getObjectByName('feiyi_snake_body')
    const map=mesh.material.uniforms.uMap.value,canvas=document.createElement('canvas')
    canvas.width=map.image.width;canvas.height=map.image.height
    const ctx=canvas.getContext('2d');ctx.drawImage(map.image,0,0)
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data,g=mesh.geometry.attributes
    const linear=v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4
    const values=[]
    for(let i=0;i<g.position.count;i++){
      if(g.normal.getY(i)<.45)continue
      const x=Math.min(canvas.width-1,Math.max(0,Math.floor(g.uv.getX(i)*canvas.width)))
      const y=Math.min(canvas.height-1,Math.max(0,Math.floor(g.uv.getY(i)*canvas.height)))
      const k=(y*canvas.width+x)*4
      values.push(.2126*linear(pixels[k]/255)+.7152*linear(pixels[k+1]/255)+.0722*linear(pixels[k+2]/255))
    }
    values.sort((a,b)=>a-b)
    return {dorsalSamples:values.length,medianLinearLuminance:values[Math.floor(values.length/2)],nearBlackFraction:values.filter(v=>v<.02).length/values.length}
  })
  assert(report.palette.dorsalSamples>1000,'actual dorsal UV samples')
  assert(report.palette.medianLinearLuminance>.07&&report.palette.medianLinearLuminance<.3,'gray brown dorsal pigment range')
  assert(report.palette.nearBlackFraction<.05,'dorsal scales must not become a near-black field')
  for(const action of ['idle','walk','special']){
    await page.getByRole('button',{name:{idle:'静',walk:'行',special:'神通'}[action],exact:true}).click()
    const samples=[]
    for(let i=0;i<(action==='special'?44:22);i++){await page.waitForTimeout(120);samples.push(await snapshot(i%11===0))}
    assert(samples.every(s=>s.invalid===0&&s.legs===6&&s.wings===4))
    if(action==='walk')assert(samples.every(s=>Math.abs(Math.min(...Object.values(s.feet)))<.007),'planted support phase')
    else assert(samples.slice(4).every(s=>Object.values(s.feet).every(y=>Math.abs(y)<.007)),`${action} all six soles on ground`)
    report.actions[action]=samples
  }
  assert.equal(await page.evaluate(()=>window.feiyiQA.useApp.getState().action),'idle','special returns idle')
  await page.waitForTimeout(600)
  report.worldContact=await page.evaluate(async()=>{
    const {state,useApp}=window.feiyiQA;const root=state.scene.getObjectByName('feiyi_snake_root')
    state.scene.updateMatrixWorld(true)
    const points={};const p=root.position.clone()
    root.traverse(mesh=>{
      if(!mesh.isMesh||mesh.userData.inkOutline||!/^feiyi_leg_\d_[lr]$/.test(mesh.name))return
      mesh.skeleton.update();const g=mesh.geometry.attributes
      const list=[]
      for(let i=0;i<g.position.count;i++){
        const bone=mesh.skeleton.bones[g.skinIndex.getX(i)]?.name
        if(!bone?.endsWith('_foot')||g.skinWeight.getX(i)<.99999)continue
        mesh.getVertexPosition(i,p);mesh.localToWorld(p)
        if(Math.abs(p.y)>.002)continue
        list.push({mesh,i,x:g.position.getX(i),z:g.position.getZ(i)})
      }
      points[mesh.name]=list
    })
    for(const [leg,vertices]of Object.entries(points)){
      if(vertices.length<3)throw new Error(`${leg}: insufficient sole points`)
      const a=vertices[0]
      if(!vertices.some(b=>vertices.some(c=>Math.abs((b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x))>1e-6)))throw new Error(`${leg}: collinear sole`)
    }
    useApp.getState().setAction('walk');await new Promise(r=>setTimeout(r,650))
    const plants={};let cycles=0,previous=root.userData.animationTime,frames=0
    const start=performance.now()
    while(cycles<3){
      if(performance.now()-start>30000)throw new Error('gait cycles timed out')
      await new Promise(r=>requestAnimationFrame(r));state.scene.updateMatrixWorld(true)
      for(const mesh of new Set(Object.values(points).flat().map(p=>p.mesh)))mesh.skeleton.update()
      const t=root.userData.animationTime;if(t<previous-.5)cycles++;previous=t;frames++
      for(const [leg,vertices]of Object.entries(points)){
        const row=Number(leg.split('_')[2]),side=leg.endsWith('_l')?0:1
        const phase=t/2.4+((row+side)%2)*.5,p=phase%1
        if(p<.04||p>.66)continue
        const key=`${leg}/${cycles+Math.floor(phase)}`
        const positions=vertices.map(({mesh,i})=>{const q=root.position.clone();mesh.getVertexPosition(i,q);mesh.localToWorld(q);return q.toArray()})
        const vectors=positions.map(q=>root.position.clone().fromArray(q)),aPoint=vectors[0]
        const b=vectors.reduce((best,q)=>q.distanceToSquared(aPoint)>best.distanceToSquared(aPoint)?q:best,vectors[1])
        const tangent=b.clone().sub(aPoint).normalize()
        const cross=q=>q.clone().sub(aPoint).cross(tangent)
        const c=vectors.reduce((best,q)=>cross(q).lengthSq()>cross(best).lengthSq()?q:best,vectors[2])
        const normal=cross(c).normalize();if(normal.y<0)normal.negate()
        const plant=plants[key]??={leg,initial:positions,initialNormal:normal.toArray(),maxDrift:0,maxDirection:0,maxNormalChange:0,maxPlaneTilt:0,samples:0,minY:Infinity,maxY:-Infinity}
        plant.maxNormalChange=Math.max(plant.maxNormalChange,Math.acos(Math.max(-1,Math.min(1,normal.dot(root.position.clone().fromArray(plant.initialNormal))))))
        plant.maxPlaneTilt=Math.max(plant.maxPlaneTilt,Math.acos(Math.max(-1,Math.min(1,normal.y))))
        positions.forEach((q,i)=>{plant.maxDrift=Math.max(plant.maxDrift,Math.hypot(...q.map((v,j)=>v-plant.initial[i][j])));plant.minY=Math.min(plant.minY,q[1]);plant.maxY=Math.max(plant.maxY,q[1])})
        const a=positions[0],a0=plant.initial[0]
        for(let i=1;i<positions.length;i++){
          const one=positions[i].map((v,k)=>v-a[k]),two=plant.initial[i].map((v,k)=>v-a0[k]);const length=Math.hypot(...one)*Math.hypot(...two)
          if(length<1e-8)continue
          const dot=one.reduce((sum,v,k)=>sum+v*two[k],0)/length
          plant.maxDirection=Math.max(plant.maxDirection,Math.acos(Math.max(-1,Math.min(1,dot))))
        }
        plant.samples++;plants[key]=plant
      }
    }
    const measured=Object.values(plants).filter(p=>p.samples>10)
    return {frames,pointsPerFoot:Object.fromEntries(Object.entries(points).map(([k,v])=>[k,v.length])),plants:measured.map(({initial,...metrics})=>metrics),maxDrift:Math.max(...measured.map(p=>p.maxDrift)),maxDirection:Math.max(...measured.map(p=>p.maxDirection))}
  })
  assert.equal(Object.keys(report.worldContact.pointsPerFoot).length,6)
  for(const leg of Object.keys(report.worldContact.pointsPerFoot))assert(report.worldContact.plants.filter(p=>p.leg===leg).length>=2,`${leg} two stances`)
  assert(report.worldContact.maxDrift<.0006,`XYZ sole drift ${report.worldContact.maxDrift}`)
  assert(report.worldContact.maxDirection<Math.PI/3600,`sole direction drift ${report.worldContact.maxDirection}`)
  await page.evaluate(()=>window.feiyiQA.useApp.getState().setAction('special'));await page.waitForTimeout(1200)
  await page.evaluate(()=>window.feiyiQA.useApp.getState().setAction('walk'));await page.waitForTimeout(80)
  assert.equal((await snapshot()).invalid,0,'interrupt special')
  await page.evaluate(()=>window.feiyiQA.useApp.getState().setAction('idle'));await page.waitForTimeout(600)
  // Every timer must be cancelled when either the action or beast changes.
  await page.evaluate(async()=>{
    const url=performance.getEntriesByType('resource').find(r=>new URL(r.name).pathname==='/src/systems/audio/AudioEngine.ts').name
    const {audio}=await import(url);window.feiyiQA.audio=audio;window.feiyiQA.wingCalls=0
    const original=audio.wingFlutter.bind(audio)
    audio.wingFlutter=(...args)=>{window.feiyiQA.wingCalls++;return original(...args)}
  })
  await page.evaluate(()=>window.feiyiQA.useApp.getState().setAction('special'));await page.waitForTimeout(80)
  await page.evaluate(()=>window.feiyiQA.useApp.getState().setAction('idle'));await page.waitForTimeout(1600)
  report.interruptedWingCalls=await page.evaluate(()=>window.feiyiQA.wingCalls)
  assert.equal(report.interruptedWingCalls,0,'cancel both delayed flutter sounds on action change')
  for(let i=0;i<3;i++){
    await page.waitForFunction(()=>{
      const skeletons=new Set();window.feiyiQA.state.scene.getObjectByName('feiyi_snake_root')?.traverse(n=>{if(n.isSkinnedMesh)skeletons.add(n.skeleton)})
      return skeletons.size>0&&[...skeletons].every(s=>s.boneTexture!==null)
    })
    await page.evaluate(()=>{
      const skeletons=new Set(),materials=new Map()
      window.feiyiQA.state.scene.getObjectByName('feiyi_snake_root').traverse(n=>{
        if(n.isSkinnedMesh)skeletons.add(n.skeleton)
        if(n.isMesh)for(const m of Array.isArray(n.material)?n.material:[n.material])materials.set(m,0)
      })
      const textures=new Map([...skeletons].map(s=>[s.boneTexture,0]))
      window.feiyiQA.old={skeletons,textures,materials}
      for(const texture of textures.keys())texture.addEventListener('dispose',()=>textures.set(texture,textures.get(texture)+1))
      for(const material of materials.keys())material.addEventListener('dispose',()=>materials.set(material,materials.get(material)+1))
    })
    const before=await page.evaluate(()=>window.feiyiQA.wingCalls)
    await page.evaluate(()=>window.feiyiQA.useApp.getState().setAction('special'));await page.waitForTimeout(80)
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready jingwei')})
    await page.evaluate(()=>window.feiyiQA.useApp.getState().select('jingwei'));await ready
    await page.waitForTimeout(1600)
    assert.equal(await page.evaluate(()=>window.feiyiQA.wingCalls),before,'cancel flutter timers on unmount')
    const cleanup=await page.evaluate(()=>{
      const {textures,skeletons,materials}=window.feiyiQA.old
      return {textures:textures.size,textureDisposals:[...textures.values()],skeletons:skeletons.size,live:[...skeletons].filter(s=>s.boneTexture!==null).length,materials:materials.size,materialDisposals:[...materials.values()]}
    })
    assert(cleanup.textures>0&&cleanup.textureDisposals.every(n=>n===1)&&cleanup.live===0,'every skeleton texture released exactly once')
    assert(cleanup.materials===22&&cleanup.materialDisposals.every(n=>n===1),'every owned ink and outline material released exactly once')
    ready=page.waitForEvent('console',{predicate:m=>m.text().includes('[beast] ready feiyi_snake')})
    await page.evaluate(()=>window.feiyiQA.useApp.getState().select('feiyi_snake'));await ready
    const current=await snapshot(true)
    for(const key of ['nodes','invalid','meshes','outlines','bones','body','legs','wings','spine'])assert.equal(current[key],report.baseline[key],`remount ${key}`)
    const animations={}
    for(const action of ['idle','walk','special']){
      await page.evaluate(a=>window.feiyiQA.useApp.getState().setAction(a),action);await page.waitForTimeout(550)
      animations[action]=await page.evaluate(async()=>{
        const {state,old}=window.feiyiQA,root=state.scene.getObjectByName('feiyi_snake_root'),meshes=[],skeletons=new Set()
        root.traverse(n=>{if(n.isSkinnedMesh)skeletons.add(n.skeleton);if(n.isMesh&&!n.userData.inkOutline){const count=n.geometry.attributes.position.count;meshes.push({mesh:n,vertices:[0,Math.floor(count/4),Math.floor(count/2),Math.floor(3*count/4),count-1],start:null,maxDisplacement:0})}})
        let invalid=0
        const startTime=root.userData.animationTime
        for(let frame=0;frame<24;frame++){
          await new Promise(requestAnimationFrame);state.scene.updateMatrixWorld(true)
          for(const item of meshes){item.mesh.skeleton.update();const points=item.vertices.map(index=>item.mesh.getVertexPosition(index,root.position.clone()));if(!points.every(p=>p.toArray().every(Number.isFinite)))invalid++;if(!item.start)item.start=points;points.forEach((p,i)=>{item.maxDisplacement=Math.max(item.maxDisplacement,p.distanceTo(item.start[i]))})}
        }
        return {invalid,startTime,endTime:root.userData.animationTime,meshes:meshes.map(m=>({name:m.mesh.name,maxDisplacement:m.maxDisplacement})),freshSkeletons:[...skeletons].every(s=>!old.skeletons.has(s)),freshBoneTextures:[...skeletons].every(s=>s.boneTexture!==null&&!old.textures.has(s.boneTexture))}
      })
      const sample=animations[action]
      assert.equal(sample.invalid,0);assert(sample.freshSkeletons&&sample.freshBoneTextures,'fresh clone skeletons and GPU bone textures')
      assert(sample.endTime!==sample.startTime,'remounted clip advances')
      assert(sample.meshes.length===11&&sample.meshes.every(m=>m.maxDisplacement>1e-6),`all body, legs and wings keep deforming in ${action}`)
    }
    await page.evaluate(()=>window.feiyiQA.useApp.getState().setAction('idle'));await page.waitForTimeout(500)
    report.remounts.push({current,cleanup,animations,unmountedDelayedCalls:0})
  }
  report.cache=await page.evaluate(()=>{
    const sourceSkeletons=new Set();let sourceOutlines=0,ownedSkeletons=true
    window.feiyiSource.traverse(n=>{if(n.skeleton)sourceSkeletons.add(n.skeleton);if(n.userData.inkOutline)sourceOutlines++})
    window.feiyiQA.state.scene.getObjectByName('feiyi_snake_root').traverse(n=>{if(n.skeleton&&sourceSkeletons.has(n.skeleton))ownedSkeletons=false})
    return {snapshottedBeforeFirstMount:true,unchanged:window.feiyiSourceSnapshot()===window.feiyiSourceBefore,sharedResources:window.feiyiShared.size,sharedDisposals:window.feiyiSharedDisposals,sourceOutlines,ownedSkeletons}
  })
  assert(report.cache.unchanged&&report.cache.ownedSkeletons&&report.cache.sharedDisposals===0&&report.cache.sourceOutlines===0,'immutable cached source and shared resources')
  assert(report.worldContact.plants.every(p=>p.maxNormalChange<.005&&p.maxPlaneTilt<.02),'actual noncollinear sole plane stays flat')
  await page.addStyleTag({content:'.card,.actions,.scroll-wrap,.controls,.title{visibility:hidden!important}'})
  await page.evaluate(()=>{const {state}=window.feiyiQA;state.setFrameloop('never');state.controls.enabled=false})
  for(const [name,x,y,z]of [['front',0,1.2,6],['back',0,1.2,-6],['left',-6,1.5,0],['right',6,1.5,0],['dorsal',0,6,-.1]]){
    await page.evaluate(({x,y,z})=>{
      const {state}=window.feiyiQA;const root=state.scene.getObjectByName('feiyi_snake_root')
      const target=root.position.clone().add({x:0,y:.3,z:0}),offset=root.position.clone().set(x,y,z).applyQuaternion(root.quaternion)
      state.controls.enableDamping=false;state.camera.filmOffset=0;state.camera.updateProjectionMatrix()
      state.controls.target.copy(target);state.camera.position.copy(target).add(offset);state.camera.lookAt(target)
      state.advance(state.clock.elapsedTime+.001,true);state.scene.updateMatrixWorld(true)
    },{x,y,z})
    await page.waitForTimeout(150);const path=join(out,`angle-${name}.png`);await page.screenshot({path});report.angles.push(path)
  }
  await page.addStyleTag({content:'.card,.actions,.scroll-wrap,.controls,.title{visibility:visible!important}'})
  await page.evaluate(()=>{const {state}=window.feiyiQA;state.controls.enabled=true;state.setFrameloop('always')})
  report.font=await page.evaluate(async()=>{
    await document.fonts.load('16px "Shanhai Rare Han"','𧔥');await document.fonts.ready
    const source=document.querySelector('.card-source'),text=source.textContent
    const face=[...document.fonts].find(f=>f.family==='Shanhai Rare Han')
    return {loaded:face?.status,check:document.fonts.check('16px "Shanhai Rare Han"','𧔥'),preservedOriginal:text.includes('肥𧔥'),family:getComputedStyle(source).fontFamily}
  })
  assert(report.font.loaded==='loaded'&&report.font.check&&report.font.preservedOriginal,'original rare Han glyph loads through the production CSS')
  await page.locator('.story-btn').click();await page.waitForTimeout(1800)
  report.audio=await page.evaluate(async()=>{
    const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'))
    const el=audio.narrationEl,buffer=await audio.context.decodeAudioData(await (await fetch(el.src)).arrayBuffer())
    let energy=0,invalid=0
    for(let c=0;c<buffer.numberOfChannels;c++)for(const value of buffer.getChannelData(c)){if(!Number.isFinite(value))invalid++;energy+=value*value}
    return {src:el?.src,duration:el?.duration,currentTime:el?.currentTime,error:el?.error,context:audio.context?.state,decodedSeconds:buffer.duration,sampleRate:buffer.sampleRate,channels:buffer.numberOfChannels,invalid,decodedRMS:Math.sqrt(energy/(buffer.length*buffer.numberOfChannels))}
  })
  assert(report.audio.src.endsWith('/audio/narration/feiyi_snake.mp3')&&report.audio.currentTime>0&&report.audio.duration>90)
  assert.equal(report.audio.error,null)
  assert(report.audio.invalid===0&&report.audio.decodedRMS>.01&&report.audio.context==='running','finite decoded narration and active audio context')
  await page.locator('.story-btn').click()
  report.stopped=await page.evaluate(async()=>{const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'));return !audio.narrationEl&&!window.feiyiQA.useApp.getState().narrating})
  assert(report.stopped,'card narration stop')
  report.sfx=await page.evaluate(async()=>{
    const {audio}=await import(performance.getEntriesByType('resource').map(r=>r.name).find(u=>new URL(u).pathname==='/src/systems/audio/AudioEngine.ts'))
    const analyser=audio.context.createAnalyser();analyser.fftSize=2048;audio.sfx.connect(analyser)
    const samples=new Float32Array(analyser.fftSize);let peakRMS=0
    window.feiyiQA.useApp.getState().setAction('special')
    for(let i=0;i<52;i++){
      await new Promise(r=>setTimeout(r,30));analyser.getFloatTimeDomainData(samples)
      peakRMS=Math.max(peakRMS,Math.sqrt(samples.reduce((s,x)=>s+x*x,0)/samples.length))
    }
    audio.sfx.disconnect(analyser);analyser.disconnect();return {peakRMS,context:audio.context.state}
  })
  assert(report.sfx.peakRMS>.0001,'actual special wing SFX bus')
  await page.waitForFunction(()=>window.feiyiQA.useApp.getState().action==='idle',null,{timeout:20000})
  report.specialReturn='idle'
  assert.equal(errors.length,0,errors.join('\n'))
  console.log(JSON.stringify({baseline:report.baseline,worldContact:{frames:report.worldContact.frames,points:report.worldContact.pointsPerFoot,maxDrift:report.worldContact.maxDrift,maxDirection:report.worldContact.maxDirection},remounts:report.remounts.length,audio:report.audio,sfx:report.sfx,errors},null,2))
} finally {await writeFile(join(out,'browser-qa.json'),JSON.stringify(report,null,2));await browser.close()}
