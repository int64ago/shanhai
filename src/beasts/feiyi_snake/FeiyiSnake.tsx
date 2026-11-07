import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, MathUtils, Mesh, MeshStandardMaterial, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/feiyi_snake/body.glb'
// rig_feiyi_snake.py uses radius 1.5, speed .085 before this uniform scale.
const SCALE = .8
const RADIUS = 1.5 * SCALE
const SPEED = .085 * SCALE
const SPECIAL_SECONDS = 4.8

export function FeiyiSnake() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const camera = useThree(s => s.camera)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
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
      if (!clips[name]) throw new Error(`肥遗缺少 ${name} 动画`)
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
      const source = node.material as MeshStandardMaterial
      const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: .72 })
      // Thin AI feather/toe surfaces include locally reversed triangles.
      // Render both sides so the backface ink shell cannot fill those gaps.
      material.side = DoubleSide
      node.material = material
      node.frustumCulled = false
      owned.push(material)
    })
    for (const mesh of originals.keys()) {
      const width = mesh.name.includes('wing') ? .00025 : mesh.name.includes('leg') ? .00015 : .0008
      const outline = createOutline(mesh, width, .0035)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready feiyi_snake')
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
    clip.reset().setEffectiveWeight(1).fadeIn(.3)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    const timers: number[] = []
    if (action === 'special') {
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * .8 : 0
      // Source has no call: only inferred movement sounds, no invented roar.
      timers.push(window.setTimeout(() => audio.wingFlutter(pan, .30), 450))
      timers.push(window.setTimeout(() => audio.wingFlutter(pan, .22), 1500))
    }
    return () => { clip.fadeOut(.3); timers.forEach(clearTimeout) }
  }, [action, rig, camera, point])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, .05)
    const group = root.current
    if (!group) return
    rig.mixer.update(dt)
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'walk') {
      angle.current -= SPEED / RADIUS * dt
      group.position.set(Math.cos(angle.current) * RADIUS, 0, Math.sin(angle.current) * RADIUS)
      group.rotation.y = Math.PI - angle.current
      const current = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      if ((phase.current < .5 && current >= .5) || current < phase.current) audio.footstep(0, .18)
      phase.current = current
    }
    if (action === 'special' && rig.clips.special.time >= SPECIAL_SECONDS - .001) setAction('idle')
    if (controls) {
      group.getWorldPosition(point)
      point.y = .28
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="feiyi_snake_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2} scale={SCALE}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}

useGLTF.preload(URL)
