import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, LoopOnce, LoopRepeat, MathUtils, Mesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'

const URL = '/models/gudiao/body.glb'

export function Gudiao() {
  const body = useGLTF(URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const time = useRef(0)
  const specialStart = useRef(0)
  const route = useRef({ elapsed: 0, phase: 0, yaw: 1.25, origin: new Vector3(0, 0, 0.35) })
  const point = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    scene.name = 'gudiao_individual'
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const meshes: Mesh[] = []
    rig.scene.traverse((node) => { if (node instanceof Mesh) meshes.push(node) })
    const resources = meshes.map((mesh) => {
      const original = mesh.material as MeshStandardMaterial
      const material = createInkMaterial({ map: original.map ?? null, saturation: 0.82, inkBoost: -0.12 })
      const outline = createOutline(mesh, 0.0025)
      mesh.material = material
      mesh.frustumCulled = false
      mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    if (import.meta.env.DEV) console.info('[beast] ready gudiao')
    return () => {
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
    if (!clip) throw new Error(`蛊雕缺少 ${name} 动画`)
    clip.reset().setEffectiveWeight(1).setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.fadeIn(0.2).play()
    if (action === 'walk' && root.current) {
      route.current.elapsed = 0
      route.current.phase = 0
      route.current.yaw = root.current.rotation.y
      route.current.origin.copy(root.current.position)
    }
    let timer: number | undefined
    if (action === 'special') {
      specialStart.current = time.current
      timer = window.setTimeout(() => audio.gudiaoCry(), 250)
    }
    return () => { clip.fadeOut(0.2); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
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
      // Turn only while airborne; baked foot retreat cancels the stance chord.
      g.rotation.y = heading + turn * MathUtils.smoothstep(phase, 0.5, 1)
      if (phase < path.phase) audio.footstep(0, 0.28)
      path.phase = phase
    }
    if (action === 'special' && time.current - specialStart.current > 4.8) setAction('idle')
    if (controls) {
      g.getWorldPosition(point)
      point.y = 0.58
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} position={[0, 0, 0.35]} rotation-y={1.25}>
    <primitive object={rig.scene} />
  </group>
}

useGLTF.preload(URL)
