import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, MathUtils, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { useApp } from '../../app/store'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { audio } from '../../systems/audio/AudioEngine'
import { FoxFire } from '../../systems/vfx/FoxFire'

const BODY_URL = '/models/bifang/body.glb'
const WALK_SPEED = 0.14 // Matches the baked single-foot support velocity.
const WALK_SECONDS = 1.4
const DUTY = 0.38
const FIRE = { idle: 0.10, walk: 0.18, special: 1.35 }

export function Bifang() {
  const body = useGLTF(BODY_URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const camera = useThree(s => s.camera)
  const narrow = useThree(s => s.size.width < 600)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const clock = useRef(0)
  const start = useRef(0)
  const phase = useRef(0)
  const fire = useRef(FIRE.idle)
  const motion = useMemo(() => new Vector3(), [])
  const cameraShift = useMemo(() => new Vector3(), [])
  const target = useMemo(() => new Vector3(), [])
  const panVector = useMemo(() => new Vector3(), [])

  const rig = useMemo(() => {
    // Own the bones and animation state while sharing immutable cached assets.
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    const emitters = ['wing_l_attach', 'wing_r_attach', 'beak_attach', 'tail_attach'].map(name => {
      const node = scene.getObjectByName(name)
      if (!node) throw new Error(`bifang: missing ${name}`)
      return node
    })
    return { scene, mixer, clips, emitters }
  }, [body])

  useEffect(() => {
    const meshes: Mesh[] = []
    rig.scene.traverse(node => { if (node instanceof Mesh && !node.userData.inkOutline) meshes.push(node) })
    const resources = meshes.map(mesh => {
      const original = mesh.material as MeshStandardMaterial
      const material = createInkMaterial({ map: original.map ?? null, saturation: 0.88,
        tint: original.map ? undefined : `#${original.color.getHexString()}` })
      const outline = createOutline(mesh, 0.0025)
      mesh.material = material
      mesh.frustumCulled = false
      mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    if (import.meta.env.DEV) console.info('[beast] ready bifang')
    return () => {
      rig.mixer.stopAllAction()
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
        mesh.material = original
        material.dispose()
      }
      // Outlines share these owned skeletons; dispose each once after removal.
      // Cached geometry, source materials and their textures stay reusable.
      const skeletons = new Set<SkinnedMesh['skeleton']>()
      rig.scene.traverse(node => { if (node instanceof SkinnedMesh) skeletons.add(node.skeleton) })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig])

  useEffect(() => () => {
    camera.position.sub(cameraShift)
    controls?.target.sub(cameraShift)
    cameraShift.set(0, 0, 0)
  }, [camera, controls, cameraShift])

  useEffect(() => {
    const clip = rig.clips[action]
    if (!clip) throw new Error(`bifang: missing ${action} animation`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.18).play()
    start.current = clock.current
    phase.current = 0
    // A cancelled display or unmount must cancel its pending call as well.
    const timer = action === 'special' ? window.setTimeout(() => audio.bifangCall(), 900) : undefined
    return () => { clip.fadeOut(0.18); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    clock.current += dt
    rig.mixer.update(dt)
    const g = root.current
    if (!g) return
    if (action === 'walk') {
      // Fixed heading preserves both world-space sole position and toe yaw.
      motion.set(Math.sin(g.rotation.y), 0, Math.cos(g.rotation.y)).multiplyScalar(WALK_SPEED * dt)
      g.position.add(motion)
      camera.position.add(motion)
      cameraShift.add(motion)
      controls?.target.add(motion)
      const p = rig.clips.walk.time / WALK_SECONDS % 1
      g.getWorldPosition(panVector).project(camera)
      const pan = MathUtils.clamp(panVector.x, -1, 1) * 0.8
      if (p < phase.current) audio.footstep(pan, 0.40)
      if (phase.current < DUTY && p >= DUTY) audio.wingFlutter(pan, 0.30)
      phase.current = p
    }
    if (action === 'special' && clock.current - start.current > 4.8) setAction('idle')
    fire.current = MathUtils.damp(fire.current, FIRE[action], 2.5, dt)
    if (controls) {
      // Keep the tall head below the portrait text card.
      target.copy(g.position); target.y = narrow ? 1.05 : 0.76
      controls.target.lerp(target, 1 - Math.exp(-2 * dt))
    }
  })

  return <>
    <group ref={root} position={[0, 0, 0.55]} rotation-y={1.25}>
      <primitive object={rig.scene} name="bifang_scene" dispose={null} />
    </group>
    <FoxFire emitters={rig.emitters} intensity={fire} coreColor="#d98a62" edgeColor="#9e3b2a" />
  </>
}

useGLTF.preload(BODY_URL)
