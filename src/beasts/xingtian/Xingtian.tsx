import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, LoopOnce, LoopRepeat, Mesh, PerspectiveCamera, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/xingtian/body.glb'

export function Xingtian() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const camera = useThree(s => s.camera)
  const size = useThree(s => s.size)
  const narrow = size.width <= 640
  const portraitTablet = !narrow && size.width / size.height <= 1.3
  const root = useRef<Group>(null)
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || duration <= 0) throw new Error(`刑天缺少有效的 ${name} 动画`)
    }
    for (const name of ['axe_grip_origin', 'shield_grip_origin', 'xingtian_wrist_l', 'xingtian_wrist_r']) {
      if (!scene.getObjectByName(name)) throw new Error(`刑天缺少独立握具挂点 ${name}`)
    }
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      originals.set(node, node.material)
      const ink = (source: MeshStandardMaterial) => {
        const material = createInkMaterial({
          map: source.map ?? null,
          tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`,
          saturation: node instanceof SkinnedMesh ? 0.65 : 0.82,
        })
        owned.push(material)
        return material
      }
      node.material = Array.isArray(node.material) ? node.material.map(source => ink(source as MeshStandardMaterial)) : ink(node.material as MeshStandardMaterial)
      node.frustumCulled = false
    })
    for (const mesh of originals.keys()) {
      // Source body is normalized by its node, while the fitted tools use meters.
      const outline = createOutline(mesh, mesh instanceof SkinnedMesh ? 0.002 : 0.00065)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready xingtian')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      const skeletons = new Set<SkinnedMesh['skeleton']>()
      rig.scene.traverse(node => { if (node instanceof SkinnedMesh) skeletons.add(node.skeleton) })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action]
    clip.reset().setEffectiveWeight(1).fadeIn(0.35)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    return () => { clip.fadeOut(0.35) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    rig.mixer.update(dt)
    const group = root.current
    if (!group) return
    // The walk clip contains its world path and planted-foot targets. Adding
    // external travel or yaw here would break stance support and tool clearance.
    if (import.meta.env.DEV) {
      group.userData.animationTime = rig.clips[action].time
      group.userData.animationMixer = rig.mixer
    }
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - 0.001) setAction('idle')
    // This beast's complete tool envelope must clear the source card and selector.
    // CameraRig restores the next beast's framing when selection changes.
    if (camera instanceof PerspectiveCamera) {
      const fov = narrow ? 80 : portraitTablet ? 86 : 42
      const offset = narrow ? 0 : portraitTablet ? -6.5 : -6
      if (camera.fov !== fov || camera.filmOffset !== offset) {
        camera.fov = fov
        camera.filmOffset = offset
        camera.updateProjectionMatrix()
      }
    }
    if (controls) {
      target.set(0, narrow ? 1.1 : 0.7, 0)
      controls.target.lerp(target, 1 - Math.exp(-2.5 * dt))
    }
  })

  return <group ref={root} name="xingtian_root" scale={1.7}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}
