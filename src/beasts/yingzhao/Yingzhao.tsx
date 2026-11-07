import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, MathUtils, Mesh, MeshStandardMaterial, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/yingzhao/body.glb'
// Keep these synchronized with rig_yingzhao.py's inverse circular hoof targets.
const RADIUS = 1
const SPEED = 0.14
const SPECIAL_SECONDS = 4.8

export function Yingzhao() {
  const body = useGLTF(URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const angle = useRef(Math.PI / 2)
  const phase = useRef(0)
  const point = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!clips[name]) throw new Error(`英招缺少 ${name} 动画`)
    }
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse((node) => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      originals.set(node, node.material)
      const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.8 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const width = node.name.includes('human_head') ? 0.001 : node.name.includes('wing') ? 0.0018 : 0.002
      const outline = createOutline(node, width)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready yingzhao')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      // SkeletonUtils owns these skeletons; geometry and textures remain cached.
      const skeletons = new Set<SkinnedMesh['skeleton']>()
      rig.scene.traverse(node => { if (node instanceof SkinnedMesh) skeletons.add(node.skeleton) })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action]
    clip.reset().setEffectiveWeight(1).fadeIn(0.32)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    let timer: number | undefined
    if (action === 'special') {
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => { audio.yingzhaoCall(pan); audio.wingFlutter(pan, 0.35) }, 240)
    }
    return () => { clip.fadeOut(0.32); clearTimeout(timer) }
  }, [action, rig, camera, point])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const group = root.current
    if (!group) return
    rig.mixer.update(dt)
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'walk') {
      angle.current -= SPEED / RADIUS * dt
      group.position.set(Math.cos(angle.current) * RADIUS, 0, Math.sin(angle.current) * RADIUS)
      // Exact tangent heading: damping this yaw breaks baked world hoof contact.
      group.rotation.y = Math.PI - angle.current
      const current = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((phase.current < beat && current >= beat) || (beat === 0 && current < phase.current)) audio.footstep(0, 0.35)
      }
      phase.current = current
    }
    if (action === 'special' && rig.clips.special.time >= SPECIAL_SECONDS - 0.001) setAction('idle')
    if (controls) {
      group.getWorldPosition(point)
      point.y = 0.58
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="yingzhao_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} />
  </group>
}

useGLTF.preload(URL)
