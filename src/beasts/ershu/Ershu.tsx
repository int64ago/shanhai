import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, MathUtils, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial, type Skeleton } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createErshuContacts } from './groundContacts'

const URL = '/models/ershu/body.glb'
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
  const phase = useRef(0)
  const time = useRef(0)
  const start = useRef(0)
  const previous = useRef(action)
  const outgoingWalkUntil = useRef(0)
  const restartHeight = useRef(0)
  const point = useMemo(() => new Vector3(), [])
  const motion = useMemo(() => new Vector3(), [])
  const cameraShift = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    // Keep enough joint flexion to reach the last planted walk target while
    // the baked root crouch blends back to idle.
    scene.position.y -= 0.03
    return { scene, mixer: new AnimationMixer(scene), clips: {} as Record<string, AnimationAction>, mounted: false }
  }, [body])
  const contacts = useMemo(() => createErshuContacts(rig.scene), [rig])

  useEffect(() => {
    // StrictMode replays setup after uncacheRoot: recreate mixer-owned actions.
    for (const clip of body.animations) rig.clips[clip.name] = rig.mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!rig.clips[name]) throw new Error(`耳鼠缺少 ${name} 动画`)
    }
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse((node) => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      originals.set(node, node.material)
      const material = createInkMaterial({ map: source.map ?? null, saturation: 0.82, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}` })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const fine = node.name.includes('whisker') || node.name.includes('lip')
      const outline = createOutline(node, fine ? 0.00035 : node.name.includes('eye') ? 0.0008 : 0.0023)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    rig.mounted = true
    if (import.meta.env.DEV) console.info('[beast] ready ershu')
    return () => {
      rig.mounted = false
      rig.mixer.stopAllAction()
      rig.mixer.uncacheRoot(rig.scene)
      for (const name of Object.keys(rig.clips)) delete rig.clips[name]
      for (const outline of outlines) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      const skeletons = new Set<Skeleton>()
      rig.scene.traverse((node) => { if (node instanceof SkinnedMesh) skeletons.add(node.skeleton) })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [body, rig])

  useEffect(() => () => {
    camera.position.sub(cameraShift)
    controls?.target.sub(cameraShift)
    cameraShift.set(0, 0, 0)
  }, [camera, controls, cameraShift])

  useEffect(() => {
    if (previous.current === 'walk' && action !== 'walk') outgoingWalkUntil.current = time.current + 0.32
    previous.current = action
    const clip = rig.clips[action]
    clip.reset().setEffectiveWeight(1).fadeIn(0.32)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    start.current = time.current
    let timer: number | undefined
    if (action === 'special') {
      restartHeight.current = flight.current?.position.y ?? 0
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => audio.ershuCall(pan), 120)
    }
    return () => { clip.fadeOut(0.32); clearTimeout(timer) }
  }, [action, rig, camera, point, contacts])

  useFrame((_, rawDt) => {
    if (!rig.mounted) return
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    const g = root.current, lift = flight.current
    if (!g || !lift) return
    contacts.restore()
    rig.mixer.update(dt)
    if (action === 'walk') {
      const speed = SPEED * Math.min(1, (time.current - start.current) / 1.5)
      motion.set(Math.sin(g.rotation.y), 0, Math.cos(g.rotation.y)).multiplyScalar(speed * dt)
      g.position.add(motion)
      camera.position.add(motion)
      cameraShift.add(motion)
      controls?.target.add(motion)
      const current = rig.clips.walk.time / 1.5 % 1
      if (lift.position.y < 0.015) {
        for (const beat of [0, 0.25, 0.5, 0.75]) {
          if ((phase.current < beat && current >= beat) || (beat === 0 && current < phase.current)) audio.footstep(0, 0.24)
        }
      }
      phase.current = current
    }
    if (action === 'special') {
      const seconds = rig.clips.special.time
      const inherited = restartHeight.current * (1 - MathUtils.smoothstep(seconds, 0, 0.4))
      lift.position.y = inherited + liftAt(seconds)
      if (seconds >= FLIGHT_SECONDS - 0.001) setAction('idle')
    } else {
      lift.position.y = MathUtils.damp(lift.position.y, 0, 5, dt)
      if (dt > 0 && lift.position.y < 0.0001) lift.position.y = 0
    }
    const walkingContact = action === 'walk' || time.current < outgoingWalkUntil.current
    contacts.update(g, walkingContact ? rig.clips.walk.time / 1.5 % 1 : 0, walkingContact ? 0.68 : 1, lift.position.y === 0)
    if (import.meta.env.DEV) {
      g.userData.walkPhase = rig.clips.walk.time / 1.5 % 1
      g.userData.walkingContact = walkingContact
      g.userData.contactActive = lift.position.y === 0
    }
    if (controls) {
      g.getWorldPosition(point)
      point.y = 0.55 + lift.position.y * 0.4
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="ershu_root" position={[0, 0, 1]} rotation-y={Math.PI / 2}>
    <group ref={flight} name="ershu_flight">
      <primitive object={rig.scene} name="ershu_scene" dispose={null} />
    </group>
  </group>
}

useGLTF.preload(URL)
