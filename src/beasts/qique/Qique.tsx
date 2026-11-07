import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, Mesh, Vector3, type AnimationAction, type Group } from 'three'
import { useApp } from '../../app/store'
import { inkify } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'

/** Fowl body, white head, bare rodent-like feet and hooked feline claws. */
export function Qique() {
  const body = useGLTF('/models/qique/body.glb')
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const time = useRef(0)
  const start = useRef(0)
  const walk = useRef({ angle: Math.PI / 2, phase: 0, center: new Vector3() })
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = body.scene
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    inkify(rig.scene, { saturation: 0.8, outline: 0.003 })
    rig.scene.traverse((o) => { if (o instanceof Mesh) o.frustumCulled = false })
    if (import.meta.env.DEV) console.info('[beast] ready qique')
    return () => { rig.mixer.stopAllAction() }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action === 'special' ? 'alert' : action]
    if (!clip) throw new Error(`qique: missing ${action} animation`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.18).play()
    start.current = time.current
    if (action === 'walk' && root.current) {
      const path = walk.current
      path.angle = Math.PI - root.current.rotation.y
      path.phase = 0
      path.center.copy(root.current.position)
      path.center.x -= 0.8 * Math.cos(path.angle)
      path.center.z -= 0.8 * Math.sin(path.angle)
    }
    let timer: number | undefined
    if (action === 'special') timer = window.setTimeout(() => audio.qiqueCall(), 650)
    return () => { clip.fadeOut(0.18); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      walk.current.angle -= 0.16 / 0.8 * dt
      const a = walk.current.angle
      g.position.copy(walk.current.center)
      g.position.x += Math.cos(a) * 0.8
      g.position.z += Math.sin(a) * 0.8
      // Matches the curved foot targets and inverse sole yaw baked by rig_qique.py.
      g.rotation.y = Math.PI - a
      const phase = rig.clips.walk.time / 1.2 % 1
      for (const beat of [0, 0.5]) {
        if ((walk.current.phase < beat && phase >= beat) || (beat === 0 && phase < walk.current.phase)) audio.footstep(0, 0.24)
      }
      walk.current.phase = phase
    }
    if (action === 'special' && time.current - start.current > 4.2) setAction('idle')
    if (controls) {
      target.copy(g.position); target.y = 0.52
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, 0.8]} rotation-y={1.15}>
    <primitive object={rig.scene} name="qique_scene" />
  </group>
}
