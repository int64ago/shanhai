import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/lu_fish/body.glb'
// Must match rig_lu_fish_native.py: baked stance includes circular counter-yaw.
const RADIUS = 1.05
const SPEED = 0.16

export function LuFish() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const camera = useThree(s => s.camera)
  const tablet = useThree(s => s.size.width > 640 && s.size.width <= 1100 && s.size.width / s.size.height <= 1.3)
  const wide = useThree(s => s.size.width > 1100 && s.size.width / s.size.height > 1.3)
  const lastPosition = useMemo(() => new Vector3(), [])
  const movement = useMemo(() => new Vector3(), [])
  const followTranslation = useMemo(() => new Vector3(), [])
  const root = useRef<Group>(null)
  const angle = useRef(Math.PI + 0.45)
  const center = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || duration <= 0) throw new Error(`鯥缺少有效的 ${name} 动画`)
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
        const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.68 })
        material.side = DoubleSide
        owned.push(material)
        return material
      }
      node.material = Array.isArray(node.material) ? node.material.map(source => ink(source as MeshStandardMaterial)) : ink(node.material as MeshStandardMaterial)
      node.frustumCulled = false
    })
    for (const mesh of originals.keys()) {
      const outline = createOutline(mesh, 0.0013)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready lu_fish')
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
    rig.mixer.stopAllAction()
    const clip = rig.clips[action]
    clip.reset().setEffectiveWeight(1)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    const group = root.current
    if (group && action === 'walk') {
      center.set(group.position.x - RADIUS * Math.cos(angle.current), 0, group.position.z - RADIUS * Math.sin(angle.current))
    }
    return () => { clip.stop() }
  }, [action, rig, center])

  useEffect(() => () => {
    // Return the shared camera to its previous origin when changing beasts.
    camera.position.sub(followTranslation)
    controls?.target.sub(followTranslation)
    followTranslation.set(0, 0, 0)
    lastPosition.set(0, 0, 0)
  }, [camera, controls, followTranslation, lastPosition])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    rig.mixer.update(dt)
    const group = root.current
    if (!group) return
    if (action === 'walk') {
      angle.current -= SPEED / RADIUS * dt
      group.position.set(center.x + RADIUS * Math.cos(angle.current), 0, center.z + RADIUS * Math.sin(angle.current))
    }
    group.rotation.y = Math.PI - angle.current
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - 0.001) setAction('idle')
    // Follow translation with the camera as well as its target. Looking at a
    // moving target from a fixed camera would enlarge the far half of the circle.
    movement.subVectors(group.position, lastPosition)
    followTranslation.add(movement)
    camera.position.add(movement)
    if (controls) {
      controls.target.add(movement)
      group.getWorldPosition(target)
      target.y = tablet ? 0.86 : wide ? 0.52 : 0.68
      controls.target.lerp(target, 1 - Math.exp(-3 * dt))
    }
    lastPosition.copy(group.position)
  })

  return <group ref={root} name="lu_fish_root">
    <primitive object={rig.scene} dispose={null} />
  </group>
}
