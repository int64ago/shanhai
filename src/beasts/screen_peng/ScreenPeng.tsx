import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, Mesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'

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
  const motion = useMemo(() => new Vector3(), [])
  const cameraShift = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const mixer = new AnimationMixer(body.scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    return { scene: body.scene, mixer, clips }
  }, [body])

  useEffect(() => {
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
    if (import.meta.env.DEV) console.info('[beast] ready screen_peng')
    return () => {
      rig.mixer.stopAllAction()
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
        mesh.material = original
        material.dispose()
      }
    }
  }, [rig])

  useEffect(() => () => {
    camera.position.sub(cameraShift)
    controls?.target.sub(cameraShift)
    cameraShift.set(0, 0, 0)
  }, [camera, controls, cameraShift])

  useEffect(() => {
    const clip = rig.clips[action === 'special' ? 'alert' : action]
    if (!clip) throw new Error(`screen_peng: missing ${action} animation`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.18).play()
    start.current = time.current
    const timer = action === 'special' ? window.setTimeout(() => audio.screenPengCall(), 900) : undefined
    return () => { clip.fadeOut(0.18); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      // No continuous turn while paws support the body: the world path and
      // baked stance velocity have the same constant direction and speed.
      motion.set(Math.sin(g.rotation.y), 0, Math.cos(g.rotation.y)).multiplyScalar(0.14 * dt)
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
    if (action === 'special' && time.current - start.current > 4.4) setAction('idle')
    if (controls) {
      target.copy(g.position); target.y = 0.55
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, 0.65]} rotation-y={1.1}>
    <primitive object={rig.scene} name="screen_peng_scene" />
  </group>
}
