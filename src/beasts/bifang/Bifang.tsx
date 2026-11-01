import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import {
  AnimationMixer,
  LoopRepeat,
  MathUtils,
  Mesh,
  Vector3,
  type AnimationAction,
  type Group,
} from 'three'
import { useApp, type BeastAction } from '../../app/store'
import { inkify } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'
import { FoxFire } from '../../systems/vfx/FoxFire'

const BODY_URL = '/models/bifang/body.glb'
const FADE = 0.28
const SPECIAL_SECONDS = 4.8
const WALK_RADIUS = 1.05
const WALK_SPEED = 0.32
const ALERT_DISTANCE = 2.4

const FIRE_GOALS: Record<BeastAction, number> = {
  idle: 0.42,
  walk: 0.65,
  special: 2.8,
}

const _v = new Vector3()

export function Bifang() {
  const body = useGLTF(BODY_URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null

  const root = useRef<Group>(null)
  const fire = useRef(FIRE_GOALS.idle)
  const walk = useRef({ angle: Math.PI / 2, lastPhase: 0 })
  const specialStart = useRef(0)
  const clock = useRef(0)

  const rig = useMemo(() => {
    const scene = body.scene
    scene.traverse((o) => {
      if (o instanceof Mesh) o.frustumCulled = false
    })
    // 毕方：「赤文青质而白喙」，保留石青与朱砂丹纹的明快工笔设色
    inkify(scene, { saturation: 0.9, outline: 0.0055 })
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
      if (!b) throw new Error(`毕方骨骼缺失: ${name}`)
      return b
    }

    // 讹火发射点：双翼尖、长喙与尾翎
    const emitters = [
      bone('wing_l_attach'),
      bone('wing_r_attach'),
      bone('beak_attach'),
      bone('tail_attach'),
    ]

    return { scene, mixer, clips, emitters }
  }, [body])

  useEffect(() => {
    if (import.meta.env.DEV) console.info('[beast] ready bifang')
    return () => {
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
      fire.current = 3.5
      const pan = panOf()
      window.setTimeout(() => audio.bifangCall(pan), 80)
    } else play('idle')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action, rig])

  useEffect(() => {
    if (action !== 'idle') return
    const id = window.setInterval(() => {
      if (Math.random() < 0.32) audio.bifangCall(panOf())
    }, 19000)
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
      g.position.x = Math.cos(a) * WALK_RADIUS
      g.position.z = Math.sin(a) * WALK_RADIUS
      const yaw = Math.atan2(Math.sin(a), -Math.cos(a))
      g.rotation.y = MathUtils.damp(g.rotation.y, yaw, 6, dt)

      // 独足鹤跃落地声 + 振翅声
      const walkAction = rig.clips.walk
      const phase = (walkAction.time % walkAction.getClip().duration) / walkAction.getClip().duration
      const last = walk.current.lastPhase
      const pan = panOf()
      if (last < 0.5 && phase >= 0.5) {
        audio.footstep(pan, 0.45)
      }
      if (phase < last) {
        audio.wingFlutter(pan, 0.38)
      }
      walk.current.lastPhase = phase
    }

    if (action === 'special') {
      const elapsed = t - specialStart.current
      if (elapsed > SPECIAL_SECONDS) setAction('idle')
      // 神通「讹火自訆」：单足轻跃腾空，双翼振起丹火
      const soar = Math.sin(Math.min(elapsed / SPECIAL_SECONDS, 1) * Math.PI) * 0.22
      g.position.y = MathUtils.damp(g.position.y, soar, 5, dt)
    } else {
      g.position.y = MathUtils.damp(g.position.y, 0, 6, dt)
    }

    if (action === 'idle') {
      g.getWorldPosition(_v)
      const near = camera.position.distanceTo(_v) < ALERT_DISTANCE
      play(near ? 'alert' : 'idle')
    }

    rig.mixer.update(dt)
    fire.current = MathUtils.damp(fire.current, FIRE_GOALS[action], 1.6, dt)

    if (controls) {
      g.getWorldPosition(_v)
      _v.y = 0.54
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
      <FoxFire emitters={rig.emitters} intensity={fire} />
    </>
  )
}

useGLTF.preload(BODY_URL)
