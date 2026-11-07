import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, MathUtils, Mesh, ShaderMaterial, Vector3, type AnimationAction, type Group } from 'three'
import { useApp } from '../../app/store'
import { inkify } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'

const URL = '/models/jingwei/body.glb'
const DURATION = 4.8
const RADIUS = 0.8
const SPEED = 0.16

export function Jingwei() {
  const body = useGLTF(URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const stone = useRef<Mesh>(null)
  const time = useRef(0)
  const start = useRef(0)
  const walk = useRef({ angle: Math.PI / 2, phase: 0 })
  const released = useRef(false)
  const releasePoint = useMemo(() => new Vector3(), [])
  const point = useMemo(() => new Vector3(), [])
  const stoneMaterial = useMemo(() => createInkMaterial({ map: null, tint: '#766e5a', saturation: 0.3 }), [])
  const rig = useMemo(() => {
    const scene = body.scene
    inkify(scene, { saturation: 0.88, outline: 0.003 })
    scene.traverse((o) => {
      if (!(o instanceof Mesh)) return
      o.frustumCulled = false
      // Dilute the crow's broad ink areas enough to retain feather modelling.
      if (!o.userData.inkOutline && o.material instanceof ShaderMaterial) o.material.uniforms.uInkBoost.value = -0.15
    })
    scene.updateMatrixWorld(true)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    const beak = scene.getObjectByName('beak_attach')
    if (!beak) throw new Error('精卫缺少 beak_attach')
    return { scene, mixer, clips, beak }
  }, [body])

  useEffect(() => {
    if (import.meta.env.DEV) console.info('[beast] ready jingwei')
    return () => { rig.mixer.stopAllAction() }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action === 'special' ? 'alert' : action]
    if (!clip) throw new Error(`精卫缺少 ${action} 动画`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.25).play()
    let timer: number | undefined
    if (action === 'special') {
      start.current = time.current
      released.current = false
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => audio.jingweiCall(pan), 100)
    }
    return () => { clip.fadeOut(0.25); clearTimeout(timer) }
  }, [action, rig, camera, point])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    const g = root.current
    if (!g) return
    rig.mixer.update(dt)
    if (action === 'walk') {
      walk.current.angle -= SPEED / RADIUS * dt
      const angle = walk.current.angle
      g.position.set(Math.cos(angle) * RADIUS, 0, Math.sin(angle) * RADIUS)
      const yaw = Math.atan2(Math.sin(angle), -Math.cos(angle))
      g.rotation.y = yaw
      const clip = rig.clips.walk
      const phase = (clip.time % clip.getClip().duration) / clip.getClip().duration
      if (walk.current.phase < 0.75 && phase >= 0.75) audio.footstep(0, 0.22)
      walk.current.phase = phase
    }
    const elapsed = time.current - start.current
    if (action === 'special' && elapsed > DURATION) setAction('idle')
    // World-space beak position follows the evaluated skeleton. The pebble is a
    // separate scene object, so switching beasts never mutates the cached GLTF.
    g.updateMatrixWorld(true)
    if (stone.current) {
      stone.current.visible = action === 'special' && elapsed < 3.6
      if (!released.current) {
        rig.beak.getWorldPosition(releasePoint)
        if (elapsed >= 1.8 && action === 'special') released.current = true
      }
      stone.current.position.copy(releasePoint)
      if (released.current) {
        const fall = Math.max(0, elapsed - 1.8)
        stone.current.position.y = Math.max(0.025, releasePoint.y - fall * fall * 1.8)
        stone.current.position.z += Math.min(fall, 0.5) * 0.12
        stone.current.rotation.x = fall * 3
      }
    }
    if (controls) {
      g.getWorldPosition(point)
      point.y = 0.48
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <>
    <group ref={root} position={[0, 0, RADIUS]} rotation-y={Math.PI / 2 - 0.22}>
      <primitive object={rig.scene} />
    </group>
    <mesh ref={stone} visible={false} material={stoneMaterial} scale={[0.033, 0.023, 0.027]}>
      <dodecahedronGeometry args={[1, 0]} />
    </mesh>
  </>
}

useGLTF.preload(URL)
