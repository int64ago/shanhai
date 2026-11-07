import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { AnimationMixer, Color, MathUtils, Mesh, NormalBlending, Quaternion, Vector3, type Group, type MeshStandardMaterial, type ShaderMaterial } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createOutline } from '../../systems/ink/inkify'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { NOISE_GLSL } from '../../scene/noise.glsl'
import { createGroundContacts } from '../groundContacts'

/** 「有珠」的解释性淡染：圆晕只是写意，不增设体外珠角或宝石器官。 */
function PearlWash({ intensity }: { intensity: { current: number } }) {
  const plane = useRef<Mesh>(null)
  const material = useRef<ShaderMaterial>(null)
  const inverse = useMemo(() => new Quaternion(), [])
  const uniforms = useMemo(() => ({
    uTime: { value: 0 }, uIntensity: { value: 0 },
    uCore: { value: new Color('#d4ddd2') }, uEdge: { value: new Color('#578b8c') },
  }), [])
  useFrame(({ camera }, rawDt) => {
    if (plane.current?.parent) {
      plane.current.parent.getWorldQuaternion(inverse).invert()
      plane.current.quaternion.copy(inverse).multiply(camera.quaternion)
    }
    if (material.current) {
      material.current.uniforms.uTime.value += Math.min(rawDt, 0.05)
      material.current.uniforms.uIntensity.value = intensity.current
    }
  })
  return <mesh ref={plane} name="Tongtong_PearlWash" position={[0, 0.47, -0.13]} renderOrder={4}>
    <planeGeometry args={[0.78, 0.78]} />
    <shaderMaterial ref={material} uniforms={uniforms} transparent depthWrite={false} depthTest={false} blending={NormalBlending}
      vertexShader={/* glsl */ `
        varying vec2 vUv;
        void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
      `}
      fragmentShader={/* glsl */ `
        uniform float uTime, uIntensity;
        uniform vec3 uCore, uEdge;
        varying vec2 vUv;
        ${NOISE_GLSL}
        void main() {
          vec2 p = (vUv - 0.5) * 2.0;
          float grain = fbm(p * 5.0);
          float radius = length(p) + (grain - 0.5) * 0.065;
          float breath = 0.52 + 0.045 * sin(uTime * 2.2);
          float ring = 1.0 - smoothstep(0.015, 0.10, abs(radius - breath));
          float wash = 1.0 - smoothstep(0.15, 0.75, radius);
          float alpha = (wash * 0.16 + ring * 0.19) * uIntensity * (0.7 + grain * 0.3);
          if (alpha < 0.002) discard;
          gl_FragColor = vec4(mix(uCore, uEdge, ring * 0.72 + grain * 0.15), alpha);
          #include <colorspace_fragment>
        }
      `}
    />
  </mesh>
}

const RADIUS = 1.1
const SPEED = 0.3
const SPECIAL_SECONDS = 4.6

export function Tongtong() {
  // Use the actual cached scene. Every material/outline attachment is paired
  // with effect cleanup so StrictMode and beast switching cannot leave copies.
  const { scene, animations } = useGLTF('/models/tongtong/body.glb')
  const mixer = useMemo(() => new AnimationMixer(scene), [scene])
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const position = useMemo(() => new Vector3(), [])
  const path = useRef({ angle: Math.PI / 2, center: new Vector3() })
  const elapsed = useRef(0)
  const specialStart = useRef(0)
  const intensity = useRef(0)
  const previousPhase = useRef(0)
  const contacts = useMemo(() => createGroundContacts(scene, ['back_l', 'front_l', 'back_r', 'front_r']), [scene])

  useEffect(() => {
    const meshes: Mesh[] = []
    scene.traverse((object) => { if (object instanceof Mesh) meshes.push(object) })
    const resources = meshes.map((mesh) => {
      const original = mesh.material as MeshStandardMaterial
      const material = createInkMaterial({ map: original.map ?? null, saturation: 0.65 })
      const outline = createOutline(mesh, 0.003)
      mesh.material = material
      mesh.frustumCulled = false
      mesh.parent!.add(outline)
      return { mesh, original, material, outline }
    })
    scene.name = 'Tongtong_CachedScene'
    if (import.meta.env.DEV) console.info(`[beast] ready tongtong bodies=${meshes.length} outlines=${resources.length} appendages=0`)
    return () => {
      for (const { mesh, original, material, outline } of resources) {
        outline.removeFromParent()
        const outlineMaterial = outline.material as ShaderMaterial
        outlineMaterial.dispose()
        mesh.material = original
        material.dispose()
      }
      mixer.stopAllAction()
      if (import.meta.env.DEV) console.info('[tongtong] cleanup outlines=0 appendages=0')
    }
  }, [scene, mixer])

  useEffect(() => {
    const name = action === 'special' ? 'alert' : action
    const clip = animations.find((candidate) => candidate.name === name)
    if (!clip) throw new Error(`tongtong: missing ${name} animation`)
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
        audio.tongtongCall(pan)
      }, 320)
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
      // The baked straight gait supplies the pose; world targets compensate turning.
      group.rotation.y = Math.PI - a
      const clip = animations.find((candidate) => candidate.name === 'walk')!
      const phase = mixer.clipAction(clip).time / clip.duration % 1
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((previousPhase.current < beat && phase >= beat) || (beat === 0 && phase < previousPhase.current)) audio.footstep(0, 0.3)
      }
      previousPhase.current = phase
      contacts.update(group, phase, 0.66)
    }
    const specialTime = elapsed.current - specialStart.current
    if (action === 'special' && specialTime >= SPECIAL_SECONDS) setAction('idle')
    const envelope = action === 'special' ? Math.sin(Math.min(specialTime / SPECIAL_SECONDS, 1) * Math.PI) ** 2 : 0
    intensity.current = MathUtils.damp(intensity.current, envelope, 8, dt)
    if (controls) {
      group.getWorldPosition(position)
      position.y = 0.48
      controls.target.lerp(position, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="Tongtong" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={scene} />
    <PearlWash intensity={intensity} />
  </group>
}
