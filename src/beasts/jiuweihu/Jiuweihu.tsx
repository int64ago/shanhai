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
  type Texture,
  type Group,
} from 'three'
import { useApp, type BeastAction } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline, inkify } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'
import { FoxFire } from '../../systems/vfx/FoxFire'
import { aimTail, createTail, prepareTailGeometry, TAIL_BONES, type Tail } from './tails'

const BODY_URL = '/models/jiuweihu/body.glb'
const TAIL_URL = '/models/jiuweihu/tail.glb'
const TAIL_COUNT = 9
const FADE = 0.3
const SPECIAL_SECONDS = 5
const WALK_RADIUS = 1.1
// 步幅约 0.3 m（身长 1 m），步态周期 1 s；行进速度要与之匹配，否则脚底打滑
const WALK_SPEED = 0.3
/** 镜头靠得比这更近时，待机自动转为警觉 */
const ALERT_DISTANCE = 2.4

interface TailPose {
  spread: number
  elevation: number
  curl: number
  amp: number
  speed: number
  fire: number
}

// 三种状态下九尾的形态：待机半展、行走拖曳、神通开屏
const POSES: Record<BeastAction, TailPose> = {
  idle: { spread: 1.3, elevation: 0.72, curl: 0.14, amp: 0.09, speed: 1.5, fire: 0.35 },
  walk: { spread: 0.65, elevation: 0.32, curl: 0.06, amp: 0.14, speed: 3.6, fire: 0.12 },
  special: { spread: 1.75, elevation: 1.05, curl: 0.22, amp: 0.07, speed: 2.4, fire: 2.2 },
}

const _v = new Vector3()

export function Jiuweihu() {
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

  // ------------------------------------------------------------ 装配：动画、骨骼、九尾
  const rig = useMemo(() => {
    const scene = body.scene
    scene.traverse((o) => {
      if (o instanceof Mesh) o.frustumCulled = false
    })
    inkify(scene, { saturation: 0.85, outline: 0.006 })
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
      if (!b) throw new Error(`九尾狐骨骼缺失: ${name}`)
      return b
    }
    const attach = bone('tail_attach')

    // 尾巴挂点：抵消挂接骨骼的静止朝向，让尾巴的基础坐标系和身体对齐
    // 注意：不在 useMemo 里直接把 holder 挂到 attach 上（React 19 StrictMode 会调用两次 useMemo 并丢弃第二次返回值）
    const holder = new Object3D()
    holder.name = 'tail_holder'
    const sceneQ = scene.getWorldQuaternion(new Quaternion())
    const restQ = attach.getWorldQuaternion(new Quaternion()).premultiply(sceneQ.invert())
    const restS = attach.getWorldScale(new Vector3())
    holder.quaternion.copy(restQ.invert())
    holder.scale.set(1 / restS.x, 1 / restS.y, 1 / restS.z)

    let tailMesh: Mesh | undefined
    tailGltf.scene.updateMatrixWorld(true)
    tailGltf.scene.traverse((o) => {
      if (!tailMesh && o instanceof Mesh) tailMesh = o
    })
    if (!tailMesh) throw new Error('尾巴模型里没有网格')
    const { geometry, length } = prepareTailGeometry(tailMesh)
    // 九条尾巴共用一个写意笔触材质，并配细墨线勾边，和身体的工笔线描统一
    const tailMaterial = createInkMaterial({
      map: (tailMesh.material as { map?: Texture | null }).map ?? null,
      saturation: 0.9,
      tailLength: length,
    })
    const tails: Tail[] = Array.from({ length: TAIL_COUNT }, () => {
      const t = createTail(geometry, tailMaterial, length)
      t.pivot.add(createOutline(t.mesh, 0.0035))
      holder.add(t.pivot)
      return t
    })

    return { scene, mixer, clips, attach, holder, tails }
  }, [body, tailGltf])

  const tips = useMemo(() => rig.tails.map((t) => t.tip), [rig])

  useEffect(() => {
    rig.attach.add(rig.holder)
    // 截图脚本据此判断模型已就绪（scripts/shot.mjs）
    if (import.meta.env.DEV) console.info('[beast] ready jiuweihu')
    return () => {
      rig.attach.remove(rig.holder)
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

  useEffect(() => {
    if (action === 'walk') play('walk')
    else if (action === 'special') {
      play('alert')
      specialStart.current = clock.current
      fire.current = 3.2
      const pan = panOf()
      window.setTimeout(() => audio.foxFire(pan), 150)
      window.setTimeout(() => audio.infantCry(pan), 600)
    } else play('idle')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action, rig])

  // 镜头位置换算成左右声像
  const panOf = () => {
    if (!root.current) return 0
    root.current.getWorldPosition(_v).project(camera)
    return MathUtils.clamp(_v.x, -1, 1) * 0.8
  }

  // 待机时偶尔低鸣一声
  useEffect(() => {
    if (action !== 'idle') return
    const id = window.setInterval(() => {
      if (Math.random() < 0.35) audio.infantCry(panOf())
    }, 18000)
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

    // 行走：沿舞台上的圆周走，身体朝切线方向
    if (action === 'walk') {
      walk.current.angle -= (WALK_SPEED / WALK_RADIUS) * dt
      const a = walk.current.angle
      g.position.set(Math.cos(a) * WALK_RADIUS, 0, Math.sin(a) * WALK_RADIUS)
      // 顺时针前进时切线方向为 (sin, -cos)，模型朝 +Z
      const yaw = Math.atan2(Math.sin(a), -Math.cos(a))
      g.rotation.y = MathUtils.damp(g.rotation.y, yaw, 6, dt)

      // 脚步声：四拍慢步，每 1/4 周期一足落地（落地点在各腿摆动结束处）
      const walkAction = rig.clips.walk
      const phase = (walkAction.time % walkAction.getClip().duration) / walkAction.getClip().duration
      const last = walk.current.lastPhase
      const pan = panOf()
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((last < beat && phase >= beat) || (beat === 0 && phase < last)) audio.footstep(pan, beat % 0.5 === 0 ? 0.45 : 0.35)
      }
      walk.current.lastPhase = phase
    }

    // 神通结束后自动回到待机
    if (action === 'special' && t - specialStart.current > SPECIAL_SECONDS) setAction('idle')

    // 靠近时警觉
    if (action === 'idle') {
      g.getWorldPosition(_v)
      const near = camera.position.distanceTo(_v) < ALERT_DISTANCE
      play(near ? 'alert' : 'idle')
    }

    rig.mixer.update(dt)

    const p = pose.current
    const goal = POSES[action]
    for (const k of Object.keys(goal) as (keyof TailPose)[]) p[k] = MathUtils.damp(p[k], goal[k], 2.5, dt)

    // 九尾：扇形排布 + 奇偶分层错开 + 行波摆动，避免九尾压在同一个平面里
    rig.tails.forEach((tail, i) => {
      const u = i / (TAIL_COUNT - 1) - 0.5 // -0.5 … 0.5
      const roll = u * 2 * p.spread
      const tier = (i % 2 === 0 ? 1 : -1) * 0.06
      const elevation = p.elevation + (0.25 - Math.abs(u)) * 0.35 + tier
      aimTail(tail.pivot, elevation, roll)
      const phase = i * 0.83
      tail.bones.forEach((b, j) => {
        const k = j / TAIL_BONES
        b.rotation.z = p.curl * (0.3 + k) + p.amp * Math.sin(t * p.speed - j * 0.7 + phase) * (0.4 + k)
        b.rotation.y = p.amp * 0.8 * Math.cos(t * p.speed * 0.8 - j * 0.6 + phase * 1.3)
      })
    })

    // 狐火：神通爆发后回落到持续焰
    fire.current = MathUtils.damp(fire.current, p.fire, 1.5, dt)

    // 镜头跟随
    if (controls) {
      g.getWorldPosition(_v)
      _v.y = 0.5
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
      <FoxFire emitters={tips} intensity={fire} />
    </>
  )
}

useGLTF.preload(BODY_URL)
useGLTF.preload(TAIL_URL)
