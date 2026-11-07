import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, MathUtils, Mesh, Vector3, type Group, type MeshStandardMaterial, type ShaderMaterial } from 'three'
import { createGroundContacts } from '../groundContacts'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'

const RADIUS = 1.15
const SPEED = 0.27
const SPECIAL_SECONDS = 4.8

export function Fengxi() {
  const { scene, animations } = useGLTF('/models/fengxi/body.glb')
  const mixer = useMemo(() => new AnimationMixer(scene), [scene])
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const position = useMemo(() => new Vector3(), [])
  const cameraShift = useMemo(() => new Vector3(), [])
  const path = useRef({ angle: Math.PI / 2, center: new Vector3() })
  const elapsed = useRef(0)
  const specialStart = useRef(0)
  const previousPhase = useRef(0)
  const contacts = useMemo(() => createGroundContacts(scene, ['back_l', 'front_l', 'back_r', 'front_r']), [scene])

  // Translate camera and orbit target together so the large boar stays in frame.
  // Undo only our automatic translation when switching beasts, preserving orbit input.
  useEffect(() => () => {
    camera.position.sub(cameraShift)
    controls?.target.sub(cameraShift)
    cameraShift.set(0, 0, 0)
  }, [camera, cameraShift, controls])

  // Reversible attachment to the actual cached singleton, including StrictMode replay.
  useEffect(() => {
    const meshes: Mesh[] = []
    scene.traverse((object) => { if (object instanceof Mesh) meshes.push(object) })
    const resources = meshes.map((mesh) => {
      const original = mesh.material as MeshStandardMaterial
      const tusks = original.name.startsWith('Fengxi_Tusks')
      const bristles = original.name.startsWith('Fengxi_Bristles')
      const material = createInkMaterial({
        map: original.map ?? null, saturation: 0.8,
        tint: tusks ? '#f0dfb6' : bristles ? '#44372b' : '#ffffff',
        inkBoost: bristles ? 0.65 : 0,
      })
      material.name = original.name
      const outline = createOutline(mesh, bristles ? 0.0007 : tusks ? 0.0015 : 0.003)
      mesh.material = material
      mesh.frustumCulled = false
      mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    scene.name = 'Fengxi_CachedScene'
    if (import.meta.env.DEV) console.info(`[beast] ready fengxi primitives=${meshes.length} outlines=${resources.length} tusks=2 bristleTufts=15`)
    return () => {
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent()
        ;(outline.material as ShaderMaterial).dispose()
        mesh.material = original
        material.dispose()
      }
      mixer.stopAllAction()
      if (import.meta.env.DEV) console.info('[fengxi] cleanup outlines=0 runtimeAppendages=0')
    }
  }, [scene, mixer])

  useEffect(() => {
    const name = action === 'special' ? 'alert' : action
    const clip = animations.find((candidate) => candidate.name === name)
    if (!clip) throw new Error(`fengxi: missing ${name} animation`)
    const playing = mixer.clipAction(clip)
    playing.reset().setEffectiveWeight(1).fadeIn(0.25).play()
    contacts.reset()
    if (action === 'walk' && root.current) {
      path.current.angle = Math.PI - root.current.rotation.y
      path.current.center.copy(root.current.position)
      path.current.center.x -= RADIUS * Math.cos(path.current.angle)
      path.current.center.z -= RADIUS * Math.sin(path.current.angle)
      previousPhase.current = 0
    }
    let timer: number | undefined
    if (action === 'special') {
      specialStart.current = elapsed.current
      timer = window.setTimeout(() => {
        const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(position).project(camera).x, -1, 1) * 0.8 : 0
        audio.fengxiCall(pan)
      }, 700)
    }
    return () => { playing.fadeOut(0.25); window.clearTimeout(timer) }
  }, [action, animations, camera, contacts, mixer, position])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    elapsed.current += dt
    mixer.update(dt)
    const group = root.current
    if (!group) return
    if (action === 'walk') {
      path.current.angle -= SPEED / RADIUS * dt
      const a = path.current.angle
      group.position.copy(path.current.center)
      group.position.x += Math.cos(a) * RADIUS
      group.position.z += Math.sin(a) * RADIUS
      group.rotation.y = Math.PI - a
      const clip = animations.find((candidate) => candidate.name === 'walk')!
      const phase = mixer.clipAction(clip).time / clip.duration % 1
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((previousPhase.current < beat && phase >= beat) || (beat === 0 && phase < previousPhase.current)) audio.footstep(0, 0.45)
      }
      previousPhase.current = phase
      contacts.update(group, phase, 0.68)
    }
    if (action === 'special' && elapsed.current - specialStart.current >= SPECIAL_SECONDS) setAction('idle')
    if (controls) {
      group.getWorldPosition(position)
      position.y = 0.6
      position.sub(controls.target).multiplyScalar(1 - Math.exp(-2 * dt))
      controls.target.add(position)
      camera.position.add(position)
      cameraShift.add(position)
    }
  })

  return <group ref={root} name="Fengxi" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={scene} />
  </group>
}
