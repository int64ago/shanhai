import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, MathUtils, Mesh, MeshStandardMaterial, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type Skeleton } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { createGroundContacts } from '../groundContacts'

const URL = '/models/boyi/body.glb'
const RADIUS = 0.9
const SPEED = 0.16 / (0.68 * 1.6)
const SPECIAL_SECONDS = 4.8

/** 四耳、九尾与背目均在独立骨架中，不向 useGLTF 缓存挂接任何器官。 */
export function Boyi() {
  const body = useGLTF(URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const path = useRef({ angle: Math.PI / 2, center: new Vector3() })
  const phase = useRef(0)
  const point = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!clips[name]) throw new Error(`猼訑缺少 ${name} 动画`)
    }
    return { scene, mixer, clips }
  }, [body])

  const contacts = useMemo(() => createGroundContacts(rig.scene, ['back_l', 'front_l', 'back_r', 'front_r']), [rig])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse((node) => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      originals.set(node, node.material)
      const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.78 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const fine = node.name.includes('dorsal') || node.name.includes('nostril') || node.name.includes('mouth')
      const outline = createOutline(node, fine ? 0.0007 : node.name.startsWith('boyi_tail_') ? 0.0014 : 0.0022)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready boyi')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) {
        outline.removeFromParent()
        const material = outline.material as Material
        material.dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      const skeletons = new Set<Skeleton>()
      rig.scene.traverse((node) => {
        if (node instanceof SkinnedMesh) skeletons.add(node.skeleton)
      })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action]
    clip.reset().setEffectiveWeight(1).fadeIn(0.32)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    contacts.reset()
    if (action === 'walk' && root.current) {
      path.current.angle = Math.PI - root.current.rotation.y
      path.current.center.copy(root.current.position)
      path.current.center.x -= RADIUS * Math.cos(path.current.angle)
      path.current.center.z -= RADIUS * Math.sin(path.current.angle)
      phase.current = 0
    }
    let timer: number | undefined
    if (action === 'special') {
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => audio.boyiCall(pan), 180)
    }
    return () => { clip.fadeOut(0.32); clearTimeout(timer) }
  }, [action, rig, camera, point, contacts])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const group = root.current
    if (!group) return
    rig.mixer.update(dt)
    if (action === 'walk') {
      path.current.angle -= SPEED / RADIUS * dt
      group.position.copy(path.current.center)
      group.position.x += Math.cos(path.current.angle) * RADIUS
      group.position.z += Math.sin(path.current.angle) * RADIUS
      group.rotation.y = Math.PI - path.current.angle
      const current = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      if (import.meta.env.DEV) group.userData.walkPhase = current
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((phase.current < beat && current >= beat) || (beat === 0 && current < phase.current)) audio.footstep(0, 0.3)
      }
      phase.current = current
      // This sheep has a wider rear stance; converge the planted hocks before
      // rendering so the entire generated hoof stays anchored around a turn.
      for (let iteration = 0; iteration < 3; iteration++) contacts.update(group, current, 0.68)
    }
    if (action === 'special' && rig.clips.special.time >= SPECIAL_SECONDS - 0.001) setAction('idle')
    if (controls) {
      group.getWorldPosition(point)
      point.y = 0.52
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="boyi_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}

useGLTF.preload(URL)
