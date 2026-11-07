import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, Bone, Box3, Float32BufferAttribute, Group, MathUtils, Mesh, MeshStandardMaterial, Object3D, Quaternion, Skeleton, SkinnedMesh, Uint16BufferAttribute, Vector3, type AnimationAction } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createOutline, inkify } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'

const SEGMENTS = 24
const SECONDS = 4.6
const X = new Vector3(1, 0, 0)

/** One continuous HIGH tail, extended offline to 2.4 nose-to-rump lengths. */
function makeTail(source: Mesh) {
  const geometry = source.geometry.clone()
  // Meshopt dequantization lives on the source node. Expand normalized integer
  // attributes before baking that matrix, or writes clamp the long tail to ±1.
  for (const name of ['position', 'normal']) {
    const attribute = geometry.getAttribute(name)
    const values = new Float32Array(attribute.count * 3)
    for (let i = 0; i < attribute.count; i++) values.set([attribute.getX(i), attribute.getY(i), attribute.getZ(i)], i * 3)
    geometry.setAttribute(name, new Float32BufferAttribute(values, 3))
  }
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
  pivot.quaternion.setFromUnitVectors(X, new Vector3(0, 0.045, -1).normalize())
  pivot.add(mesh, createOutline(mesh, 0.0025))
  return { pivot, mesh, bones, length }
}

export function Zouwu() {
  const body = useGLTF('/models/zouwu/body.glb')
  const tail = useGLTF('/models/zouwu/tail.glb')
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3; update: () => void } | null
  const root = useRef<Group>(null)
  const time = useRef(0)
  const since = useRef(0)
  const walk = useRef({ angle: 0, phase: 0 })
  const follow = useMemo(() => new Vector3(), [])
  const rig = useMemo(() => {
    const scene = body.scene
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    scene.updateMatrixWorld(true)
    const attach = scene.getObjectByName('tail_attach')
    if (!attach) throw new Error('zouwu: missing tail root')
    tail.scene.updateMatrixWorld(true)
    let source: Mesh | undefined
    tail.scene.traverse((o) => { if (!source && o instanceof Mesh) source = o })
    if (!source) throw new Error('zouwu: missing HIGH tail')
    const chain = makeTail(source)
    const holder = new Object3D()
    holder.name = 'zouwu_tail_holder'
    // The cancellation excludes the rotating outer beast group.
    holder.quaternion.copy(attach.getWorldQuaternion(new Quaternion()).premultiply(scene.getWorldQuaternion(new Quaternion()).invert()).invert())
    holder.add(chain.pivot)
    return { scene, mixer, clips, attach, holder, chain }
  }, [body, tail])

  useEffect(() => {
    // All cached-scene additions, including outlines, happen in an effect.
    inkify(rig.scene, { saturation: 0.88, outline: 0.004 })
    rig.scene.traverse((o) => { if (o instanceof Mesh) o.frustumCulled = false })
    rig.attach.add(rig.holder)
    if (import.meta.env.DEV) console.info('[beast] ready zouwu')
    return () => { rig.attach.remove(rig.holder); rig.mixer.stopAllAction() }
  }, [rig])

  useEffect(() => {
    if (!controls) return
    const previousPosition = camera.position.clone()
    const previousTarget = controls.target.clone()
    camera.position.set(3.1, 1.65, 6.5)
    controls.target.set(-0.25, 0.48, 0.6)
    controls.update()
    return () => {
      camera.position.copy(previousPosition)
      controls.target.copy(previousTarget)
      controls.update()
    }
  }, [camera, controls])

  useEffect(() => {
    const name = action === 'special' ? 'alert' : action
    const clip = rig.clips[name]
    if (!clip) throw new Error(`zouwu: missing ${name}`)
    clip.reset().setEffectiveWeight(1).fadeIn(0.2).play()
    since.current = time.current
    let timer: number | undefined
    if (action === 'special') timer = window.setTimeout(() => audio.zouwuCall(), 800)
    return () => { clip.fadeOut(0.2); clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    time.current += dt
    const t = time.current
    const g = root.current
    if (!g) return
    rig.mixer.update(dt)
    if (action === 'walk') {
      // A broad, slow arc matches the offline stance displacement (0.18/s).
      walk.current.angle += 0.18 / 1.8 * dt
      const a = walk.current.angle
      g.position.set(0.55 + 1.8 * Math.sin(a), 0, 0.6 + 1.8 * (Math.cos(a) - 1))
      g.rotation.y = Math.PI / 2 + a
      const phase = rig.clips.walk.time / 1.6 % 1
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((walk.current.phase < beat && phase >= beat) || (beat === 0 && phase < walk.current.phase)) audio.footstep(0, 0.35)
      }
      walk.current.phase = phase
    }
    if (controls) {
      follow.set(g.position.x - Math.sin(g.rotation.y) * 0.8, 0.48, g.position.z - Math.cos(g.rotation.y) * 0.8)
      follow.sub(controls.target).multiplyScalar(1 - Math.exp(-2 * dt))
      controls.target.add(follow)
      camera.position.add(follow)
    }
    const s = t - since.current
    if (action === 'special' && s > SECONDS) setAction('idle')
    // A low S curve preserves the visible body. Travelling curvature lags
    // progressively behind the rump; the bound sends a stronger wave down it.
    const burst = action === 'special' ? Math.exp(-Math.pow((s - 2.05) / 0.72, 2)) : 0
    for (let i = 0; i <= SEGMENTS; i++) {
      const k = i / SEGMENTS
      const lag = i * 0.21
      const speed = action === 'walk' ? 2.4 : 1.05
      rig.chain.bones[i].rotation.y = 0.11 * Math.sin(k * Math.PI * 2 - 0.4) + (0.02 + k * 0.045 + burst * 0.055) * Math.sin(t * speed - lag)
      rig.chain.bones[i].rotation.z = 0.02 * Math.sin(k * Math.PI * 2) + (0.01 + burst * 0.025) * Math.sin(t * 1.3 - lag)
    }
  })

  return <group ref={root} position={[0.55, 0, 0.6]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} />
  </group>
}
