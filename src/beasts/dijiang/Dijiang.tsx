import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import {
  AnimationMixer,
  LoopRepeat,
  MathUtils,
  Mesh,
  Object3D,
  Quaternion,
  Vector3,
  type AnimationAction,
  type Group,
  type Texture,
} from 'three'
import { useApp, type BeastAction } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline, inkify } from '../../systems/ink/inkify'
import { FoxFire } from '../../systems/vfx/FoxFire'
import {
  createLeg,
  createWing,
  prepareLegGeometry,
  prepareWingGeometry,
  WING_BONES,
  type Leg,
  type Wing,
} from './parts'

const BODY_URL = '/models/dijiang/body.glb'
const WING_URL = '/models/dijiang/wing.glb'
const LEG_URL = '/models/dijiang/leg.glb'

const FADE = 0.3
const SPECIAL_SECONDS = 5.5
const WALK_RADIUS = 1.05
const WALK_SPEED = 0.28
const ALERT_DISTANCE = 2.4

interface WingPose {
  /** 主翼向后掠角 */
  sweep: number
  /** 基础抬角 */
  elevation: number
  /** 扑翼振幅 */
  flapAmp: number
  /** 扑翼角速度 */
  flapSpeed: number
  /** 丹火强度 */
  fire: number
}

const POSES: Record<BeastAction, WingPose> = {
  idle: { sweep: 0.42, elevation: 0.18, flapAmp: 0.08, flapSpeed: 1.8, fire: 0.4 },
  walk: { sweep: 0.52, elevation: 0.28, flapAmp: 0.16, flapSpeed: 4.2, fire: 0.25 },
  special: { sweep: 0.22, elevation: 0.52, flapAmp: 0.38, flapSpeed: 6.2, fire: 2.4 },
}

const WING_SPECS: { bone: string; side: 1 | -1; isFront: boolean }[] = [
  { bone: 'wing_fl_attach', side: 1, isFront: true },
  { bone: 'wing_fr_attach', side: -1, isFront: true },
  { bone: 'wing_bl_attach', side: 1, isFront: false },
  { bone: 'wing_br_attach', side: -1, isFront: false },
]

const LEG_SPECS: { bone: string; side: 1 | -1; row: 0 | 1 | 2 }[] = [
  { bone: 'leg_fl_attach', side: 1, row: 0 },
  { bone: 'leg_fr_attach', side: -1, row: 0 },
  { bone: 'leg_ml_attach', side: 1, row: 1 },
  { bone: 'leg_mr_attach', side: -1, row: 1 },
  { bone: 'leg_bl_attach', side: 1, row: 2 },
  { bone: 'leg_br_attach', side: -1, row: 2 },
]

/** 六足三脚架步态单腿周期：前 60% 支撑相匀速后移，后 40% 摆动相抬起前送 */
function legCycle(p: number, duty = 0.6): [swing: number, lift: number] {
  if (p < duty) return [1 - 2 * (p / duty), 0]
  const q = (p - duty) / (1 - duty)
  const s = q * q * (3 - 2 * q)
  return [-1 + 2 * s, Math.sin(q * Math.PI)]
}

const _v = new Vector3()

export function Dijiang() {
  const body = useGLTF(BODY_URL)
  const wingGltf = useGLTF(WING_URL)
  const legGltf = useGLTF(LEG_URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null

  const root = useRef<Group>(null)
  const fire = useRef(0.4)
  const pose = useRef<WingPose>({ ...POSES.idle })
  const walk = useRef({ angle: Math.PI / 2, lastPhase: 0 })
  const specialStart = useRef(0)
  const clock = useRef(0)

  // ------------------------------------------------------------ 装配：囊体、四翼、六足
  const rig = useMemo(() => {
    const scene = body.scene
    scene.traverse((o) => {
      if (o instanceof Mesh) o.frustumCulled = false
    })
    inkify(scene, { saturation: 0.9, outline: 0.006 })
    scene.updateMatrixWorld(true)

    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) {
      const a = mixer.clipAction(clip)
      a.setLoop(LoopRepeat, Infinity)
      clips[clip.name] = a
    }

    const sceneQ = scene.getWorldQuaternion(new Quaternion())
    const makeHolder = (boneName: string) => {
      const attach = scene.getObjectByName(boneName)
      if (!attach) throw new Error(`帝江骨骼缺失: ${boneName}`)
      const holder = new Object3D()
      const restQ = attach.getWorldQuaternion(new Quaternion()).premultiply(sceneQ.clone().invert())
      const restS = attach.getWorldScale(new Vector3())
      holder.quaternion.copy(restQ.invert())
      holder.scale.set(1 / restS.x, 1 / restS.y, 1 / restS.z)
      return { attach, holder }
    }

    let wingMesh: Mesh | undefined
    wingGltf.scene.updateMatrixWorld(true)
    wingGltf.scene.traverse((o) => {
      if (!wingMesh && o instanceof Mesh) wingMesh = o
    })
    if (!wingMesh) throw new Error('帝江翼模型里没有网格')
    const { geometry: wingGeo, length: wingLen } = prepareWingGeometry(wingMesh)
    const wingMat = createInkMaterial({
      map: (wingMesh.material as { map?: Texture | null }).map ?? null,
      saturation: 0.92,
    })

    let legMesh: Mesh | undefined
    legGltf.scene.updateMatrixWorld(true)
    legGltf.scene.traverse((o) => {
      if (!legMesh && o instanceof Mesh) legMesh = o
    })
    if (!legMesh) throw new Error('帝江足模型里没有网格')
    const { geometry: legGeo, reach: legReach } = prepareLegGeometry(legMesh, 0.335)
    const legMat = createInkMaterial({
      map: (legMesh.material as { map?: Texture | null }).map ?? null,
      saturation: 0.88,
    })

    const mounts: { attach: Object3D; holder: Object3D }[] = []
    const wings: Wing[] = WING_SPECS.map((spec) => {
      const m = makeHolder(spec.bone)
      const w = createWing(wingGeo, wingMat, wingLen, spec.side, spec.isFront)
      w.pivot.add(createOutline(w.mesh, 0.0038))
      m.holder.add(w.pivot)
      mounts.push(m)
      return w
    })

    const legs: Leg[] = LEG_SPECS.map((spec) => {
      const m = makeHolder(spec.bone)
      const l = createLeg(legGeo, legMat, legReach, spec.side, spec.row)
      l.pivot.add(createOutline(l.mesh, 0.004))
      m.holder.add(l.pivot)
      mounts.push(m)
      return l
    })

    return { scene, mixer, clips, mounts, wings, legs }
  }, [body, wingGltf, legGltf])

  const tips = useMemo(() => rig.wings.map((w) => w.tip), [rig])

  useEffect(() => {
    for (const m of rig.mounts) m.attach.add(m.holder)
    if (import.meta.env.DEV) console.info('[beast] ready dijiang')
    return () => {
      for (const m of rig.mounts) m.attach.remove(m.holder)
      rig.mixer.stopAllAction()
    }
  }, [rig])

  // ------------------------------------------------------------ 动作切换
  const current = useRef<AnimationAction | null>(null)
  const play = (name: string) => {
    const next = rig.clips[name]
    if (!next || next === current.current) return
    next.reset().setEffectiveWeight(1).fadeIn(FADE).play()
    current.current?.fadeOut(FADE)
    current.current = next
  }

  const panOf = () => {
    if (!root.current) return 0
    root.current.getWorldPosition(_v).project(camera)
    return MathUtils.clamp(_v.x, -1, 1) * 0.8
  }

  useEffect(() => {
    if (action === 'walk') play('walk')
    else if (action === 'special') {
      play('alert')
      specialStart.current = clock.current
      fire.current = 3.0
      const pan = panOf()
      window.setTimeout(() => audio.dijiangSong(pan), 80)
      window.setTimeout(() => audio.wingFlutter(pan, 0.55), 220)
      window.setTimeout(() => audio.wingFlutter(pan, 0.55), 900)
    } else play('idle')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action, rig])

  // 待机时偶发编钟囊鸣
  useEffect(() => {
    if (action !== 'idle') return
    const id = window.setInterval(() => {
      if (Math.random() < 0.35) audio.dijiangSong(panOf())
    }, 20000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action])

  // ------------------------------------------------------------ 每帧
  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 1 / 20)
    clock.current += dt
    const t = clock.current
    const g = root.current
    if (!g) return

    // 行走：沿圆周轻快踱步
    if (action === 'walk') {
      walk.current.angle -= (WALK_SPEED / WALK_RADIUS) * dt
      const a = walk.current.angle
      g.position.set(Math.cos(a) * WALK_RADIUS, 0, Math.sin(a) * WALK_RADIUS)
      const yaw = Math.atan2(Math.sin(a), -Math.cos(a))
      g.rotation.y = MathUtils.damp(g.rotation.y, yaw, 6, dt)

      const walkAction = rig.clips.walk
      const phase = (walkAction.time % walkAction.getClip().duration) / walkAction.getClip().duration
      const last = walk.current.lastPhase
      const pan = panOf()
      if (phase < last || (last < 0.5 && phase >= 0.5)) {
        audio.footstep(pan, 0.42)
        window.setTimeout(() => audio.footstep(pan, 0.32), 45)
      }
      walk.current.lastPhase = phase
    } else if (action === 'special') {
      // 「是识歌舞」：神通时原地欢快旋身律动
      const danceT = t - specialStart.current
      const baseYaw = Math.PI / 2 - 0.3
      g.rotation.y = MathUtils.damp(g.rotation.y, baseYaw + Math.sin(danceT * 2.4) * 0.55, 5, dt)
      if (danceT > SPECIAL_SECONDS) setAction('idle')
    } else {
      const baseYaw = Math.PI / 2 - 0.3
      g.rotation.y = MathUtils.damp(g.rotation.y, baseYaw, 3, dt)
      g.getWorldPosition(_v)
      const near = camera.position.distanceTo(_v) < ALERT_DISTANCE
      play(near ? 'alert' : 'idle')
    }

    rig.mixer.update(dt)

    const p = pose.current
    const goal = POSES[action]
    for (const k of Object.keys(goal) as (keyof WingPose)[]) p[k] = MathUtils.damp(p[k], goal[k], 2.8, dt)

    // 四翼：前翼偏大偏高、后翼偏小偏低，翼面略向前下倾使正侧视角都能看到饱满意境的翎羽
    rig.wings.forEach((w) => {
      const phase = w.isFront ? 0 : -0.95
      const sweep = p.sweep + (w.isFront ? -0.14 : 0.22)
      const elev = p.elevation + (w.isFront ? 0.22 : -0.10)
      const flap = p.flapAmp * Math.sin(t * p.flapSpeed + phase)
      w.pivot.rotation.order = 'YZX'
      // 绕 +Y 正转把 +X 转往 -Z（后方）：左翼(+X)取 +sweep，右翼(-X)取 π - sweep，使四翼向身后舒展
      w.pivot.rotation.y = w.side === 1 ? sweep : Math.PI - sweep
      w.pivot.rotation.z = elev + flap
      w.pivot.rotation.x = (w.side === 1 ? -0.32 : 0.32) + 0.12 * Math.cos(t * p.flapSpeed + phase)
      w.bones.forEach((b, j) => {
        const k = j / WING_BONES
        b.rotation.z = 0.09 * Math.sin(t * p.flapSpeed - j * 0.55 + phase) * (0.3 + k)
        b.rotation.y = -0.05 * (0.2 + k)
      })
    })

    // 六足：待机稳立、行走三脚架交替迈步（fl+mr+bl 与 fr+ml+br）、神通随节拍踏舞
    rig.legs.forEach((l) => {
      // 中排腿向外微张，前后排略分列，稳托黄囊
      const splay = l.side * (l.row === 1 ? 0.14 : 0.08)
      l.pivot.rotation.z = splay
      const tripodGroup = (l.row + (l.side === 1 ? 0 : 1)) % 2
      if (action === 'walk') {
        const cyc = (t * 1.15 + tripodGroup * 0.5) % 1.0
        const [swing, lift] = legCycle(cyc)
        const u = -0.28 * swing
        const k = 0.35 * lift
        l.bones[0].rotation.x = u
        l.bones[1].rotation.x = k
        l.bones[2].rotation.x = -(u + k) + 0.12 * lift
      } else if (action === 'special') {
        const beat = Math.max(0, Math.sin(t * 5.2 + tripodGroup * Math.PI))
        const sway = Math.sin(t * 2.6 + l.row * 0.8) * 0.12
        l.bones[0].rotation.x = -0.22 * beat + sway
        l.bones[1].rotation.x = 0.36 * beat
        l.bones[2].rotation.x = -0.14 * beat - sway
      } else {
        const breath = Math.sin(t * Math.PI) * 0.03
        l.bones[0].rotation.x = (l.row - 1) * 0.08 + breath
        l.bones[1].rotation.x = -breath * 1.5
        l.bones[2].rotation.x = -(l.bones[0].rotation.x + l.bones[1].rotation.x)
      }
    })

    fire.current = MathUtils.damp(fire.current, p.fire, 1.8, dt)

    if (controls) {
      g.getWorldPosition(_v)
      _v.y = 0.52
      controls.target.x = MathUtils.damp(controls.target.x, _v.x, 2, dt)
      controls.target.y = MathUtils.damp(controls.target.y, _v.y, 2, dt)
      controls.target.z = MathUtils.damp(controls.target.z, _v.z, 2, dt)
    }
  })

  return (
    <>
      <group ref={root} position={[0, 0, WALK_RADIUS]} rotation-y={Math.PI / 2 - 0.3}>
        <primitive object={rig.scene} />
      </group>
      <FoxFire emitters={tips} intensity={fire} coreColor="#e87a38" edgeColor="#a82418" />
    </>
  )
}

useGLTF.preload(BODY_URL)
useGLTF.preload(WING_URL)
useGLTF.preload(LEG_URL)
