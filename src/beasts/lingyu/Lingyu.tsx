import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/lingyu/body.glb'

export function Lingyu() {
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
      if (!clips[name] || clips[name].getClip().duration <= 0) throw new Error(`陵鱼缺少 ${name} 动画`)
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
        const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.68, wash2: { start: 0.56, end: 0.66, strength: 0.6 } })
        // Only the bounded donor and bridge carry authored linear vertex colors.
        // Feed them into albedo without changing shared geometry or global ink GLSL.
        if (node.geometry.getAttribute('color')) {
          material.vertexShader = material.vertexShader
            .replace('varying vec2 vUv;', 'attribute vec4 color; varying vec3 vLingyuColor; varying vec2 vUv;')
            .replace('vUv = uv;', 'vUv = uv; vLingyuColor = color.rgb;')
          material.fragmentShader = material.fragmentShader
            .replace('varying vec2 vUv;', 'varying vec3 vLingyuColor; varying vec2 vUv;')
            .replace('vec3(0.6);', 'vec3(1.0);')
            .replace('float lum = dot(albedo,', 'albedo *= vLingyuColor; float lum = dot(albedo,')
        }
        material.side = DoubleSide
        owned.push(material)
        return material
      }
      node.material = Array.isArray(node.material) ? node.material.map(source => ink(source as MeshStandardMaterial)) : ink(node.material as MeshStandardMaterial)
      node.frustumCulled = false
    })
    for (const mesh of originals.keys()) {
      const outline = createOutline(mesh, 0.0012)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready lingyu')
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
    rig.mixer.update(Math.min(rawDt, 0.05))
    const group = root.current
    if (!group) return
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - 0.001) setAction('idle')
    if (controls) {
      target.set(0, width <= 640 ? 1.1 : 0.9, 0)
      controls.target.lerp(target, 1 - Math.exp(-2 * Math.min(rawDt, 0.05)))
    }
  })

  return <group ref={root} name="lingyu_root">
    <primitive object={rig.scene} dispose={null} />
  </group>
}
