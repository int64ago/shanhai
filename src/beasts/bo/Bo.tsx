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
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline, inkify } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'
import { FoxFire } from '../../systems/vfx/FoxFire'
import { aimTail, createTail, prepareTailGeometry, TAIL_BONES } from '../jiuweihu/tails'

const BODY_URL = '/models/bo/body.glb'
const TAIL_URL = '/models/jiuweihu/tail.glb'
const FADE = 0.28
const SPECIAL_SECONDS = 4.6
const WALK_RADIUS = 1.15
const WALK_SPEED = 0.34
const ALERT_DISTANCE = 2.4

interface TailPose {
  elevation: number
  curl: number
  amp: number
  speed: number
  fire: number
}

// 驳（白身黑尾）：待机垂尾微拂、驰行扬尾、神通「音如鼓·御兵」昂首振尾
const POSES: Record<BeastAction, TailPose> = {
  idle: { elevation: -0.28, curl: -0.14, amp: 0.07, speed: 1.4, fire: 0.18 },
  walk: { elevation: 0.08, curl: -0.1, amp: 0.15, speed: 3.8, fire: 0.1 },
  special: { elevation: 0.58, curl: 0.14, amp: 0.18, speed: 4.5, fire: 2.1 },
}

const _v = new Vector3()

export function Bo() {
  const body = useGLTF(BODY_URL)
  const tailGltf = useGLTF(TAIL_URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null

  const root = useRef<Group>(null)
  const fire = useRef(0)
  const pose = useRef<TailPose>({ ...POSES.idle })
  const walk = useRef({ angle: Math.PI / 2, lastPhase: 0 })
  const specialStart = useRef(0)
  const clock = useRef(0)

  const rig = useMemo(() => {
    const scene = body.scene
    scene.traverse((o) => {
      if (o instanceof Mesh) o.frustumCulled = false
    })
    // 驳：白身黑尾、虎牙爪，贴图保持素白与玄黑的高对比工笔设色
    inkify(scene, { saturation: 0.78, outline: 0.006 })
    scene.updateMatrixWorld(true)

    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) {
      const a = mixer.clipAction(clip)
      a.setLoop(LoopRepeat, Infinity)
      clips[clip.name] = a
    }

    const bone = (name: string) => {
      const b = scene.getObjectByName(name)
      if (!b) throw new Error(`驳骨骼缺失: ${name}`)
      return b
    }
    const attach = bone('tail_attach')
    const head = bone('head')

    const holder = new Object3D()
    holder.name = 'bo_tail_holder'
    const sceneQ = scene.getWorldQuaternion(new Quaternion())
    const restQ = attach.getWorldQuaternion(new Quaternion()).premultiply(sceneQ.invert())
    const restS = attach.getWorldScale(new Vector3())
    holder.quaternion.copy(restQ.invert())
    holder.scale.set(1 / restS.x, 1 / restS.y, 1 / restS.z)
    holder.position.set(0, 0.055, 0.025)

    // 独角灵芒挂点（位于额顶一角尖端）
    const hornTip = new Object3D()
    hornTip.name = 'bo_horn_tip'
    hornTip.position.set(0, 0.24, 0.14)

    let tailMesh: Mesh | undefined
    tailGltf.scene.updateMatrixWorld(true)
    tailGltf.scene.traverse((o) => {
      if (!tailMesh && o instanceof Mesh) tailMesh = o
    })
    if (!tailMesh) throw new Error('尾巴模型里没有网格')
    const { geometry, length } = prepareTailGeometry(tailMesh, 0.18)

    // 「白身黑尾」：浓墨玄尾，尾梢不留白，配飞白笔锋
    const tailMaterial = createInkMaterial({
      map: (tailMesh.material as { map?: Texture | null }).map ?? null,
      saturation: 0.35,
      tailLength: length,
      tint: '#201d1a',
      inkBoost: 0.76,
    })
    const tail = createTail(geometry, tailMaterial, length)
    tail.pivot.add(createOutline(tail.mesh, 0.0038))
    holder.add(tail.pivot)

    return { scene, mixer, clips, attach, head, holder, hornTip, tail }
  }, [body, tailGltf])

  const emitters = useMemo(() => [rig.hornTip, rig.tail.tip], [rig])

  useEffect(() => {
    rig.attach.add(rig.holder)
    rig.head.add(rig.hornTip)
    if (import.meta.env.DEV) console.info('[beast] ready bo')
    return () => {
      rig.attach.remove(rig.holder)
      rig.head.remove(rig.hornTip)
      rig.mixer.stopAllAction()
    }
  }, [rig])

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
      window.setTimeout(() => audio.boDrumRoar(pan), 100)
    } else play('idle')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action, rig])

  useEffect(() => {
    if (action !== 'idle') return
    const id = window.setInterval(() => {
      if (Math.random() < 0.3) audio.boDrumRoar(panOf())
    }, 20000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 1 / 20)
    clock.current += dt
    const t = clock.current
    const g = root.current
    if (!g) return

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
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((last < beat && phase >= beat) || (beat === 0 && phase < last)) {
          audio.footstep(pan, beat % 0.5 === 0 ? 0.52 : 0.4)
        }
      }
      walk.current.lastPhase = phase
    }

    if (action === 'special') {
      const elapsed = t - specialStart.current
      if (elapsed > SPECIAL_SECONDS) setAction('idle')
      // 「音如鼓，食虎豹」：神通蓄势微昂前躯
      const rear = Math.sin(Math.min(elapsed / 1.2, 1) * Math.PI) * 0.1
      g.rotation.x = MathUtils.damp(g.rotation.x, -rear, 6, dt)
    } else {
      g.rotation.x = MathUtils.damp(g.rotation.x, 0, 6, dt)
    }

    if (action === 'idle') {
      g.getWorldPosition(_v)
      const near = camera.position.distanceTo(_v) < ALERT_DISTANCE
      play(near ? 'alert' : 'idle')
    }

    rig.mixer.update(dt)

    const p = pose.current
    const goal = POSES[action]
    for (const k of Object.keys(goal) as (keyof TailPose)[]) p[k] = MathUtils.damp(p[k], goal[k], 2.8, dt)

    // 浓墨长马尾：随呼吸与奔跑行波轻拂
    const sway = Math.sin(t * p.speed * 0.65) * 0.16
    aimTail(rig.tail.pivot, p.elevation, sway)
    rig.tail.bones.forEach((b, j) => {
      const k = j / TAIL_BONES
      b.rotation.z = p.curl * (0.25 + k) + p.amp * Math.sin(t * p.speed - j * 0.65) * (0.35 + k)
      b.rotation.y = p.amp * 0.85 * Math.cos(t * p.speed * 0.75 - j * 0.55)
    })

    fire.current = MathUtils.damp(fire.current, p.fire, 1.6, dt)

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
      <group ref={root} position={[0, 0, WALK_RADIUS]} rotation-y={Math.PI / 2 - 0.22}>
        <primitive object={rig.scene} />
      </group>
      <FoxFire emitters={emitters} intensity={fire} />
    </>
  )
}

useGLTF.preload(BODY_URL)
useGLTF.preload(TAIL_URL)
