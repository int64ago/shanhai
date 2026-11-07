import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial, type Skeleton } from 'three'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'
import { createScreenPengContacts } from './groundContacts'

/** One body, two lateral heads and a branching shoulder; details are inference. */
export function ScreenPeng() {
  const body = useGLTF('/models/screen_peng/body.glb')
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const time = useRef(0)
  const start = useRef(0)
  const phase = useRef(0)
  const previousAction = useRef(action)
  const outgoingWalkUntil = useRef(0)
  const motion = useMemo(() => new Vector3(), [])
  const cameraShift = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    return { scene, mixer: new AnimationMixer(scene), clips: {} as Record<string, AnimationAction>, mounted: false }
  }, [body])
  const contacts = useMemo(() => createScreenPengContacts(rig.scene), [rig])

  useEffect(() => {
    // StrictMode replays this effect after uncacheRoot. Actions from the first
    // setup are no longer mixer-owned and must never be reused.
    for (const clip of body.animations) rig.clips[clip.name] = rig.mixer.clipAction(clip)
    const meshes: Mesh[] = []
    rig.scene.traverse((node) => { if (node instanceof Mesh) meshes.push(node) })
    const resources = meshes.map((mesh) => {
      const original = mesh.material as MeshStandardMaterial
      const material = createInkMaterial({ map: original.map ?? null, saturation: 0.82 })
      const outline = createOutline(mesh, 0.003)
      mesh.material = material
      mesh.frustumCulled = false
      mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    rig.mounted = true
    if (import.meta.env.DEV) console.info('[beast] ready screen_peng')
    return () => {
      rig.mounted = false
      rig.mixer.stopAllAction()
      rig.mixer.uncacheRoot(rig.scene)
      for (const name of Object.keys(rig.clips)) delete rig.clips[name]
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
        mesh.material = original
        material.dispose()
      }
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
    const clip = rig.clips[action === 'special' ? 'alert' : action]
    if (!clip) throw new Error(`screen_peng: missing ${action} animation`)
    if (previousAction.current === 'walk' && action !== 'walk') outgoingWalkUntil.current = time.current + 0.18
    previousAction.current = action
    // Capture stance before the first blended frame. Keep existing planted
    // anchors when stopping; a swing paw joins them once the blend has landed.
    if (root.current) contacts.update(root.current, action === 'walk' ? 0 : rig.clips.walk.time / 1.8 % 1, action === 'walk' || time.current < outgoingWalkUntil.current ? 0.78 : 1)
    clip.reset().setEffectiveWeight(1).fadeIn(0.18).play()
    start.current = time.current
    const timer = action === 'special' ? window.setTimeout(() => audio.screenPengCall(), 900) : undefined
    return () => { clip.fadeOut(0.18); clearTimeout(timer) }
  }, [action, rig, contacts])

  useFrame((_, rawDt) => {
    if (!rig.mounted) return
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      // No continuous turn while paws support the body: the world path and
      // baked stance velocity have the same constant direction and speed.
      // A standing paw begins near mid-stance. Accelerate over the first gait
      // cycle so it can finish that initial support without overreaching.
      const speed = 0.14 * Math.min(1, (time.current - start.current) / 1.8)
      motion.set(Math.sin(g.rotation.y), 0, Math.cos(g.rotation.y)).multiplyScalar(speed * dt)
      g.position.add(motion)
      camera.position.add(motion)
      cameraShift.add(motion)
      controls?.target.add(motion)
      const p = rig.clips.walk.time / 1.8 % 1
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((phase.current < beat && p >= beat) || (beat === 0 && p < phase.current)) audio.footstep(0, 0.35)
      }
      phase.current = p
    }
    const walkingContact = action === 'walk' || time.current < outgoingWalkUntil.current
    contacts.update(g, walkingContact ? rig.clips.walk.time / 1.8 % 1 : 0, walkingContact ? 0.78 : 1)
    if (import.meta.env.DEV) {
      g.userData.walkPhase = rig.clips.walk.time / 1.8 % 1
      g.userData.walkingContact = walkingContact
    }
    if (action === 'special' && time.current - start.current > 4.4) setAction('idle')
    if (controls) {
      target.copy(g.position); target.y = 0.55
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="screen_peng_root" position={[0, 0, 0.65]} rotation-y={1.1}>
    <primitive object={rig.scene} name="screen_peng_scene" dispose={null} />
  </group>
}
