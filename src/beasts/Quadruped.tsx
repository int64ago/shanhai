import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, MathUtils, Mesh, Object3D, Quaternion, Vector3, type AnimationAction, type Group, type Texture } from 'three'
import { useApp } from '../app/store'
import { audio } from '../systems/audio/AudioEngine'
import { createOutline, inkify } from '../systems/ink/inkify'
import { createInkMaterial } from '../systems/ink/inkMaterial'
import { FoxFire } from '../systems/vfx/FoxFire'
import { aimTail, createTail, prepareTailGeometry, TAIL_BONES } from './jiuweihu/tails'

interface Props {
  id: string
  /** 原文规定的尾数；0 表示保留模型原生尾。 */
  tailCount?: number
  tailColor?: string
  inkBoost?: number
  onCall: (pan: number) => void
}

const RADIUS = 1.1
const SPEED = 0.3
const SPECIAL_SECONDS = 4.6

/** 四足兽共用步态与外挂尾，异相数量、设色和鸣声由各兽明确配置。 */
export function Quadruped({ id, tailCount = 0, tailColor = '#b7492b', inkBoost = 0, onCall }: Props) {
  const body = useGLTF(`/models/${id}/body.glb`)
  const tailSource = useGLTF('/models/jiuweihu/tail.glb')
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const clock = useRef(0)
  const specialStart = useRef(0)
  const walk = useRef({ angle: Math.PI / 2, phase: 0 })
  const intensity = useRef(0)
  const position = useMemo(() => new Vector3(), [])

  const rig = useMemo(() => {
    const scene = body.scene
    inkify(scene, { saturation: 0.88, outline: 0.0055 })
    scene.traverse((o) => { if (o instanceof Mesh) o.frustumCulled = false })
    scene.updateMatrixWorld(true)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    const attach = scene.getObjectByName('tail_attach')
    if (!attach) throw new Error(`${id}: 缺少 tail_attach 骨骼`)
    const holder = new Object3D()
    const relative = attach.getWorldQuaternion(new Quaternion()).premultiply(scene.getWorldQuaternion(new Quaternion()).invert())
    holder.quaternion.copy(relative.invert())
    const scale = attach.getWorldScale(new Vector3())
    holder.scale.set(1 / scale.x, 1 / scale.y, 1 / scale.z)
    const tails = []
    if (tailCount > 0) {
      let source: Mesh | undefined
      tailSource.scene.updateMatrixWorld(true)
      tailSource.scene.traverse((o) => { if (!source && o instanceof Mesh) source = o })
      if (!source) throw new Error('缺少尾巴母件网格')
      const { geometry, length } = prepareTailGeometry(source, tailCount > 1 ? 0.21 : 0.16)
      const material = createInkMaterial({
        map: (source.material as { map?: Texture }).map ?? null,
        saturation: 0.25, tailLength: length, tint: tailColor, inkBoost, tipWhite: 0,
      })
      for (let i = 0; i < tailCount; i++) {
        const tail = createTail(geometry, material, length)
        tail.pivot.add(createOutline(tail.mesh, 0.0035))
        holder.add(tail.pivot)
        tails.push(tail)
      }
    }
    return { scene, mixer, clips, attach, holder, tails, emitters: tails.map((t) => t.tip) }
  }, [body, tailSource, id, tailCount, tailColor, inkBoost])

  useEffect(() => {
    rig.attach.add(rig.holder)
    if (import.meta.env.DEV) console.info(`[beast] ready ${id}`)
    return () => {
      rig.attach.remove(rig.holder)
      rig.mixer.stopAllAction()
    }
  }, [rig, id])

  useEffect(() => {
    const name = action === 'special' ? 'alert' : action
    const clip = rig.clips[name]
    if (!clip) throw new Error(`${id}: 缺少 ${name} 动画`)
    // 每次 effect 都重新启动，兼容 StrictMode 的 setup → cleanup → setup。
    clip.reset().setEffectiveWeight(1).fadeIn(0.28).play()
    let timer: number | undefined
    if (action === 'special') {
      specialStart.current = clock.current
      intensity.current = 2.8
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(position).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => onCall(pan), 100)
    }
    return () => { clip.fadeOut(0.28); clearTimeout(timer) }
  }, [action, rig, camera, id, onCall, position])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    clock.current += dt
    const t = clock.current
    const g = root.current
    if (!g) return
    rig.mixer.update(dt)
    if (action === 'walk') {
      walk.current.angle -= SPEED / RADIUS * dt
      const angle = walk.current.angle
      g.position.set(Math.cos(angle) * RADIUS, 0, Math.sin(angle) * RADIUS)
      // 在最短角度方向插值，经过 ±π 时不突然绕回一整圈。
      const yaw = Math.atan2(Math.sin(angle), -Math.cos(angle))
      const delta = Math.atan2(Math.sin(yaw - g.rotation.y), Math.cos(yaw - g.rotation.y))
      g.rotation.y += delta * (1 - Math.exp(-6 * dt))
      const clip = rig.clips.walk
      const phase = (clip.time % clip.getClip().duration) / clip.getClip().duration
      const previous = walk.current.phase
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((previous < beat && phase >= beat) || (beat === 0 && phase < previous)) audio.footstep(0, 0.4)
      }
      walk.current.phase = phase
    }
    if (action === 'special' && t - specialStart.current > SPECIAL_SECONDS) setAction('idle')
    rig.tails.forEach((tail, i) => {
      const spread = tailCount > 1 ? (i / (tailCount - 1) - 0.5) * 2.4 : Math.sin(t) * 0.16
      const elevation = action === 'special' ? 0.85 : tailCount > 1 ? 0.55 : -0.28
      aimTail(tail.pivot, elevation + (i % 2) * 0.08, spread)
      tail.bones.forEach((bone, j) => {
        const k = j / TAIL_BONES
        bone.rotation.z = -0.08 + 0.1 * Math.sin(t * (action === 'walk' ? 3.5 : 1.7) - j * 0.65 + i) * (0.4 + k)
        bone.rotation.y = 0.09 * Math.cos(t * 1.5 - j * 0.55 + i)
      })
    })
    intensity.current = MathUtils.damp(intensity.current, action === 'special' ? 1.8 : 0, 2, dt)
    if (controls) {
      g.getWorldPosition(position)
      position.y = 0.52
      controls.target.lerp(position, 1 - Math.exp(-2 * dt))
    }
  })

  return <>
    <group ref={root} position={[0, 0, RADIUS]} rotation-y={Math.PI / 2 - 0.22}>
      <primitive object={rig.scene} />
    </group>
    {rig.emitters.length > 0 && <FoxFire emitters={rig.emitters} intensity={intensity} coreColor="#e9c488" edgeColor="#ad6632" />}
  </>
}
