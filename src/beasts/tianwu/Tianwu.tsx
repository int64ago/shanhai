import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { Bone, Group, Matrix4, Quaternion, SkinnedMesh, Vector3, type Material, type MeshStandardMaterial, type PerspectiveCamera } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'

const SCALE = .60, HEADING = -.10, DUTY = .68, PERIOD = 4, STRIDE = .06
const RADIUS = SCALE * .40 / DUTY, SPEED = SCALE * STRIDE / (PERIOD * DUTY), OMEGA = SPEED / RADIUS
const SOURCE_RADIUS = RADIUS / SCALE
const ANCHORS = [-.368, .3765, .732, 1.4765]
const Y = new Vector3(0, 1, 0), Z = new Vector3(0, 0, 1)
type Placement = { deformation: number[][][]; pivots: number[][] }
type Plan = { version: number; heads: Placement[]; tails: Placement[] }
type Mounted = { scene: Group; bones: Map<string, Bone>; rest: Map<string, Matrix4>; meshes: SkinnedMesh[] }
type Limb = Mounted & { foot: number; phase: number; ankle: Vector3; hip: Vector3; knee: Vector3; soleIds: number[]; pawIds: number[]; anchorIds: number[]; mesh: SkinnedMesh }
const matrix = (rows: number[][]) => new Matrix4().set(...rows.flat() as Parameters<Matrix4['set']>)
const translation = (p: Vector3) => new Matrix4().makeTranslation(p.x, p.y, p.z)
function around(p: Vector3, rotation: Matrix4) { return translation(p).multiply(rotation).multiply(translation(p.clone().negate())) }
function segment(a: Vector3, b: Vector3, c: Vector3, d: Vector3) {
  const before = b.clone().sub(a), after = d.clone().sub(c)
  const q = new Quaternion().setFromUnitVectors(before.normalize(), after.normalize())
  return translation(c).multiply(new Matrix4().makeRotationFromQuaternion(q)).multiply(translation(a.clone().negate()))
}
function mount(source: Group, selected?: string): Mounted {
  const scene = clone(source) as Group, bones = new Map<string, Bone>(), rest = new Map<string, Matrix4>(), meshes: SkinnedMesh[] = []
  scene.traverse(node => {
    if (node instanceof Bone) { bones.set(node.name, node); rest.set(node.name, node.matrix.clone()) }
    if (node instanceof SkinnedMesh) { node.visible = !selected || node.name.startsWith(selected); if (node.visible) meshes.push(node) }
  })
  scene.updateMatrixWorld(true)
  for (const mesh of meshes) mesh.skeleton.update()
  return { scene, bones, rest, meshes }
}
function bindPoint(part: Mounted, mesh: SkinnedMesh, index: number, target: Vector3) {
  mesh.getVertexPosition(index,target);mesh.localToWorld(target);part.scene.worldToLocal(target)
  return target
}
function setBone(rig: Mounted, name: string, deformation: Matrix4) {
  const bone = rig.bones.get(name)
  if (!bone) throw new Error(`Tianwu native rig missing ${name}`)
  bone.matrixAutoUpdate = false
  bone.matrix.copy(deformation).multiply(rig.rest.get(name)!)
  bone.matrixWorldNeedsUpdate = true
}
function hermite(a: Vector3, b: Vector3, va: Vector3, vb: Vector3, u: number, duration: number) {
  return a.clone().multiplyScalar(2*u*u*u-3*u*u+1).addScaledVector(va, (u*u*u-2*u*u+u)*duration)
    .addScaledVector(b, -2*u*u*u+3*u*u).addScaledVector(vb, (u*u*u-u*u)*duration)
}
function stance(ankle: Vector3, elapsed: number) {
  const angle = OMEGA * elapsed, c = Math.cos(angle), s = Math.sin(angle)
  const x = ankle.x - .75 - STRIDE / 2, lateral = -ankle.z
  return new Vector3(.75 + SOURCE_RADIUS*s+c*x+s*lateral, ankle.y, -(SOURCE_RADIUS*(c-1)-s*x+c*lateral))
}
function soleTarget(limb: Limb, time: number) {
  const phase = ((time/PERIOD+limb.phase)%1+1)%1
  if (phase < DUTY) return { position: stance(limb.ankle, phase*PERIOD), yaw: -OMEGA*phase*PERIOD }
  const duration = PERIOD*(1-DUTY), elapsed = DUTY*PERIOD, u = (phase-DUTY)/(1-DUTY), epsilon = 1e-4
  const a = stance(limb.ankle, elapsed), b = stance(limb.ankle, 0)
  const va = stance(limb.ankle, elapsed+epsilon).sub(stance(limb.ankle, elapsed-epsilon)).multiplyScalar(.5/epsilon)
  const vb = stance(limb.ankle, epsilon).sub(stance(limb.ankle, -epsilon)).multiplyScalar(.5/epsilon)
  const position = hermite(a,b,va,vb,u,duration)
  position.y += .038*Math.sin(Math.PI*u)**2
  const start = -OMEGA*elapsed
  const yaw = (2*u*u*u-3*u*u+1)*start + (u*u*u-2*u*u+u)*duration*(-OMEGA) + (u*u*u-u*u)*duration*(-OMEGA)
  return { position, yaw }
}
function poseLeg(limb: Limb, time: number, walking: boolean) {
  const { position: target, yaw } = walking ? soleTarget(limb,time) : { position: limb.ankle.clone(), yaw: 0 }
  const h = limb.hip, k = limb.knee, a = limb.ankle
  const l1 = h.distanceTo(k), l2 = k.distanceTo(a), axis = target.clone().sub(h), distance = axis.length()
  axis.normalize()
  const along = (l1*l1-l2*l2+distance*distance)/(2*distance)
  const radius = Math.sqrt(Math.max(0,l1*l1-along*along))
  const bend = k.clone().sub(h).addScaledVector(axis,-k.clone().sub(h).dot(axis)).normalize()
  const knee = h.clone().addScaledVector(axis,along).addScaledVector(bend,radius)
  setBone(limb,'anchor',new Matrix4())
  setBone(limb,'upper',segment(h,k,h,knee))
  setBone(limb,'lower',segment(k,a,knee,target))
  const sole = new Matrix4().makeRotationY(yaw)
  sole.setPosition(target.clone().sub(a.clone().applyMatrix4(sole)))
  setBone(limb,'sole',sole)
}
function poseChain(rig: Mounted, placement: Placement, index: number, time: number, action: string, head: boolean) {
  let motion = new Matrix4()
  for (let j=0;j<5;j++) {
    // Two basal sections stay fixed in the shared shoulder/sacral tissue.
    if (j>=2) {
      const amplitude = action==='special' ? .075 : action==='walk' ? .025 : .012
      const angle = Math.sin(time*1.5-index*.51-j*.6)*amplitude*(head ? .65 : 1)
      const rotation = new Matrix4().makeRotationAxis(j%2 ? Y : Z,angle)
      motion = motion.clone().multiply(around(new Vector3().fromArray(placement.pivots[j]),rotation))
    }
    setBone(rig,`segment_${j}`,motion.clone().multiply(matrix(placement.deformation[j])))
  }
  if (head) setBone(rig,'cranium',motion.clone().multiply(matrix(placement.deformation[5])))
}

export function Tianwu() {
  const body = useGLTF('/models/tianwu/body.glb'), leg = useGLTF('/models/tianwu/leg.glb')
  const head = useGLTF('/models/tianwu/headneck.glb'), tail = useGLTF('/models/tianwu/tail.glb')
  const action = useApp(s=>s.action), setAction = useApp(s=>s.setAction), camera = useThree(s=>s.camera)
  const controls=useThree(s=>s.controls) as unknown as {target:Vector3;enabled:boolean;update:()=>void}|undefined
  const root = useRef<Group>(null), controlled = useRef(false), walkTime = useRef(0), clock = useRef(0), specialTime = useRef(0)
  const rig = useMemo(()=>{
    let plan: Plan | undefined
    body.scene.traverse(node=>{ if (node.userData.tianwuNativePlan) plan=JSON.parse(node.userData.tianwuNativePlan) as Plan })
    if (!plan || plan.version!==1) throw new Error('Tianwu native placement plan missing')
    const content = new Group(); content.rotation.y=Math.PI/2; content.position.z=.75
    const trunk=mount(body.scene), heads=Array.from({length:8},()=>mount(head.scene)), tails=Array.from({length:8},()=>mount(tail.scene))
    const limbs: Limb[]=[]
    for (let pair=0;pair<4;pair++) for (const side of [-1,1]) {
      const mounted=mount(leg.scene,side<0?'leg_negative_y':'leg_positive_y'), mesh=mounted.meshes[0]
      if (!mesh) throw new Error('Tianwu native leg prototype missing')
      const p=mesh.geometry.attributes.position, point=new Vector3(), ankle=new Vector3(), soleIds:number[]=[],pawIds:number[]=[],coordinates=new Map<number,Vector3>()
      for(let i=0;i<p.count;i++) {
        bindPoint(mounted,mesh,i,point)
        if(point.y<.078)pawIds.push(i)
        if(point.y<.022) {soleIds.push(i);ankle.add(point);coordinates.set(i,point.clone())}
      }
      const anchorIds=[...new Set(['x','z'].flatMap(axis=>[-1,1].map(sign=>soleIds.reduce((best,id)=>sign*coordinates.get(id)![axis as 'x'|'z']>sign*coordinates.get(best)![axis as 'x'|'z']?id:best,soleIds[0]))))]
      if (soleIds.length<10) throw new Error('Tianwu actual sole mask empty')
      ankle.multiplyScalar(1/soleIds.length); ankle.y=.09
      const hip=new Vector3(-.368,.37,ankle.z*.70), knee=new Vector3(-.31,.23,ankle.z*.90)
      mounted.scene.position.x=ANCHORS[pair]+.368
      // Circle compensation includes each translated foot's full pivot offset.
      const offset=mounted.scene.position.x
      ankle.x+=offset;hip.x+=offset;knee.x+=offset
      limbs.push({...mounted,mesh,foot:pair*2+(side>0?1:0),phase:(pair*.25+(side>0?.5:0))%1,ankle,hip,knee,soleIds,pawIds,anchorIds})
    }
    const headSamples=heads.map(part=>{
      const mesh=part.meshes[0],point=new Vector3(),ids:number[]=[]
      for(let i=0;i<mesh.geometry.attributes.position.count;i++)if(bindPoint(part,mesh,i,point).y>=1.0)ids.push(i)
      return {mesh,ids:ids.filter((_,i)=>i%Math.max(1,Math.floor(ids.length/24))===0).slice(0,24)}
    })
    // Scene assembly is performed in the effect; this memo only creates owned objects.
    return {content,trunk,heads,tails,limbs,plan,headSamples,all:[trunk,...heads,...tails,...limbs]}
  },[body,leg,head,tail])
  function route(time:number) {
    if(!root.current)return
    const angle=OMEGA*time, x=-RADIUS*Math.cos(angle), z=RADIUS*Math.sin(angle)
    root.current.rotation.y=HEADING+angle
    root.current.position.set(Math.cos(HEADING)*x+Math.sin(HEADING)*z,0,-Math.sin(HEADING)*x+Math.cos(HEADING)*z)
  }
  function pose(name:string,time:number,locomotion:boolean) {
    route(locomotion?time:walkTime.current)
    setBone(rig.trunk,'core',new Matrix4())
    rig.heads.forEach((part,i)=>poseChain(part,rig.plan.heads[i],i,time,name,true))
    rig.tails.forEach((part,i)=>poseChain(part,rig.plan.tails[i],i,time,name,false))
    for(const limb of rig.limbs) {
      // Solve in the full animal frame, then conjugate into this shared prototype.
      poseLeg(limb,time,name==='walk')
      const offset=limb.scene.position.x
      for(const bone of limb.bones.values()) {
        bone.matrix.premultiply(new Matrix4().makeTranslation(-offset,0,0)).multiply(new Matrix4().makeTranslation(offset,0,0))
      }
    }
    rig.content.updateMatrixWorld(true)
    for(const part of rig.all) for(const mesh of part.meshes) mesh.skeleton.update()
  }
  useEffect(()=>{
    for(const part of rig.all) rig.content.add(part.scene)
    const resources=rig.all.flatMap(part=>part.meshes).map(mesh=>{
      const original=mesh.material as MeshStandardMaterial
      const material=createInkMaterial({map:original.map??null,saturation:.76,inkBoost:0})
      if(mesh.geometry.hasAttribute('color')) {
        material.vertexColors=true
        material.vertexShader=material.vertexShader.replace('varying vec2 vUv;','varying vec3 vPigment;\n varying vec2 vUv;').replace('vUv = uv;','vUv = uv; vPigment = color.rgb;')
        material.fragmentShader=material.fragmentShader.replace('varying vec2 vUv;','varying vec3 vPigment;\n varying vec2 vUv;').replace('vec3 albedo = uHasMap > 0.5 ? texture2D(uMap, vUv).rgb : vec3(0.6);','vec3 albedo = uHasMap > 0.5 ? texture2D(uMap, vUv).rgb * vPigment : vPigment;')
      }
      const outline=createOutline(mesh,.0018);mesh.material=material;mesh.frustumCulled=false;mesh.parent!.add(outline)
      return {mesh,original,material,outline}
    })
    pose(useApp.getState().action,0,false)
    if(import.meta.env.DEV)console.info('[beast] ready tianwu')
    return ()=>{
      for(const {mesh,original,material,outline} of resources) {outline.removeFromParent();(outline.material as Material).dispose();mesh.material=original;material.dispose()}
      const owned=new Set<SkinnedMesh['skeleton']>()
      for(const part of rig.all) {part.scene.traverse(node=>{if(node instanceof SkinnedMesh)owned.add(node.skeleton)});part.scene.removeFromParent()}
      for(const skeleton of owned)skeleton.dispose()
    }
  },[rig])
  useEffect(()=>{specialTime.current=0},[action])
  useFrame((_,rawDt)=>{
    if(controlled.current)return
    const dt=Math.min(rawDt,.05);clock.current+=dt
    if(action==='walk') {const before=walkTime.current;walkTime.current+=dt;if(Math.floor(before*2)!==Math.floor(walkTime.current*2))audio.footstep(0,.16)}
    pose(action,action==='walk'?walkTime.current:clock.current,false)
    if(action==='walk')route(walkTime.current)
    if(action==='special') {specialTime.current+=dt;if(specialTime.current>=5)setAction('idle')}
  })
  useEffect(()=>{
    if(!import.meta.env.DEV)return
    const sample=new Vector3()
    const headSamples=rig.headSamples
    let originalView: {position:Vector3;quaternion:Quaternion;target:Vector3;zoom:number;filmOffset:number;enabled:boolean}|null=null
    const api={useApp,cameraState(){return {position:camera.position.toArray(),quaternion:camera.quaternion.toArray(),target:controls?.target.toArray()??[0,.6,0],zoom:camera.zoom,filmOffset:(camera as PerspectiveCamera).filmOffset,fov:(camera as PerspectiveCamera).fov}},view(kind:string){
      if(kind==='restore') {
        if(!originalView)return
        camera.position.copy(originalView.position);camera.quaternion.copy(originalView.quaternion)
        camera.zoom=originalView.zoom;(camera as PerspectiveCamera).filmOffset=originalView.filmOffset
        if(controls){controls.target.copy(originalView.target);controls.enabled=originalView.enabled}
        originalView=null
      } else {
        originalView??={position:camera.position.clone(),quaternion:camera.quaternion.clone(),target:controls?.target.clone()??new Vector3(0,.6,0),zoom:camera.zoom,filmOffset:(camera as PerspectiveCamera).filmOffset,enabled:controls?.enabled??true}
        rig.content.updateWorldMatrix(true,true)
        let center=new Vector3(...(kind==='shoulder'?[-.2,.68,0]:kind==='hips'?[.72,.4,.17]:[1.45,.7,0]) as [number,number,number]).applyMatrix4(rig.content.matrixWorld)
        if(kind==='face') {
          center=new Vector3();const head=headSamples[3]
          for(const id of head.ids){head.mesh.getVertexPosition(id,sample);head.mesh.localToWorld(sample);center.add(sample)}
          center.multiplyScalar(1/head.ids.length)
        }
        camera.position.copy(center).add(kind==='tails'?new Vector3(1.6,.7,-2.4):new Vector3(1.6,.7,2.4))
        camera.zoom=kind==='face'?4:kind==='tails'?1.8:2.3;(camera as PerspectiveCamera).filmOffset=0
        if(controls){controls.enabled=false;controls.target.copy(center)}
        camera.lookAt(center)
      }
      camera.updateProjectionMatrix();camera.updateMatrixWorld(true)
    },sample(name:string,time:number,locomotion=false){
      controlled.current=true;pose(name,time,locomotion)
      root.current?.updateMatrixWorld(true)
      for(const part of rig.all)for(const mesh of part.meshes)mesh.skeleton.update()
      const points=(mesh:SkinnedMesh,ids:number[])=>ids.map(i=>{mesh.getVertexPosition(i,sample);mesh.localToWorld(sample);return sample.toArray()})
      const feet=rig.limbs.map(l=>({foot:l.foot,count:l.soleIds.length,pawCount:l.pawIds.length,anchorVertexIds:l.anchorIds,points:points(l.mesh,[...new Set([...l.anchorIds,...l.soleIds.filter((_,i)=>i%Math.max(1,Math.floor(l.soleIds.length/10))===0).slice(0,10)])]),pawPoints:points(l.mesh,l.pawIds.filter((_,i)=>i%Math.max(1,Math.floor(l.pawIds.length/24))===0).slice(0,24))}))
      const heads=headSamples.map((h,head)=>({head,points:points(h.mesh,h.ids)}))
      const projected:number[][]=[];let outlines=0
      rig.content.traverse(node=>{if(node.userData.inkOutline)outlines++})
      for(const part of rig.all)for(const mesh of part.meshes)for(let i=0;i<mesh.geometry.attributes.position.count;i+=113){mesh.getVertexPosition(i,sample);mesh.localToWorld(sample).project(camera);projected.push(sample.toArray())}
      return {feet,heads,outlines,sharing:{headGeometries:new Set(rig.heads.flatMap(p=>p.meshes.map(m=>m.geometry))).size,tailGeometries:new Set(rig.tails.flatMap(p=>p.meshes.map(m=>m.geometry))).size,legGeometries:new Set(rig.limbs.map(p=>p.mesh.geometry)).size,skeletons:new Set(rig.all.flatMap(p=>p.meshes.map(m=>m.skeleton))).size},skins:rig.all.reduce((sum,p)=>sum+p.meshes.length,0),clips:['idle','walk','special'],speed:SPEED,route:{radius:RADIUS,angularSpeed:OMEGA,period:2*Math.PI/OMEGA},screenBounds:{minX:Math.min(...projected.map(p=>p[0])),maxX:Math.max(...projected.map(p=>p[0])),minY:Math.min(...projected.map(p=>p[1])),maxY:Math.max(...projected.map(p=>p[1]))}}
    },clearance(name:string,time:number,rects:{name:string;x:number;y:number;width:number;height:number}[],step=113){
      controlled.current=true;pose(name,time,true);root.current?.updateMatrixWorld(true)
      for(const part of rig.all)for(const mesh of part.meshes)mesh.skeleton.update()
      let minimum=Infinity,closest={ui:'',x:0,y:0},samples=0,vertices=0
      for(const part of rig.all)for(const mesh of part.meshes) {
        const count=mesh.geometry.attributes.position.count;vertices+=count
        for(let i=0;i<count;i+=step) {
          mesh.getVertexPosition(i,sample);mesh.localToWorld(sample).project(camera)
          const x=(sample.x+1)*innerWidth/2,y=(1-sample.y)*innerHeight/2;samples++
          for(const rect of rects) {
            const right=rect.x+rect.width,bottom=rect.y+rect.height
            const dx=Math.max(rect.x-x,0,x-right),dy=Math.max(rect.y-y,0,y-bottom)
            const distance=dx||dy?Math.hypot(dx,dy):-Math.min(x-rect.x,right-x,y-rect.y,bottom-y)
            if(distance<minimum){minimum=distance;closest={ui:rect.name,x,y}}
          }
        }
      }
      return {minimumPx:minimum,closest,step,samples,vertices}
    },observe(){return {clock:clock.current,walkTime:walkTime.current,action:useApp.getState().action,head:rig.heads[0].bones.get('cranium')!.matrix.toArray()}},resume(){controlled.current=false}}
    const target=window as typeof window & {tianwuQA?:typeof api};target.tianwuQA=api
    return ()=>{api.view('restore');if(target.tianwuQA===api)delete target.tianwuQA}
  },[rig,camera,controls])
  useEffect(()=>{
    if(!controls)return
    // Other beasts follow their moving roots; Tianwu uses a fixed stage origin.
    const previousTarget=controls.target.clone()
    controls.target.set(0,.6,0);controls.update()
    return ()=>{controls.target.copy(previousTarget);controls.update()}
  },[controls])
  return <group ref={root} rotation-y={HEADING} position={[-RADIUS*Math.cos(HEADING),0,RADIUS*Math.sin(HEADING)]} scale={SCALE} dispose={null}><primitive object={rig.content} dispose={null}/></group>
}
