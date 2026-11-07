import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Group, LoopOnce, LoopRepeat, MathUtils, Mesh, Vector3, type AnimationAction } from 'three'
import { useApp } from '../../app/store'
import { inkify } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'

const URL = '/models/qingniao/body.glb'
const SCALE = 0.82
const SPEED = 0.12 * SCALE
const PLACEMENT = [[-0.65, 0.45, 1.65], [-0.35, -0.45, 1.3], [0.5, -0.35, 1.05]] as const

export function Qingniao() {
  const body = useGLTF(URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const flock = useRef<Group>(null)
  const elapsed = useRef(0)
  const specialTime = useRef(0)
  const route = useRef({ elapsed: 0, phase: 0, origin: new Vector3() })
  const point = useMemo(() => new Vector3(), [])
  const birds = useMemo(() => PLACEMENT.map(([x, z, yaw], i) => {
    // SkeletonUtils gives each of the three bodies its own skeleton and mixer.
    // The cached source scene remains untouched, including under StrictMode.
    const scene = clone(body.scene)
    scene.name = `qingniao_individual_${i}`
    inkify(scene, { saturation: 0.88, outline: 0.0025 })
    scene.traverse((o) => { if (o instanceof Mesh) o.frustumCulled = false })
    const holder = new Group()
    holder.name = `qingniao_holder_${i}`
    holder.position.set(x, 0, z)
    holder.rotation.y = yaw
    holder.scale.setScalar(SCALE)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    return { scene, holder, mixer, clips }
  }), [body])

  useEffect(() => {
    for (const bird of birds) bird.holder.add(bird.scene)
    if (import.meta.env.DEV) console.info('[beast] ready qingniao')
    return () => {
      for (const bird of birds) {
        bird.holder.remove(bird.scene)
        bird.mixer.stopAllAction()
        bird.scene.traverse((o) => {
          if (o instanceof Mesh) {
            for (const material of Array.isArray(o.material) ? o.material : [o.material]) material.dispose()
          }
        })
      }
    }
  }, [birds])

  useEffect(() => {
    for (const [i, bird] of birds.entries()) {
      const clip = bird.clips[action === 'special' ? 'alert' : action]
      if (!clip) throw new Error(`青鸟缺少 ${action} 动画`)
      clip.reset().setEffectiveWeight(1).setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
      clip.clampWhenFinished = action === 'special'
      clip.time = action === 'idle' ? i * 1.1 : action === 'special' ? i * 0.12 : 0
      clip.fadeIn(0.2).play()
    }
    if (action === 'walk' && flock.current) {
      route.current.elapsed = 0
      route.current.phase = 0
      route.current.origin.copy(flock.current.position)
    }
    let timer: number | undefined
    if (action === 'special') {
      specialTime.current = elapsed.current
      timer = window.setTimeout(() => audio.qingniaoCall(), 180)
    }
    return () => {
      for (const bird of birds) bird.clips[action === 'special' ? 'alert' : action].fadeOut(0.2)
      clearTimeout(timer)
    }
  }, [action, birds])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    elapsed.current += dt
    for (const bird of birds) bird.mixer.update(dt)
    const g = flock.current
    if (!g) return
    if (action === 'walk') {
      const path = route.current
      const duration = birds[0].clips.walk.getClip().duration
      path.elapsed += dt
      const steps = Math.floor(path.elapsed / duration)
      const phase = (path.elapsed % duration) / duration
      const turn = Math.PI * 2 / 24
      const heading = 1.4 + steps * turn
      const sum = Math.sin(steps * turn / 2) / Math.sin(turn / 2)
      const middle = 1.4 + (steps - 1) * turn / 2
      // Every bird turns about its own feet only during the airborne half-cycle.
      // Shared translation preserves the formation without rotating its offsets.
      g.position.copy(path.origin)
      g.position.x += SPEED * duration * (sum * Math.sin(middle) + phase * Math.sin(heading))
      g.position.z += SPEED * duration * (sum * Math.cos(middle) + phase * Math.cos(heading))
      for (const bird of birds) bird.holder.rotation.y = heading + turn * MathUtils.smoothstep(phase, 0.5, 1)
      if (phase < path.phase) audio.footstep(0, 0.22)
      path.phase = phase
    }
    if (action === 'special' && elapsed.current - specialTime.current > 4.8) setAction('idle')
    if (controls) {
      g.getWorldPosition(point)
      point.y = 0.42
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={flock}>
    {birds.map((bird, i) => <primitive key={i} object={bird.holder} />)}
  </group>
}

useGLTF.preload(URL)
