import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/yinglong/body.glb'

export function Yinglong() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const width = useThree(s => s.size.width)
  const root = useRef<Group>(null)
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || duration <= 0) throw new Error(`应龙缺少有效的 ${name} 动画`)
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
        const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.65 })
        material.side = DoubleSide
        owned.push(material)
        return material
      }
      node.material = Array.isArray(node.material) ? node.material.map(source => ink(source as MeshStandardMaterial)) : ink(node.material as MeshStandardMaterial)
      node.frustumCulled = false
    })
    for (const mesh of originals.keys()) {
      const outline = createOutline(mesh, 0.0014)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready yinglong')
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
    clip.reset().setEffectiveWeight(1).fadeIn(0.3)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    return () => { clip.fadeOut(0.3) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    rig.mixer.update(dt)
    const group = root.current
    if (!group) return
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - 0.001) setAction('idle')
    if (controls) {
      group.getWorldPosition(target)
      target.y = width <= 640 ? 1.2 : 1.0
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="yinglong_root">
    <primitive object={rig.scene} dispose={null} />
  </group>
}
