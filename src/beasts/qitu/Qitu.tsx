import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Euler, Group, LoopOnce, LoopRepeat, MathUtils, Mesh, Quaternion, ShaderMaterial, Vector3, type AnimationAction, type Object3D } from 'three'
import { useApp } from '../../app/store'
import { inkify } from '../../systems/ink/inkify'
import { audio } from '../../systems/audio/AudioEngine'

const BASE = '/models/qitu/'
const HEADS = [[-0.08, -0.07, 0, 0.55], [0, 0.05, 0.06, 0], [0.08, -0.07, 0, -0.55]] as const
const TAILS = [-0.85, -0.51, -0.17, 0.17, 0.51, 0.85]

export function Qitu() {
  const body = useGLTF(`${BASE}body.glb`)
  const head = useGLTF(`${BASE}head.glb`)
  const tail = useGLTF(`${BASE}tail.glb`)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const clock = useRef(0)
  const specialStart = useRef(0)
  const route = useRef({ elapsed: 0, phase: 0, yaw: 1.1, origin: new Vector3(0, 0, 0.35) })
  const point = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    function part(model: typeof body, name: string, outline: number) {
      const scene = clone(model.scene)
      scene.name = name
      inkify(scene, { saturation: 0.75, outline })
      scene.traverse((o) => {
        if (!(o instanceof Mesh)) return
        o.frustumCulled = false
        if (!o.userData.inkOutline && o.material instanceof ShaderMaterial) o.material.uniforms.uInkBoost.value = -0.18
      })
      const mixer = new AnimationMixer(scene)
      const clips: Record<string, AnimationAction> = {}
      for (const clip of model.animations) clips[clip.name] = mixer.clipAction(clip)
      return { scene, mixer, clips }
    }
    const torso = part(body, 'qitu_torso', 0.0025)
    const neck = torso.scene.getObjectByName('neck_attach')
    const rump = torso.scene.getObjectByName('tail_attach')
    if (!neck || !rump) throw new Error('鵸鵌缺少颈尾挂点')
    const modules = [
      ...HEADS.map(([x, y, z, roll], i) => {
        const holder = new Group(), layout = new Group()
        holder.name = `qitu_head_holder_${i}`
        layout.position.set(x, y, z)
        layout.rotation.z = roll
        layout.scale.setScalar(0.88)
        return { ...part(head, `qitu_head_${i}`, 0.002), holder, layout, attach: neck, kind: 'head', index: i }
      }),
      ...TAILS.map((angle, i) => {
        const holder = new Group(), layout = new Group()
        holder.name = `qitu_tail_holder_${i}`
        layout.position.set(-angle * 0.1, i % 2 ? -0.018 : 0.018, -0.03)
        layout.quaternion.setFromEuler(new Euler(0.10 + (i % 2) * 0.04, angle, 0, 'YXZ'))
        return { ...part(tail, `qitu_tail_${i}`, 0.0015), holder, layout, attach: rump, kind: 'tail', index: i }
      }),
    ]
    return { torso, modules }
  }, [body, head, tail])

  useEffect(() => {
    const scene = rig.torso.scene
    scene.updateMatrixWorld(true)
    const inverseScene = scene.getWorldQuaternion(new Quaternion()).invert()
    for (const module of rig.modules) {
      // Rest rotation is relative to the body scene, excluding outer locomotion.
      const rest = module.attach.getWorldQuaternion(new Quaternion()).premultiply(inverseScene).invert()
      module.holder.quaternion.copy(rest)
      module.holder.add(module.layout)
      module.layout.add(module.scene)
      module.attach.add(module.holder)
    }
    if (import.meta.env.DEV) console.info('[beast] ready qitu')
    return () => {
      for (const module of rig.modules) {
        module.attach.remove(module.holder)
        module.layout.remove(module.scene)
        module.holder.remove(module.layout)
      }
      for (const part of [rig.torso, ...rig.modules]) {
        part.mixer.stopAllAction()
        part.scene.traverse((o) => {
          if (o instanceof Mesh) for (const m of Array.isArray(o.material) ? o.material : [o.material]) m.dispose()
        })
      }
    }
  }, [rig])

  useEffect(() => {
    const name = action === 'special' ? 'alert' : action
    const parts = [rig.torso, ...rig.modules]
    for (const [i, part] of parts.entries()) {
      const clip = part.clips[name]
      if (!clip) throw new Error(`鵸鵌缺少 ${name} 动画`)
      clip.reset().setEffectiveWeight(1).setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
      clip.clampWhenFinished = action === 'special'
      clip.time = i === 0 ? 0 : action === 'idle' ? i * 0.37 % 4.8 : action === 'walk' ? i * 0.13 % 1.4 : i * 0.08
      clip.fadeIn(0.2).play()
    }
    if (action === 'walk' && root.current) {
      route.current.elapsed = 0
      route.current.phase = 0
      route.current.yaw = root.current.rotation.y
      route.current.origin.copy(root.current.position)
    }
    let timer: number | undefined
    if (action === 'special') {
      specialStart.current = clock.current
      timer = window.setTimeout(() => audio.qituLaugh(), 180)
    }
    return () => {
      for (const part of parts) part.clips[name].fadeOut(0.2)
      clearTimeout(timer)
    }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    clock.current += dt
    rig.torso.mixer.update(dt)
    for (const part of rig.modules) part.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      const path = route.current, duration = rig.torso.clips.walk.getClip().duration
      path.elapsed += dt
      const steps = Math.floor(path.elapsed / duration), phase = path.elapsed % duration / duration
      const turn = Math.PI * 2 / 24, heading = path.yaw + steps * turn
      const sum = Math.sin(steps * turn / 2) / Math.sin(turn / 2), middle = path.yaw + (steps - 1) * turn / 2
      g.position.copy(path.origin)
      g.position.x += 0.12 * duration * (sum * Math.sin(middle) + phase * Math.sin(heading))
      g.position.z += 0.12 * duration * (sum * Math.cos(middle) + phase * Math.cos(heading))
      g.rotation.y = heading + turn * MathUtils.smoothstep(phase, 0.5, 1)
      if (phase < path.phase) audio.footstep(0, 0.2)
      path.phase = phase
    }
    if (action === 'special' && clock.current - specialStart.current > 4.8) setAction('idle')
    if (controls) {
      g.getWorldPosition(point)
      point.y = 0.48
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, 0.35]} rotation-y={1.1}>
    <primitive object={rig.torso.scene as Object3D} />
  </group>
}

for (const part of ['body', 'head', 'tail']) useGLTF.preload(`${BASE}${part}.glb`)
