import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'

/** Chicken-shaped five-colour bird; the five virtue patterns belong to its feathers. */
export function Fenghuang() {
  const body = useGLTF('/models/fenghuang/body.glb')
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const camera = useThree((s) => s.camera)
  const root = useRef<Group>(null)
  const time = useRef(0)
  const start = useRef(0)
  const walk = useRef({ phase: 0 })
  const motion = useMemo(() => new Vector3(), [])
  const cameraShift = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    // StrictMode replays this setup after cleanup. Build fresh actions after
    // uncacheRoot releases their bindings; old actions retain stale bindings.
    for (const clip of body.animations) rig.clips[clip.name] = rig.mixer.clipAction(clip)
    const meshes: Mesh[] = []
    rig.scene.traverse((node) => { if (node instanceof Mesh) meshes.push(node) })
    const resources = meshes.map((mesh) => {
      const original = mesh.material as MeshStandardMaterial
      const material = createInkMaterial({ map: original.map ?? null, saturation: 0.91 })
      const outline = createOutline(mesh, 0.0012)
      mesh.material = material
      mesh.frustumCulled = false
      mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    if (import.meta.env.DEV) console.info('[beast] ready fenghuang')
    return () => {
      rig.mixer.stopAllAction()
      rig.mixer.uncacheRoot(rig.scene)
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
        mesh.material = original
        material.dispose()
      }
      // Clone-owned skeletons may be shared with outlines. Dispose each once;
      // cached geometry, source materials and image textures remain shared.
      const skeletons = new Set<SkinnedMesh['skeleton']>()
      for (const mesh of meshes) if (mesh instanceof SkinnedMesh) skeletons.add(mesh.skeleton)
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig, body.animations])

  useEffect(() => () => {
    camera.position.sub(cameraShift)
    controls?.target.sub(cameraShift)
    cameraShift.set(0, 0, 0)
  }, [camera, controls, cameraShift])

  useEffect(() => {
    const clip = rig.clips[action === 'special' ? 'alert' : action]
    if (!clip) throw new Error(`fenghuang: missing ${action} animation`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.2).play()
    start.current = time.current
    const timers = action === 'special'
      ? [650, 2450].map((delay) => window.setTimeout(() => audio.fenghuangCall(), delay))
      : []
    return () => { clip.fadeOut(0.2); timers.forEach(clearTimeout) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      // Straight translation matches the baked stance velocity. Continuous yaw
      // on a circular path would drag planted toes sideways.
      motion.set(Math.sin(g.rotation.y), 0, Math.cos(g.rotation.y)).multiplyScalar(0.12 * dt)
      g.position.add(motion)
      camera.position.add(motion)
      cameraShift.add(motion)
      controls?.target.add(motion)
      const phase = rig.clips.walk.time / 1.6 % 1
      for (const beat of [0, 0.5]) {
        if ((walk.current.phase < beat && phase >= beat) || (beat === 0 && phase < walk.current.phase)) audio.footstep(0, 0.18)
      }
      walk.current.phase = phase
    }
    if (action === 'special' && time.current - start.current > 5.2) setAction('idle')
    if (controls) {
      target.copy(g.position); target.y = 0.55
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, 0.85]} rotation-y={0.7}>
    <primitive object={rig.scene} name="fenghuang_scene" dispose={null} />
  </group>
}
