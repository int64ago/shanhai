import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, Mesh, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshBasicMaterial, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/kui/body.glb'
const RADIUS = 0.65, SPEED = 0.16, START_ANGLE = Math.PI / 2 + 1.2
const DURATIONS = { idle: 4, walk: 1.8, special: 4.8 } as const

// The native PBR remains embedded. In ink, retain its fine normal and roughness
// variation as a restrained contribution to the existing wash lighting.
function nativeInk(source: MeshStandardMaterial) {
  const material = createInkMaterial({ map: source.map, saturation: 0.68, wash2: { start: 0.53, end: 0.66, strength: 0.6 } })
  material.side = DoubleSide
  material.uniforms.uNativeNormal = { value: source.normalMap }
  material.uniforms.uHasNativeNormal = { value: source.normalMap ? 1 : 0 }
  material.uniforms.uNativeRoughness = { value: source.roughnessMap }
  material.uniforms.uHasNativeRoughness = { value: source.roughnessMap ? 1 : 0 }
  material.fragmentShader = material.fragmentShader.replace('uniform sampler2D uMap;', `
    uniform sampler2D uMap;
    uniform sampler2D uNativeNormal;
    uniform float uHasNativeNormal;
    uniform sampler2D uNativeRoughness;
    uniform float uHasNativeRoughness;
  `).replace('vec3 V = normalize(vViewDir);', `
    if (uHasNativeNormal > 0.5) {
      vec3 dx = mat3(viewMatrix) * dFdx(vWorld);
      vec3 dy = mat3(viewMatrix) * dFdy(vWorld);
      vec2 ux = dFdx(vUv), uy = dFdy(vUv);
      float det = ux.x * uy.y - ux.y * uy.x;
      if (abs(det) > 1e-10) {
        vec3 T = (dx * uy.y - dy * ux.y) / det;
        T = normalize(T - N * dot(N, T));
        vec3 B = normalize(cross(N, T)) * sign(det);
        vec3 detail = texture2D(uNativeNormal, vUv).xyz * 2.0 - 1.0;
        detail.xy *= 0.25;
        N = normalize(mat3(T, B, N) * detail);
      }
    }
    vec3 V = normalize(vViewDir);
  `).replace('float tone = clamp(', `
    float nativeRoughness = uHasNativeRoughness > 0.5 ? texture2D(uNativeRoughness, vUv).g : 0.8;
    float tone = clamp((nativeRoughness - 0.8) * 0.025 + `)
  return material
}

function thunder() {
  const ctx = audio.context
  if (!ctx) return
  const source = ctx.createBufferSource(), filter = ctx.createBiquadFilter(), gain = ctx.createGain()
  const buffer = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * 2.3), ctx.sampleRate)
  const data = buffer.getChannelData(0)
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1
  source.buffer = buffer; filter.type = 'lowpass'; filter.frequency.value = 360
  const t = ctx.currentTime
  gain.gain.setValueAtTime(0, t); gain.gain.linearRampToValueAtTime(0.48, t + 0.16); gain.gain.exponentialRampToValueAtTime(0.001, t + 2.3)
  source.connect(filter).connect(gain).connect(audio.sfx)
  source.onended = () => { source.disconnect(); filter.disconnect(); gain.disconnect() }
  source.start()
}

export function Kui() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action), setAction = useApp(s => s.setAction)
  const root = useRef<Group>(null), ripple = useRef<Mesh>(null), lightWash = useRef<Mesh>(null)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const width = useThree(s => s.size.width), camera = useThree(s => s.camera)
  const target = useMemo(() => new Vector3(), []), delta = useMemo(() => new Vector3(), [])
  const elapsedWalkSeconds = useRef(0), previousPhase = useRef(0)
  const rig = useMemo(() => {
    const scene = clone(body.scene), mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const [name, seconds] of Object.entries(DURATIONS)) {
      if (Math.abs((clips[name]?.getClip().duration ?? 0) - seconds) > 0.0001) throw new Error(`夔缺少 ${name} 原生骨架动画`)
    }
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>(), owned: Material[] = [], outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      originals.set(node, node.material); node.frustumCulled = false
      const material = nativeInk(node.material as MeshStandardMaterial)
      node.material = material; owned.push(material)
    })
    for (const mesh of originals.keys()) { const outline = createOutline(mesh, 0.0012); mesh.parent!.add(outline); outlines.push(outline) }
    if (import.meta.env.DEV) console.info('[beast] ready kui')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) { outline.removeFromParent(); (outline.material as Material).dispose() }
      for (const [mesh, material] of originals) mesh.material = material
      for (const material of owned) material.dispose()
      const skeletons = new Set<SkinnedMesh['skeleton']>()
      rig.scene.traverse(node => { if (node instanceof SkinnedMesh) skeletons.add(node.skeleton) })
      for (const skeleton of skeletons) skeleton.dispose()
    }
  }, [rig])

  useEffect(() => {
    const clip = rig.clips[action]
    clip.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(0.24)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'; clip.play()
    if (action === 'walk') previousPhase.current = 0
    const timer = action === 'special' ? window.setTimeout(thunder, 850) : undefined
    return () => { clip.fadeOut(0.24); window.clearTimeout(timer) }
  }, [action, rig])

  useFrame((_, rawDt) => {
    const group = root.current
    if (!group) return
    const dt = Math.min(rawDt, 0.05); rig.mixer.update(dt)
    if (action === 'walk') {
      elapsedWalkSeconds.current += dt
      const phase = rig.clips.walk.time / DURATIONS.walk % 1
      if (phase < previousPhase.current) audio.footstep(0, 0.42)
      previousPhase.current = phase
    }
    const angle = START_ANGLE - SPEED / RADIUS * elapsedWalkSeconds.current
    group.position.set(RADIUS * Math.cos(angle), 0, RADIUS * Math.sin(angle)); group.rotation.y = Math.PI - angle
    if (controls) {
      target.copy(group.position); target.y = width <= 640 ? 1.1 : 0.68
      delta.copy(controls.target); controls.target.lerp(target, 1 - Math.exp(-3 * dt)); delta.sub(controls.target); camera.position.sub(delta)
    }
    const specialTime = rig.clips.special.time
    const envelope = action === 'special' ? Math.min(1, specialTime / 0.8) * Math.min(1, Math.max(0, (4.8 - specialTime) / 1.1)) : 0
    if (ripple.current && lightWash.current) {
      const pulse = (specialTime % 1.6) / 1.6
      ripple.current.visible = lightWash.current.visible = envelope > 0
      ripple.current.scale.setScalar(0.7 + pulse * 1.5)
      ;(ripple.current.material as MeshBasicMaterial).opacity = envelope * (1 - pulse) * 0.42
      ;(lightWash.current.material as MeshBasicMaterial).opacity = envelope * (0.10 + 0.025 * Math.sin(specialTime * 3))
    }
    if (import.meta.env.DEV) Object.assign(group.userData, { action, animationTime: rig.clips[action].time, animationWeight: rig.clips[action].getEffectiveWeight(), elapsedWalkSeconds: elapsedWalkSeconds.current, worldAngle: angle, specialEnvelope: envelope })
    if (action === 'special' && specialTime >= DURATIONS.special - 0.001) setAction('idle')
  })

  return <group ref={root} name="kui_root" position={[RADIUS * Math.cos(START_ANGLE), 0, RADIUS * Math.sin(START_ANGLE)]} rotation-y={Math.PI - START_ANGLE}>
    <primitive object={rig.scene} dispose={null} />
    {/* 日月光与风雨的光晕、水波为设计推断；普通透明混合保持宣纸底色。 */}
    <mesh ref={ripple} name="kui_water_ripple" visible={false} position={[0, 0.022, -0.04]} rotation-x={-Math.PI / 2}>
      <ringGeometry args={[0.34, 0.354, 80]} /><meshBasicMaterial color="#627e83" transparent opacity={0} depthWrite={false} />
    </mesh>
    <mesh ref={lightWash} name="kui_moon_wash" visible={false} position={[0, 0.021, -0.04]} rotation-x={-Math.PI / 2}>
      <circleGeometry args={[0.32, 64]} /><meshBasicMaterial color="#f0dfaf" side={DoubleSide} transparent opacity={0} depthWrite={false} />
    </mesh>
  </group>
}
