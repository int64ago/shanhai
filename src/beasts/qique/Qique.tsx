import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Bone, Mesh, Quaternion, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial, type Skeleton } from 'three'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'
import { createQiqueContacts } from './groundContacts'

/** Native chicken silhouette, white head, continuous mouse feet and swept claws. */
export function Qique() {
  const body = useGLTF('/models/qique/body.glb')
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const time = useRef(0), start = useRef(0), phase = useRef(0)
  const previousAction = useRef(action), outgoingWalkUntil = useRef(0)
  const motion = useMemo(() => new Vector3(), [])
  const cameraShift = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const animated: { node: Bone; position: Vector3; quaternion: Quaternion; scale: Vector3 }[] = []
    scene.traverse((node) => {
      if (node instanceof Bone) animated.push({ node, position: node.position.clone(), quaternion: node.quaternion.clone(), scale: node.scale.clone() })
    })
    return { scene, animated, mixer: new AnimationMixer(scene), clips: {} as Record<string, AnimationAction>, mounted: false }
  }, [body])
  const contacts = useMemo(() => createQiqueContacts(rig.scene), [rig])

  useEffect(() => {
    // Setup runs again after StrictMode cleanup: uncacheRoot invalidates old
    // bindings, so every setup creates fresh mixer-owned actions.
    for (const clip of body.animations) rig.clips[clip.name] = rig.mixer.clipAction(clip)
    const meshes: Mesh[] = []
    rig.scene.traverse((node) => { if (node instanceof Mesh) meshes.push(node) })
    const resources = meshes.map((mesh) => {
      const original = mesh.material as MeshStandardMaterial
      const material = createInkMaterial({ map: original.map ?? null, saturation: 0.84 })
      const outline = createOutline(mesh, 0.0012)
      mesh.material = material; mesh.frustumCulled = false; mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    rig.mounted = true
    if (import.meta.env.DEV) console.info('[beast] ready qique')
    return () => {
      rig.mounted = false; rig.mixer.stopAllAction(); rig.mixer.uncacheRoot(rig.scene)
      for (const name of Object.keys(rig.clips)) delete rig.clips[name]
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent(); (outline.material as Material).dispose()
        mesh.material = original; material.dispose()
      }
      const skeletons = new Set<Skeleton>()
      for (const mesh of meshes) if (mesh instanceof SkinnedMesh) skeletons.add(mesh.skeleton)
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [body, rig])

  useEffect(() => () => {
    camera.position.sub(cameraShift); controls?.target.sub(cameraShift); cameraShift.set(0, 0, 0)
  }, [camera, controls, cameraShift])

  useEffect(() => {
    const clip = rig.clips[action === 'special' ? 'alert' : action]
    if (!clip) throw new Error(`qique: missing ${action} animation`)
    if (previousAction.current === 'walk' && action !== 'walk') outgoingWalkUntil.current = time.current + 0.18
    previousAction.current = action
    // Preserve the outgoing rendered pose and stance before starting the blend.
    if (root.current) contacts.capture(root.current)
    clip.reset().setEffectiveWeight(1).fadeIn(0.18).play()
    if (action === 'walk') {
      // An already lifted foot enters the incoming swing, instead of being
      // declared planted at walk phase zero while it is still in the air.
      const planted = contacts.planted()
      clip.time = !planted[0] ? 1.2 : !planted[1] ? 0.4 : 0
      contacts.beginWalk(clip.time / 1.6)
    }
    start.current = time.current
    const timer = action === 'special' ? window.setTimeout(() => audio.qiqueCall(), 650) : undefined
    return () => { clip.fadeOut(0.18); clearTimeout(timer) }
  }, [action, rig, contacts])

  useFrame((_, rawDt) => {
    if (!rig.mounted) return
    const dt = Math.min(rawDt, 0.05); time.current += dt
    // PropertyMixer skips unchanged values, including dt=0 and constant foot
    // tracks. Restore its previous animation result before evaluating again;
    // otherwise procedural IK can accumulate on the same rendered pose.
    for (const pose of rig.animated) {
      pose.node.position.copy(pose.position); pose.node.quaternion.copy(pose.quaternion); pose.node.scale.copy(pose.scale)
    }
    rig.mixer.update(dt)
    for (const pose of rig.animated) {
      pose.position.copy(pose.node.position); pose.quaternion.copy(pose.node.quaternion); pose.scale.copy(pose.node.scale)
    }
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      const speed = 0.10 * Math.min(1, (time.current - start.current) / 1.6)
      motion.set(Math.sin(g.rotation.y), 0, Math.cos(g.rotation.y)).multiplyScalar(speed * dt)
      g.position.add(motion); camera.position.add(motion); cameraShift.add(motion); controls?.target.add(motion)
      const p = rig.clips.walk.time / 1.6 % 1
      for (const beat of [0, 0.5]) if ((phase.current < beat && p >= beat) || (beat === 0 && p < phase.current)) audio.footstep(0, 0.24)
      phase.current = p
    }
    const walking = action === 'walk' || time.current < outgoingWalkUntil.current
    const p = rig.clips.walk.time / 1.6 % 1, phases = [p, (p + 0.5) % 1]
    const displayTime = action === 'special' ? rig.clips.alert.time : 0
    const displayingLeft = displayTime > 0.95 && displayTime < 2.8
    const support = walking ? phases.map((v) => v < 0.65) : [!displayingLeft, true]
    const swing = walking ? phases.map((v) => (v - 0.65) / 0.35) : [(displayTime - 0.95) / 1.85, 0]
    const planted = contacts.update(g, support, swing, dt)
    if (import.meta.env.DEV) { g.userData.walkPhase = p; g.userData.walkingContact = walking; g.userData.planted = planted; g.userData.contactDebug = contacts.debug() }
    if (action === 'special' && time.current - start.current > 4.2) setAction('idle')
    if (controls) { target.copy(g.position); target.y = 0.52; controls.target.lerp(target, 1 - Math.exp(-2 * dt)) }
  })
  return <group ref={root} name="qique_root" position={[0, 0, 0.85]} rotation-y={0.7}>
    <primitive object={rig.scene} name="qique_scene" dispose={null} />
  </group>
}
