import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, MathUtils, Mesh, MeshStandardMaterial, Vector3, type AnimationAction, type Group, type Material } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'

const URL = '/models/ershu/body.glb'
const RADIUS = 1.0
// Matches rig_ershu.py's linear stance travel and 1.5-second walk cycle.
const SPEED = 0.19 / (0.68 * 1.5)
const FLIGHT_SECONDS = 5.4

function liftAt(seconds: number) {
  return 0.38 * MathUtils.smoothstep(seconds, 0.4, 1.35) * (1 - MathUtils.smoothstep(seconds, 3.5, 4.9))
}

export function Ershu() {
  const body = useGLTF(URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const flight = useRef<Group>(null)
  const angle = useRef(Math.PI / 2)
  const phase = useRef(0)
  const restartHeight = useRef(0)
  const point = useMemo(() => new Vector3(), [])

  const rig = useMemo(() => {
    // All posing/material work belongs to an owned clone; useGLTF's cache stays pristine.
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!clips[name]) throw new Error(`耳鼠缺少 ${name} 动画`)
    }
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse((node) => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      originals.set(node, node.material)
      const material = createInkMaterial({
        map: source.map ?? null,
        saturation: 0.82,
        tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`,
      })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    // Add siblings only after traversal; StrictMode cleanup removes every outline.
    for (const node of originals.keys()) {
      const fine = node.name.includes('whisker') || node.name.includes('lip')
      const outline = createOutline(node, fine ? 0.00035 : node.name.includes('eye') ? 0.0008 : 0.0023)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready ershu')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) {
        outline.removeFromParent()
        const material = outline.material as Material
        material.dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
    }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action]
    clip.reset().setEffectiveWeight(1).fadeIn(0.32)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    let timer: number | undefined
    if (action === 'special') {
      restartHeight.current = flight.current?.position.y ?? 0
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => audio.ershuCall(pan), 120)
    }
    return () => { clip.fadeOut(0.32); clearTimeout(timer) }
  }, [action, rig, camera, point])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const g = root.current
    const lift = flight.current
    if (!g || !lift) return
    rig.mixer.update(dt)
    if (action === 'walk') {
      // Continue the circle from the current position after idle or interrupted flight.
      angle.current -= SPEED / RADIUS * dt
      g.position.set(Math.cos(angle.current) * RADIUS, 0, Math.sin(angle.current) * RADIUS)
      const heading = Math.atan2(Math.sin(angle.current), -Math.cos(angle.current))
      const delta = Math.atan2(Math.sin(heading - g.rotation.y), Math.cos(heading - g.rotation.y))
      g.rotation.y += delta * (1 - Math.exp(-8 * dt))
      const current = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      if (lift.position.y < 0.015) {
        for (const beat of [0, 0.25, 0.5, 0.75]) {
          if ((phase.current < beat && current >= beat) || (beat === 0 && current < phase.current)) audio.footstep(0, 0.24)
        }
      }
      phase.current = current
    }
    if (action === 'special') {
      const seconds = rig.clips.special.time
      // The tail strokes, folding hooves and altitude share the exported clip clock.
      const inherited = restartHeight.current * (1 - MathUtils.smoothstep(seconds, 0, 0.4))
      lift.position.y = inherited + liftAt(seconds)
      if (seconds >= FLIGHT_SECONDS - 0.001) setAction('idle')
    } else {
      // Crossfade unfolds the legs before this damped descent reaches the ground.
      lift.position.y = MathUtils.damp(lift.position.y, 0, 5, dt)
      if (lift.position.y < 0.0001) lift.position.y = 0
    }
    if (controls) {
      g.getWorldPosition(point)
      point.y = 0.55 + lift.position.y * 0.4
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="ershu_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <group ref={flight} name="ershu_flight">
      <primitive object={rig.scene} />
    </group>
  </group>
}

useGLTF.preload(URL)
