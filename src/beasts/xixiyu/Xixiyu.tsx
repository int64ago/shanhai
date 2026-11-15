import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import {
  AnimationMixer,
  LoopOnce,
  LoopRepeat,
  MathUtils,
  Mesh,
  Object3D,
  Quaternion,
  SkinnedMesh,
  Vector3,
  type AnimationAction,
  type Group,
  type Material,
  type MeshStandardMaterial,
  type Skeleton,
} from 'three'
import { useApp, type BeastAction } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { FoxFire } from '../../systems/vfx/FoxFire'
import { createXixiyuWing, prepareXixiyuWingGeometry, WING_BONES, type XixiyuWing } from './wings'

const BODY_URL = '/models/xixiyu/body.glb'
const WING_URL = '/models/xixiyu/wing.glb'

// The high-resolution core has two native folded wings. Add four pairs
// around them for ten wings total; pair 2 is reserved for the native wings.
const PAIR_LAYOUT = [
  { scale: 0.80, sweep: -0.86, dihedral: 0.98, pitch: 0.66, phase: 0.0 },
  { scale: 1.04, sweep: 0.10, dihedral: 0.18, pitch: 0.58, phase: -0.62 },
  { scale: 0.96, sweep: 0.20, dihedral: 0.02, pitch: 0.0, phase: -1.24 },
  { scale: 0.94, sweep: 0.50, dihedral: -0.12, pitch: 0.46, phase: -1.86 },
  { scale: 0.80, sweep: 0.98, dihedral: -0.62, pitch: 0.28, phase: -2.48 },
] as const

interface WingMotionState {
  flapAmp: number
  flapSpeed: number
  sweepOffset: number
  dihedralOffset: number
  fire: number
}

const MOTION: Record<BeastAction, WingMotionState> = {
  idle: { flapAmp: 0.14, flapSpeed: 2.3, sweepOffset: 0.0, dihedralOffset: 0.0, fire: 0 },
  walk: { flapAmp: 0.30, flapSpeed: 5.0, sweepOffset: -0.02, dihedralOffset: 0.06, fire: 0 },
  special: { flapAmp: 0.42, flapSpeed: 6.8, sweepOffset: -0.12, dihedralOffset: 0.12, fire: 0.95 },
}

const REST_YAW = 0.16

const _v = new Vector3()

export function Xixiyu() {
  const body = useGLTF(BODY_URL)
  const wingGltf = useGLTF(WING_URL)
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const narrow = useThree((s) => s.size.width < 640)

  const root = useRef<Group>(null)
  const clock = useRef(0)
  const wingPhase = useRef(0)
  const specialStart = useRef(0)
  const walkSoundTimer = useRef(0)
  const motion = useRef<WingMotionState>({ ...MOTION.idle })
  const fire = useRef(MOTION.idle.fire)
  const target = useMemo(() => new Vector3(), [])

  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      const duration = clips[name]?.getClip().duration
      if (!duration || !Number.isFinite(duration) || duration <= 0) {
        throw new Error(`鳛鳛鱼缺少有效的 ${name} 动画`)
      }
    }

    const wingLMesh = wingGltf.scene.getObjectByName('wing_l') as Mesh | undefined
    const wingRMesh = wingGltf.scene.getObjectByName('wing_r') as Mesh | undefined
    if (!wingLMesh || !wingRMesh) {
      throw new Error('鳛鳛鱼翼模型缺少 wing_l 或 wing_r')
    }

    const leftPrep = prepareXixiyuWingGeometry(wingLMesh, 1)
    const rightPrep = prepareXixiyuWingGeometry(wingRMesh, -1)

    const wingSpecs: {
      boneName: string
      pair: number
      side: 1 | -1
      holder: Object3D
      wing: XixiyuWing
    }[] = []

    for (const pair of [0, 1, 3, 4]) {
      const layout = PAIR_LAYOUT[pair]
      for (const side of [1, -1] as const) {
        const suffix = side === 1 ? 'l' : 'r'
        const boneName = `wing_${pair}_${suffix}_attach`
        const prep = side === 1 ? leftPrep : rightPrep
        const wingSourceMat = (side === 1 ? wingLMesh : wingRMesh).material as MeshStandardMaterial
        const mat = createInkMaterial({
          map: wingSourceMat.map ?? null,
          tint: wingSourceMat.map ? '#ffffff' : `#${wingSourceMat.color.getHexString()}`,
          saturation: 0.88,
        })
        const wing = createXixiyuWing(prep.geometry, mat, prep.span, pair, side, layout.scale)
        const holder = new Object3D()
        holder.name = `xixiyu_wing_holder_${pair}_${suffix}`
        holder.add(wing.pivot)
        wingSpecs.push({ boneName, pair, side, holder, wing })
      }
    }

    const emitters: Object3D[] = []
    for (const spec of wingSpecs) {
      if (spec.pair === 0 || spec.pair === 2 || spec.pair === 4) {
        emitters.push(spec.wing.tip)
      }
    }

    return {
      scene,
      mixer,
      clips,
      wingSpecs,
      sharedWingGeos: [leftPrep.geometry, rightPrep.geometry],
      emitters,
      specialDuration: clips.special.getClip().duration,
    }
  }, [body, wingGltf])

  // Attach modular wings, apply gongbi ink materials and outlines inside useEffect (StrictMode safe).
  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const ownedMaterials: Material[] = []
    const outlines: Mesh[] = []

    rig.scene.traverse((node) => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      originals.set(node, node.material)
      const makeInk = (source: MeshStandardMaterial) => {
        const material = createInkMaterial({
          map: source.map ?? null,
          tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`,
          saturation: 0.88,
        })
        ownedMaterials.push(material)
        return material
      }
      node.material = Array.isArray(node.material)
        ? node.material.map((m) => makeInk(m as MeshStandardMaterial))
        : makeInk(node.material as MeshStandardMaterial)
    })

    for (const mesh of originals.keys()) {
      const outline = createOutline(mesh, 0.002)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }

    rig.scene.updateMatrixWorld(true)
    const sceneQInv = rig.scene.getWorldQuaternion(new Quaternion()).invert()
    const attached: { attach: Object3D; holder: Object3D }[] = []

    for (const spec of rig.wingSpecs) {
      const attach = rig.scene.getObjectByName(spec.boneName)
      if (!attach) throw new Error(`鳛鳛鱼缺少骨骼挂点: ${spec.boneName}`)
      const restQ = attach.getWorldQuaternion(new Quaternion()).premultiply(sceneQInv)
      const restS = attach.getWorldScale(new Vector3())
      spec.holder.quaternion.copy(restQ.invert())
      spec.holder.scale.set(1 / restS.x, 1 / restS.y, 1 / restS.z)

      const wingOutline = createOutline(spec.wing.mesh, 0.0022)
      spec.wing.pivot.add(wingOutline)
      outlines.push(wingOutline)
      ownedMaterials.push(spec.wing.mesh.material as Material)

      attach.add(spec.holder)
      attached.push({ attach, holder: spec.holder })
    }

    if (import.meta.env.DEV) console.info('[beast] ready xixiyu')

    return () => {
      rig.mixer.stopAllAction()
      for (const { attach, holder } of attached) attach.remove(holder)
      for (const outline of outlines) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
      }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of ownedMaterials) material.dispose()
      for (const geo of rig.sharedWingGeos) geo.dispose()
      const skeletons = new Set<Skeleton>()
      rig.scene.traverse((node) => {
        if (node instanceof SkinnedMesh) skeletons.add(node.skeleton)
      })
      for (const spec of rig.wingSpecs) skeletons.add(spec.wing.mesh.skeleton)
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action]
    clip.reset().setEffectiveWeight(1).fadeIn(0.25)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()

    let callTimer: number | undefined
    let flapTimer: number | undefined
    if (action === 'special') {
      specialStart.current = clock.current
      const pan = root.current
        ? MathUtils.clamp(root.current.getWorldPosition(_v).project(camera).x, -1, 1) * 0.75
        : 0
      callTimer = window.setTimeout(() => audio.qiqueCall(pan), 200)
      flapTimer = window.setTimeout(() => audio.wingFlutter(pan, 0.34), 480)
    }
    return () => {
      clip.fadeOut(0.25)
      clearTimeout(callTimer)
      clearTimeout(flapTimer)
    }
  }, [action, rig, camera])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    clock.current += dt
    const t = clock.current
    rig.mixer.update(dt)

    const g = root.current
    if (!g) return

    if (import.meta.env.DEV) g.userData.animationTime = rig.clips[action].time

    if (action === 'walk') {
      // Gentle figure-8 airborne/aquatic glide around origin
      const speed = 1.25
      g.position.x = MathUtils.damp(g.position.x, 0.24 * Math.sin(t * speed), 3.5, dt)
      g.position.z = MathUtils.damp(g.position.z, 0.14 * Math.sin(t * speed * 2.0), 3.5, dt)
      const vx = 0.24 * speed * Math.cos(t * speed)
      const vz = 0.28 * speed * Math.cos(t * speed * 2.0)
      const targetYaw = Math.atan2(vx, vz)
      const yawDelta = Math.atan2(Math.sin(targetYaw - g.rotation.y), Math.cos(targetYaw - g.rotation.y))
      g.rotation.y = MathUtils.damp(g.rotation.y, g.rotation.y + yawDelta, 3.5, dt)

      walkSoundTimer.current += dt
      if (walkSoundTimer.current > 0.65) {
        walkSoundTimer.current = 0
        audio.wingFlutter(MathUtils.clamp(g.position.x, -1, 1) * 0.6, 0.16)
      }
    } else {
      g.position.x = MathUtils.damp(g.position.x, 0, 3.0, dt)
      g.position.z = MathUtils.damp(g.position.z, 0, 3.0, dt)
      const yawDelta = Math.atan2(Math.sin(REST_YAW - g.rotation.y), Math.cos(REST_YAW - g.rotation.y))
      g.rotation.y = MathUtils.damp(g.rotation.y, g.rotation.y + yawDelta, 3.0, dt)
    }

    const m = motion.current
    const goal = MOTION[action]
    m.flapAmp = MathUtils.damp(m.flapAmp, goal.flapAmp, 3.2, dt)
    m.flapSpeed = MathUtils.damp(m.flapSpeed, goal.flapSpeed, 3.2, dt)
    m.sweepOffset = MathUtils.damp(m.sweepOffset, goal.sweepOffset, 3.2, dt)
    m.dihedralOffset = MathUtils.damp(m.dihedralOffset, goal.dihedralOffset, 3.2, dt)
    // Integrate frequency so action changes never jump the wing oscillation phase.
    wingPhase.current += m.flapSpeed * dt
    const phase = wingPhase.current

    // Fire-warding ember aura rises on special then fades as the wings quell it.
    let fireGoal = goal.fire
    if (action === 'special') {
      const elapsed = t - specialStart.current
      fireGoal = elapsed < 2.2 ? 0.95 : MathUtils.lerp(0.95, 0.04, Math.min(1, (elapsed - 2.2) / 1.8))
    }
    fire.current = MathUtils.damp(fire.current, fireGoal, 2.8, dt)

    // Drive the eight modular wings; the native folded pair follows the body rig.
    for (const { pair, side, wing } of rig.wingSpecs) {
      const layout = PAIR_LAYOUT[pair]
      const flap = m.flapAmp * Math.sin(phase + layout.phase)
      const sweep = layout.sweep + m.sweepOffset + 0.05 * Math.cos(phase + layout.phase)
      const dihedral = layout.dihedral + m.dihedralOffset + flap

      wing.pivot.rotation.order = 'YZX'
      wing.pivot.rotation.y = side * sweep
      wing.pivot.rotation.z = side * dihedral
      wing.pivot.rotation.x = layout.pitch + 0.08 * Math.cos(phase + layout.phase)

      for (let j = 0; j < WING_BONES; j++) {
        const k = (j + 1) / WING_BONES
        const wave = Math.sin(phase - j * 0.55 + layout.phase)
        wing.bones[j].rotation.z = side * (0.09 + m.flapAmp * 0.25) * wave * (0.35 + k * 0.65)
        wing.bones[j].rotation.y = -side * 0.05 * (0.2 + k)
      }
    }

    if (action === 'special' && rig.clips.special.time >= rig.specialDuration - 0.001) {
      setAction('idle')
    }

    if (controls) {
      g.getWorldPosition(target)
      target.y = narrow ? 0.58 : 0.46
      controls.target.lerp(target, 1 - Math.exp(-2.5 * dt))
    }
  })

  return (
    <>
      <group ref={root} name="xixiyu_root" rotation-y={REST_YAW}>
        <primitive object={rig.scene} dispose={null} />
      </group>
      <FoxFire
        emitters={rig.emitters}
        intensity={fire}
        coreColor="#f2c4a2"
        edgeColor="#b5442b"
      />
    </>
  )
}
