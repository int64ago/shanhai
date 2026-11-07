import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, MathUtils, Mesh, ShaderMaterial, Vector3, type AnimationAction, type Group } from 'three'
import { useApp } from '../../app/store'
import { inkify } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'

const URL = '/models/min_bird/body.glb'
const RADIUS = 0.65
const SPEED = 0.10

export function MinBird() {
  const body = useGLTF(URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const time = useRef(0)
  const specialStart = useRef(0)
  const walk = useRef({ elapsed: 0, phase: 0, yaw: 1.65, origin: new Vector3(0, 0, RADIUS) })
  const point = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = body.scene
    inkify(scene, { saturation: 0.9, outline: 0.0024 })
    scene.traverse((o) => {
      if (!(o instanceof Mesh)) return
      o.frustumCulled = false
      if (!o.userData.inkOutline && o.material instanceof ShaderMaterial) {
        o.material.uniforms.uInkBoost.value = -0.1
      }
    })
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    if (import.meta.env.DEV) console.info('[beast] ready min_bird')
    return () => { rig.mixer.stopAllAction() }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action === 'special' ? 'alert' : action]
    if (!clip) throw new Error(`鴖缺少 ${action} 动画`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.2).play()
    let timer: number | undefined
    if (action === 'walk' && root.current) {
      walk.current.elapsed = 0
      walk.current.phase = 0
      walk.current.yaw = root.current.rotation.y
      walk.current.origin.copy(root.current.position)
    }
    if (action === 'special') {
      specialStart.current = time.current
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => audio.minBirdCall(pan), 180)
    }
    return () => { clip.fadeOut(0.2); clearTimeout(timer) }
  }, [action, rig, camera, point])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      const route = walk.current
      const duration = rig.clips.walk.getClip().duration
      route.elapsed += dt
      const steps = Math.floor(route.elapsed / duration)
      const phase = (route.elapsed % duration) / duration
      const turn = Math.PI * 2 / 40
      const heading = route.yaw + steps * turn
      // A closed 40-sided path: translate along a straight chord in stance,
      // and turn only while both feet are airborne. The baked 0.10 m/s foot
      // retreat therefore cancels world motion for both planted feet.
      const sum = Math.sin(steps * turn / 2) / Math.sin(turn / 2)
      const middle = route.yaw + (steps - 1) * turn / 2
      g.position.copy(route.origin)
      g.position.x += SPEED * duration * (sum * Math.sin(middle) + phase * Math.sin(heading))
      g.position.z += SPEED * duration * (sum * Math.cos(middle) + phase * Math.cos(heading))
      g.rotation.y = heading + turn * MathUtils.smoothstep(phase, 0.5, 1)
      if (phase < route.phase) audio.footstep(0, 0.12)
      route.phase = phase
    }
    if (action === 'special' && time.current - specialStart.current > 4.2) setAction('idle')
    if (controls) {
      g.getWorldPosition(point)
      point.y = 0.41
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, RADIUS]} rotation-y={1.65}>
    <primitive object={rig.scene} />
  </group>
}

useGLTF.preload(URL)
