import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/bashe/body.glb'

export function Bashe() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const point = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || duration <= 0) throw new Error(`巴蛇缺少有效的 ${name} 动画`)
    }
    return { scene, mixer, clips, specialDuration: clips.special.getClip().duration }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      originals.set(node, node.material)
      const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.65 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const outline = createOutline(node, 0.0014)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready bashe')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) { outline.removeFromParent(); (outline.material as Material).dispose() }
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
    const group = root.current
    if (!group) return
    rig.mixer.update(dt)
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'special' && rig.clips.special.time >= rig.specialDuration - 0.001) setAction('idle')
    if (controls) {
      group.getWorldPosition(point); point.y = 0.20
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="bashe_root" rotation-y={Math.PI * 5 / 18}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}

useGLTF.preload(URL)
