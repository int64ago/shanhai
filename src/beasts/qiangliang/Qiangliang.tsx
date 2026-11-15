import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Bone, DoubleSide, LoopOnce, LoopRepeat, Mesh, Quaternion, SkinnedMesh, Vector3 } from 'three'
import type { AnimationAction, Group, Material, MeshStandardMaterial, Skeleton } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { animateSupportedSnake, createSupportedSnake } from './snakes'

const BODY = '/models/qiangliang/body.glb'
const SNAKE = '/models/qiangliang/snake.glb'
const RADIUS = 1
const SPEED = 0.085

export function Qiangliang() {
  const body = useGLTF(BODY)
  const snake = useGLTF(SNAKE)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const angle = useRef(Math.PI / 2)
  const time = useRef(0)
  const phase = useRef(0)
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!(clips[name]?.getClip().duration > 0)) throw new Error(`强良缺少 ${name} 动画`)
    }
    scene.updateMatrixWorld(true)
    const serpentSource = clone(snake.scene)
    const mouth = createSupportedSnake(serpentSource, 0.43)
    const held = createSupportedSnake(serpentSource, 0.46)
    const attachments = [
      { ...mouth, attach: scene.getObjectByName('mouth_attach') as Bone, name: 'mouth_snake', turn: Math.PI / 2 },
      { ...held, attach: scene.getObjectByName('hold_l_attach') as Bone, name: 'held_snake', turn: -0.45 },
    ]
    for (const item of attachments) {
      if (!item.attach?.isBone) throw new Error(`强良缺少 ${item.name} 挂点`)
      const rest = item.attach.getWorldQuaternion(new Quaternion()).premultiply(scene.getWorldQuaternion(new Quaternion()).invert())
      item.holder.quaternion.copy(rest.invert()).multiply(new Quaternion().setFromAxisAngle(new Vector3(0, 0, 1), item.turn))
      item.holder.name = item.name
    }
    return { scene, mixer, clips, attachments }
  }, [body, snake])

  useEffect(() => {
    for (const item of rig.attachments) item.attach.add(item.holder)
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      originals.set(node, node.material)
      const source = node.material as MeshStandardMaterial
      const isSnake = node.name === 'qiangliang_supported_serpent'
      const material = createInkMaterial({ map: source.map ?? null, tint: isSnake ? '#788b73' : '#ffffff', saturation: isSnake ? 0.35 : 0.68 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const outline = createOutline(node, node.name === 'qiangliang_supported_serpent' ? 0.0009 : 0.0014)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready qiangliang')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) { outline.removeFromParent(); (outline.material as Material).dispose() }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      for (const item of rig.attachments) {
        item.holder.removeFromParent()
        item.mesh.skeleton.dispose()
        item.mesh.geometry.dispose()
      }
      const skeletons = new Set<Skeleton>()
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
    if (action === 'walk') phase.current = 0
    return () => { clip.fadeOut(0.3) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    rig.mixer.update(dt)
    for (let i = 0; i < rig.attachments.length; i++) animateSupportedSnake(rig.attachments[i].bones, time.current, i * 1.7, action === 'special' ? 1 : 0, i === 1 ? 0.035 : 0)
    const group = root.current
    if (!group) return
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'walk') {
      angle.current -= SPEED / RADIUS * dt
      group.position.set(Math.cos(angle.current) * RADIUS, 0, Math.sin(angle.current) * RADIUS)
      group.rotation.y = Math.PI - angle.current
      const current = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      if ((phase.current < 0.5 && current >= 0.5) || current < phase.current) audio.footstep(0, 0.25)
      phase.current = current
    }
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - 0.001) setAction('idle')
    if (controls) {
      group.getWorldPosition(target); target.y = 0.85
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="qiangliang_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}
