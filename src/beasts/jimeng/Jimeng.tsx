import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/jimeng/body.glb'
const RADIUS = 1
const SPEED = 0.08
const DURATIONS = { idle: 4, walk: 2.4, special: 4 } as const

export function Jimeng() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const root = useRef<Group>(null)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const camera = useThree(s => s.camera)
  const width = useThree(s => s.size.width)
  const cameraDelta = useMemo(() => new Vector3(), [])
  const cameraTarget = useMemo(() => new Vector3(), [])
  // Only the clip's local time restarts. This clock preserves the world orbit
  // across idle/special/walk switches and advances by the same dt as the mixer.
  const elapsedWalkSeconds = useRef(0)
  const previousPhase = useRef(0)
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const [name, seconds] of Object.entries(DURATIONS)) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || Math.abs(duration - seconds) > 0.0001) {
        throw new Error(`计蒙缺少符合原生骨架契约的 ${name} 动画`)
      }
    }
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    // Geometry and native textures remain shared with the GLTF cache. Only this
    // clone's materials, outlines and skeleton GPU resources belong to us.
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      originals.set(node, node.material)
      const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.65 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const mesh of originals.keys()) {
      const outline = createOutline(mesh, 0.0014)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready jimeng')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) {
        outline.removeFromParent()
        const material = outline.material as Material
        material.dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      const skeletons = new Set<SkinnedMesh['skeleton']>()
      rig.scene.traverse(node => { if (node instanceof SkinnedMesh) skeletons.add(node.skeleton) })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action]
    clip.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(0.3)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    if (action === 'walk') previousPhase.current = 0
    return () => { clip.fadeOut(0.3) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const group = root.current
    if (!group) return
    const dt = Math.min(rawDt, 0.05)
    rig.mixer.update(dt)
    if (action === 'walk') {
      elapsedWalkSeconds.current += dt
      const phase = rig.clips.walk.time / DURATIONS.walk % 1
      for (const beat of [0, 0.5]) {
        if ((previousPhase.current < beat && phase >= beat) || (beat === 0 && phase < previousPhase.current)) audio.footstep(0, 0.25)
      }
      previousPhase.current = phase
    }
    // The native clip already cancels this orbit's position AND orientation for
    // every vertex of each planted foot. Do not apply a second foot correction.
    const angle = Math.PI / 2 - SPEED / RADIUS * elapsedWalkSeconds.current
    group.position.set(RADIUS * Math.cos(angle), 0, RADIUS * Math.sin(angle))
    group.rotation.y = Math.PI - angle
    if (controls) {
      cameraTarget.copy(group.position)
      cameraTarget.y = width <= 640 ? 1.1 : 1.0
      cameraDelta.copy(controls.target)
      controls.target.lerp(cameraTarget, 1 - Math.exp(-3 * dt))
      cameraDelta.sub(controls.target)
      camera.position.sub(cameraDelta)
    }
    if (import.meta.env.DEV) {
      group.userData.animationTime = rig.clips[action].time
      group.userData.animationWeight = rig.clips[action].getEffectiveWeight()
      group.userData.elapsedWalkSeconds = elapsedWalkSeconds.current
      group.userData.worldAngle = angle
      group.userData.action = action
    }
    if (action === 'special' && rig.clips.special.time >= DURATIONS.special - 0.001) setAction('idle')
  })

  return <group ref={root} name="jimeng_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} dispose={null} />
  </group>
}
