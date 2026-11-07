import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Group, LoopOnce, LoopRepeat, MathUtils, Mesh, Quaternion, Vector3, type AnimationAction, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'

const BASE = '/models/jiufeng/'
const FACE_X = [-0.42, -0.21, 0, 0.21, 0.42, -0.315, -0.105, 0.105, 0.315]

export function Jiufeng() {
  const body = useGLTF(`${BASE}body.glb`)
  const face = useGLTF(`${BASE}head.glb`)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const clock = useRef(0)
  const specialStart = useRef(0)
  const route = useRef({ elapsed: 0, phase: 0, yaw: 0.65, origin: new Vector3(0, 0, 0.25) })
  const point = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    scene.name = 'jiufeng_torso'
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    const heads = FACE_X.map((x, i) => {
      const attach = scene.getObjectByName(`human_mount_${i}`)
      if (!attach) throw new Error(`九凤缺少第 ${i + 1} 首颈根`)
      const holder = new Group()
      holder.name = `jiufeng_holder_${i}`
      const head = clone(face.scene)
      head.name = `jiufeng_human_${i}`
      head.scale.setScalar(0.63)
      head.rotation.y = -x * 0.18
      return { attach, holder, head }
    })
    return { scene, mixer, clips, heads }
  }, [body, face])

  useEffect(() => {
    const parts = [{ scene: rig.scene, width: 0.0024 }, ...rig.heads.map(({ head }) => ({ scene: head, width: 0.0013 }))]
    const resources = parts.flatMap(({ scene, width }) => {
      const meshes: Mesh[] = []
      scene.traverse((node) => { if (node instanceof Mesh) meshes.push(node) })
      return meshes.map((mesh) => {
        const original = mesh.material as MeshStandardMaterial
        const material = createInkMaterial({ map: original.map ?? null, saturation: 0.78, inkBoost: -0.12 })
        const outline = createOutline(mesh, width)
        mesh.material = material
        mesh.frustumCulled = false
        mesh.parent!.add(outline)
        return { mesh, original, material, outline }
      })
    })
    rig.scene.updateMatrixWorld(true)
    const inverseScene = rig.scene.getWorldQuaternion(new Quaternion()).invert()
    for (const { attach, holder, head } of rig.heads) {
      holder.quaternion.copy(attach.getWorldQuaternion(new Quaternion()).premultiply(inverseScene).invert())
      holder.add(head)
      attach.add(holder)
    }
    if (import.meta.env.DEV) console.info('[beast] ready jiufeng')
    return () => {
      for (const { attach, holder, head } of rig.heads) { attach.remove(holder); holder.remove(head) }
      rig.mixer.stopAllAction()
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
        mesh.material = original
        material.dispose()
      }
    }
  }, [rig])

  useEffect(() => {
    const name = action === 'special' ? 'alert' : action
    const clip = rig.clips[name]
    if (!clip) throw new Error(`九凤缺少 ${name} 动画`)
    clip.reset().setEffectiveWeight(1).setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.fadeIn(0.2).play()
    if (action === 'walk' && root.current) {
      route.current.elapsed = 0; route.current.phase = 0
      route.current.yaw = root.current.rotation.y
      route.current.origin.copy(root.current.position)
    }
    let timer: number | undefined
    if (action === 'special') {
      specialStart.current = clock.current
      timer = window.setTimeout(() => audio.jiufengCall(), 250)
    }
    return () => { clip.fadeOut(0.2); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    clock.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      const path = route.current, duration = rig.clips.walk.getClip().duration
      path.elapsed += dt
      const steps = Math.floor(path.elapsed / duration), phase = path.elapsed % duration / duration
      const turn = Math.PI * 2 / 24, heading = path.yaw + steps * turn
      const sum = Math.sin(steps * turn / 2) / Math.sin(turn / 2), middle = path.yaw + (steps - 1) * turn / 2
      g.position.copy(path.origin)
      g.position.x += 0.12 * duration * (sum * Math.sin(middle) + phase * Math.sin(heading))
      g.position.z += 0.12 * duration * (sum * Math.cos(middle) + phase * Math.cos(heading))
      g.rotation.y = heading + turn * MathUtils.smoothstep(phase, 0.5, 1)
      if (phase < path.phase) audio.footstep(0, 0.22)
      path.phase = phase
    }
    if (action === 'special' && clock.current - specialStart.current > 4.8) setAction('idle')
    if (controls) {
      g.getWorldPosition(point); point.y = 0.66
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, 0.25]} rotation-y={0.65}>
    <primitive object={rig.scene} />
  </group>
}

for (const part of ['body', 'head']) useGLTF.preload(`${BASE}${part}.glb`)
