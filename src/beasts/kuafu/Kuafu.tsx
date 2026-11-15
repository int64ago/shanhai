import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Bone, Color, DoubleSide, LoopOnce, LoopRepeat, Mesh, Quaternion, SkinnedMesh, Vector3 } from 'three'
import type { AnimationAction, Group, Material, MeshStandardMaterial, Skeleton } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { animateEarSnake, createEarSnake } from './earSnakes'

const RADIUS = 1, SPEED = 0.09

export function Kuafu() {
  const body = useGLTF('/models/kuafu/body.glb')
  const ear = useGLTF('/models/kuafu/ear.glb')
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const phone = useThree(s => s.size.width <= 640)
  const root = useRef<Group>(null)
  const angle = useRef(Math.PI / 2), time = useRef(0), phase = useRef(0)
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!(clips[name]?.getClip().duration > 0)) throw new Error(`夸父缺少 ${name} 动画`)
    }
    scene.updateMatrixWorld(true)
    const source = clone(ear.scene)
    const attachments = ['l', 'r'].map(side => {
      const item = createEarSnake(source)
      const attach = scene.getObjectByName(`ear_${side}_attach`) as Bone
      if (!attach?.isBone) throw new Error(`夸父缺少 ${side} 耳挂点`)
      const rest = attach.getWorldQuaternion(new Quaternion()).premultiply(scene.getWorldQuaternion(new Quaternion()).invert())
      item.holder.quaternion.copy(rest.invert()).multiply(new Quaternion().setFromAxisAngle(new Vector3(0, 0, 1), side === 'l' ? 0.4 : -0.4))
      item.holder.name = `ear_${side}_snake_holder`
      return { ...item, attach }
    })
    return { scene, mixer, clips, attachments }
  }, [body, ear])

  useEffect(() => {
    for (const item of rig.attachments) item.attach.add(item.holder)
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = [], outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      originals.set(node, node.material)
      const source = node.material as MeshStandardMaterial
      const held = node.name.startsWith('kuafu_held_snake') || !!node.parent?.name.startsWith('kuafu_held_snake')
      const serpent = held || node.name === 'kuafu_ear_snake'
      const tint = source.color.clone().multiply(new Color(held ? '#e7bd6b' : '#ffffff'))
      const material = createInkMaterial({ map: source.map ?? null, tint: '#' + tint.getHexString(), saturation: serpent ? 0.82 : 0.68 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const outline = createOutline(node, node.name.includes('snake') || node.parent?.name.includes('snake') ? 0.0007 : 0.0012)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready kuafu')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) { outline.removeFromParent(); (outline.material as Material).dispose() }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      for (const item of rig.attachments) { item.holder.removeFromParent(); item.mesh.geometry.dispose(); item.mesh.skeleton.dispose() }
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
    for (let i = 0; i < rig.attachments.length; i++) animateEarSnake(rig.attachments[i].bones, time.current, i * 1.9, action === 'special')
    const group = root.current
    if (!group) return
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'walk') {
      angle.current -= SPEED / RADIUS * dt
      group.position.set(Math.cos(angle.current) * RADIUS, 0, Math.sin(angle.current) * RADIUS)
      group.rotation.y = Math.PI - angle.current
      const current = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      if ((phase.current < 0.5 && current >= 0.5) || current < phase.current) audio.footstep(0, 0.3)
      phase.current = current
    }
    if (action === 'special' && rig.clips.special.time >= rig.clips.special.getClip().duration - 0.001) setAction('idle')
    if (controls) {
      // Portrait framing sits below the source card; desktop clears the selector.
      group.getWorldPosition(target); target.y = phone ? 1.5 : 0.82
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="kuafu_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}
