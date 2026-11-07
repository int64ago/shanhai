import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, Mesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'

/** The classical 烏 is visualized with two feet; the count is inference. */
export function Jinwu() {
  const body = useGLTF('/models/jinwu/body.glb')
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
    rig.scene.traverse(node => { if (node instanceof Mesh) meshes.push(node) })
    const resources = meshes.map(mesh => {
      const original = mesh.material as MeshStandardMaterial
      const material = createInkMaterial({ map: original.map ?? null, saturation: 0.75 })
      const outline = createOutline(mesh, 0.003)
      mesh.material = material
      mesh.frustumCulled = false
      mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    if (import.meta.env.DEV) console.info('[beast] ready jinwu')
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
    if (!clip) throw new Error(`jinwu: missing ${action} animation`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.18).play()
    start.current = time.current
    const timer = action === 'special' ? window.setTimeout(() => audio.jinwuCall(), 1000) : undefined
    return () => { clip.fadeOut(0.18); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      // Straight travel matches the baked support velocity and heading.
      motion.set(Math.sin(g.rotation.y), 0, Math.cos(g.rotation.y)).multiplyScalar(0.12 * dt)
      g.position.add(motion)
      camera.position.add(motion)
      cameraShift.add(motion)
      controls?.target.add(motion)
      const p = rig.clips.walk.time / 1.6 % 1
      if ((phase.current < 0.5 && p >= 0.5) || p < phase.current) audio.footstep(0, 0.25)
      phase.current = p
    }
    if (action === 'special' && time.current - start.current > 4.6) setAction('idle')
    if (controls) {
      target.copy(g.position); target.y = 0.52
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, 0.6]} rotation-y={1.65}>
    <primitive object={rig.scene} name="jinwu_scene" />
  </group>
}
