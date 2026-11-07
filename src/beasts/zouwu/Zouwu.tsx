import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Bone, Box3, Float32BufferAttribute, Group, LoopOnce, LoopRepeat, MathUtils, Mesh, MeshStandardMaterial, Object3D, Quaternion, Skeleton, SkinnedMesh, Uint16BufferAttribute, Vector3, type AnimationAction, type Material } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createPawPlants, stabilizePaws } from './paws'

const SEGMENTS = 36
const SECONDS = 4.6
const RADIUS = 1.8
const SPEED = 0.18
const X = new Vector3(1, 0, 0)

/** Locally rebuilt round/tapered surface, with four rings per flexible joint. */
function makeTail(source: Mesh) {
  const geometry = source.geometry.clone()
  // Meshopt's integer attributes must be expanded before baking node transforms.
  for (const name of ['position', 'normal']) {
    const attribute = geometry.getAttribute(name)
    const values = new Float32Array(attribute.count * 3)
    for (let i = 0; i < attribute.count; i++) values.set([attribute.getX(i), attribute.getY(i), attribute.getZ(i)], i * 3)
    geometry.setAttribute(name, new Float32BufferAttribute(values, 3))
  }
  // applyMatrix4 uses the inverse transpose for the authored analytic normals.
  geometry.applyMatrix4(source.matrixWorld)
  const position = geometry.getAttribute('position')
  const bounds = new Box3().setFromBufferAttribute(position as never)
  const length = bounds.max.x - bounds.min.x
  geometry.translate(-bounds.min.x, -(bounds.min.y + bounds.max.y) / 2, -(bounds.min.z + bounds.max.z) / 2)
  const indices = new Uint16Array(position.count * 4)
  const weights = new Float32Array(position.count * 4)
  for (let i = 0; i < position.count; i++) {
    const t = MathUtils.clamp(position.getX(i) / length * SEGMENTS, 0, SEGMENTS)
    const a = Math.floor(t)
    indices.set([a, Math.min(a + 1, SEGMENTS), 0, 0], i * 4)
    weights.set([1 - (t - a), t - a, 0, 0], i * 4)
  }
  geometry.setAttribute('skinIndex', new Uint16BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new Float32BufferAttribute(weights, 4))
  const material = createInkMaterial({ map: (source.material as MeshStandardMaterial).map, saturation: 0.86 })
  const mesh = new SkinnedMesh(geometry, material)
  mesh.name = 'zouwu_single_tail'
  mesh.frustumCulled = false
  const bones: Bone[] = []
  for (let i = 0; i <= SEGMENTS; i++) {
    const bone = new Bone()
    bone.name = `zouwu_tail_${i}`
    if (i > 0) { bone.position.x = length / SEGMENTS; bones[i - 1].add(bone) }
    bones.push(bone)
  }
  mesh.add(bones[0])
  mesh.bind(new Skeleton(bones))
  const pivot = new Object3D()
  pivot.quaternion.setFromUnitVectors(X, new Vector3(0, 0, -1))
  const outline = createOutline(mesh, 0.0018)
  pivot.add(mesh, outline)
  return { pivot, mesh, bones, length, outline, phase: 0, speed: 1, burst: 0,
    direction: new Vector3(), previous: new Quaternion(), absolute: new Quaternion() }
}
type Tail = ReturnType<typeof makeTail>

export function Zouwu() {
  const body = useGLTF('/models/zouwu/body.glb')
  const tail = useGLTF('/models/zouwu/tail.glb')
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3; update: () => void } | null
  const root = useRef<Group>(null)
  const walk = useRef({ angle: 0, phase: 0 })
  const follow = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    // Cached useGLTF objects remain untouched. GPU resources are made in the
    // effect so StrictMode's discarded memo cannot allocate orphaned materials.
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    const attach = scene.getObjectByName('tail_attach')
    if (!attach) throw new Error('zouwu: missing tail root')
    return { scene, mixer, clips, attach, plants: createPawPlants(scene), chain: null as Tail | null }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse((node) => {
      if (!(node instanceof Mesh)) return
      originals.set(node, node.material)
      node.frustumCulled = false
      const material = createInkMaterial({ map: (node.material as MeshStandardMaterial).map, saturation: 0.88 })
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const outline = createOutline(node, 0.004)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    rig.scene.updateMatrixWorld(true)
    tail.scene.updateMatrixWorld(true)
    let source: Mesh | undefined
    tail.scene.traverse((o) => { if (!source && o instanceof Mesh) source = o })
    if (!source) throw new Error('zouwu: missing local tail')
    const chain = makeTail(source)
    const holder = new Object3D()
    holder.name = 'zouwu_tail_holder'
    holder.quaternion.copy(rig.attach.getWorldQuaternion(new Quaternion()).premultiply(rig.scene.getWorldQuaternion(new Quaternion()).invert()).invert())
    holder.add(chain.pivot)
    rig.attach.add(holder)
    rig.chain = chain
    for (const paw of rig.plants.paws) paw.planted = false
    if (import.meta.env.DEV) console.info('[beast] ready zouwu')
    return () => {
      rig.chain = null
      holder.removeFromParent()
      rig.mixer.stopAllAction()
      chain.mesh.skeleton.dispose()
      chain.mesh.geometry.dispose()
      ;(chain.mesh.material as Material).dispose()
      ;(chain.outline.material as Material).dispose()
      for (const outline of outlines) { outline.removeFromParent(); (outline.material as Material).dispose() }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      const skeletons = new Set<Skeleton>()
      rig.scene.traverse(node => { if (node instanceof SkinnedMesh) skeletons.add(node.skeleton) })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig, tail])

  useEffect(() => {
    if (!controls) return
    const previousPosition = camera.position.clone()
    const previousTarget = controls.target.clone()
    camera.position.set(3.1, 1.65, 6.5)
    controls.target.set(-0.25, 0.48, 0.6)
    controls.update()
    return () => { camera.position.copy(previousPosition); controls.target.copy(previousTarget); controls.update() }
  }, [camera, controls])

  useEffect(() => {
    const name = action === 'special' ? 'alert' : action
    const clip = rig.clips[name]
    if (!clip) throw new Error(`zouwu: missing ${name}`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.2)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    let timer: number | undefined
    if (action === 'special') timer = window.setTimeout(() => audio.zouwuCall(), 800)
    return () => { clip.fadeOut(0.2); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const g = root.current
    const chain = rig.chain
    if (!g || !chain) return
    rig.mixer.update(dt)
    if (import.meta.env.DEV) g.userData.animationTime = rig.clips[action === 'special' ? 'alert' : action].time
    if (action === 'walk') {
      walk.current.angle += SPEED / RADIUS * dt
      const a = walk.current.angle
      g.position.set(0.55 + RADIUS * Math.sin(a), 0, 0.6 + RADIUS * (Math.cos(a) - 1))
      g.rotation.y = Math.PI / 2 + a
      const phase = rig.clips.walk.time / 1.6 % 1
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((walk.current.phase < beat && phase >= beat) || (beat === 0 && phase < walk.current.phase)) audio.footstep(0, 0.35)
      }
      walk.current.phase = phase
    }
    stabilizePaws(rig.plants, g)
    if (controls) {
      follow.set(g.position.x - Math.sin(g.rotation.y) * 0.5, 0.42, g.position.z - Math.cos(g.rotation.y) * 0.5)
      follow.sub(controls.target).multiplyScalar(1 - Math.exp(-2 * dt))
      controls.target.add(follow)
      camera.position.add(follow)
    }
    const s = rig.clips.alert.time
    if (action === 'special' && s >= SECONDS - 0.001) setAction('idle')
    // Prescribe absolute tangents, then convert to parent-local quaternions.
    // This gives a weight-bearing root, a low gravity arc, and a soft upturned
    // tip without accumulating dozens of per-joint oscillations into a rope.
    chain.speed = MathUtils.damp(chain.speed, action === 'walk' ? 1.8 : 1, 4, dt)
    chain.phase += dt * chain.speed
    chain.burst = MathUtils.damp(chain.burst, action === 'special' ? Math.exp(-Math.pow((s - 2.1) / 0.55, 2)) : 0, 6, dt)
    chain.previous.identity()
    for (let i = 0; i <= SEGMENTS; i++) {
      const k = i / SEGMENTS
      const lag = k * 2.8
      const pitch = 0.04 - 0.32 * Math.sin(k * Math.PI) + 1.25 * MathUtils.smoothstep(k, 0.52, 1)
        + (0.025 + 0.11 * k) * Math.sin(chain.phase - lag)
        - chain.burst * 0.09 * Math.sin(k * Math.PI)
      const yaw = 0.1 * Math.sin(k * Math.PI) + (0.025 + 0.12 * k) * Math.sin(chain.phase * 0.83 - lag)
        + chain.burst * 0.12 * Math.sin(lag)
      chain.direction.set(Math.cos(pitch) * Math.cos(yaw), Math.sin(pitch), Math.cos(pitch) * Math.sin(yaw))
      chain.absolute.setFromUnitVectors(X, chain.direction)
      chain.bones[i].quaternion.copy(chain.previous).invert().multiply(chain.absolute)
      chain.previous.copy(chain.absolute)
    }
  })

  return <group ref={root} name="zouwu_root" position={[0.55, 0, 0.6]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} />
  </group>
}
