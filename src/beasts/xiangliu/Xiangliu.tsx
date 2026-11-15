import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, LoopOnce, LoopRepeat, Mesh, SkinnedMesh, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/xiangliu/body.glb'

export function Xiangliu() {
  const asset = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const root = useRef<Group>(null)
  const rig = useMemo(() => {
    // Every mount owns a skeleton. Cached GLTF scene graphs are never modified.
    const scene = clone(asset.scene)
    scene.position.z -= 1.6
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of asset.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || duration <= 0) throw new Error(`相柳缺少有效的 ${name} 动画`)
    }
    return { scene, mixer, clips }
  }, [asset])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const materials: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      originals.set(node, node.material)
      const convert = (source: Material) => {
        const standard = source as MeshStandardMaterial
        const material = createInkMaterial({ map: standard.map ?? null, tint: standard.map ? '#ffffff' : `#${standard.color.getHexString()}`, saturation: 0.68 })
        materials.push(material)
        return material
      }
      node.material = Array.isArray(node.material) ? node.material.map(convert) : convert(node.material)
    })
    // Attach ink shells only in effects, including the nine skinned human faces.
    for (const node of originals.keys()) {
      const outline = createOutline(node, 0.0015)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready xiangliu')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of materials) material.dispose()
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
    rig.mixer.update(Math.min(rawDt, 0.05))
    if (import.meta.env.DEV && root.current) root.current.userData.animationTime = rig.clips[action].time
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - 0.001) setAction('idle')
  })

  return <group ref={root} name="xiangliu_root" scale={0.45} rotation-y={-Math.PI / 2}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}
