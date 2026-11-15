import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, LoopOnce, LoopRepeat, Mesh, PerspectiveCamera, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'

const URL = '/models/longzhi/body.glb'
const RADIUS = 3
const SPEED = .07 / (.68 * 2.4)

export function Longzhi() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const camera = useThree(s => s.camera)
  const size = useThree(s => s.size)
  const root = useRef<Group>(null)
  const angle = useRef(0)
  const previous = useMemo(() => new Vector3(), [])
  const movement = useMemo(() => new Vector3(), [])
  const followTranslation = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(0, .70, 0), [])
  useEffect(() => {
    if (!(camera instanceof PerspectiveCamera)) return
    const aspect = size.width / size.height
    // Allow the tail fan to turn past the seals and narrow tablet edge.
    const base = size.width <= 640 ? 32 : size.width <= 1100 ? 40 : 34
    camera.fov = aspect >= 1.2 ? base : Math.min(70, Math.atan(Math.tan(base * Math.PI / 360) * 1.2 / aspect) * 360 / Math.PI)
    camera.filmOffset = size.width <= 640 ? 0 : size.width <= 1100 ? -4 : -6
    camera.updateProjectionMatrix()
  }, [camera, size.width, size.height])
  useEffect(() => () => {
    // Undo only this beast's world-path translation on the shared camera.
    camera.position.sub(followTranslation)
    controls?.target.sub(followTranslation)
    followTranslation.set(0, 0, 0)
  }, [camera, controls, followTranslation])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || duration <= 0) throw new Error(`蠪侄缺少有效的 ${name} 动画`)
    }
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const materials: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      originals.set(node, node.material)
      const ink = (source: MeshStandardMaterial) => {
        const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: .66 })
        materials.push(material)
        return material
      }
      node.material = Array.isArray(node.material) ? node.material.map(source => ink(source as MeshStandardMaterial)) : ink(node.material as MeshStandardMaterial)
      node.frustumCulled = false
    })
    for (const mesh of originals.keys()) {
      const outline = createOutline(mesh, .0011)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready longzhi')
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
    clip.reset().setEffectiveWeight(1).fadeIn(.3)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    const voice = action === 'special' ? window.setTimeout(() => audio.infantCry(), 240) : undefined
    return () => { clip.fadeOut(.3); window.clearTimeout(voice) }
  }, [action, rig])

  useFrame((_, delta) => {
    const dt = Math.min(delta, .05), group = root.current
    if (!group) return
    rig.mixer.update(dt)
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'walk') {
      previous.copy(group.position)
      angle.current += SPEED / RADIUS * dt
      group.position.set(RADIUS * (1 - Math.cos(angle.current)), 0, RADIUS * Math.sin(angle.current))
      group.rotation.y = angle.current
      movement.copy(group.position).sub(previous)
      followTranslation.add(movement)
      camera.position.add(movement)
      if (controls) controls.target.add(movement)
    }
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - .001) setAction('idle')
    target.copy(group.position).y = .70
    if (controls) controls.target.lerp(target, 1 - Math.exp(-2 * dt))
  })

  return <group ref={root} name="longzhi_root">
    <primitive object={rig.scene} dispose={null} />
  </group>
}
