import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, DoubleSide, LoopOnce, LoopRepeat, MathUtils, Mesh, NormalBlending, SkinnedMesh, Vector3, type AnimationAction, type Group, type Material, type MeshStandardMaterial, type ShaderMaterial } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/xuangui/body.glb'
// Exact inverse circular stance targets are baked by rig_xuangui.py.
const RADIUS = 0.85
const SPEED = 0.065
const SPECIAL_SECONDS = 4.8

export function Xuangui() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const camera = useThree(s => s.camera)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const angle = useRef(Math.PI / 2)
  const phase = useRef(0)
  const point = useMemo(() => new Vector3(), [])
  const water = useMemo(() => ({ uTime: { value: 0 }, uDisplay: { value: 0 } }), [])
  const waterMaterial = useRef<ShaderMaterial>(null)
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!clips[name]) throw new Error(`旋龟缺少 ${name} 动画`)
    }
    return { scene, mixer, clips }
  }, [body])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      originals.set(node, node.material)
      const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.72 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const mesh of originals.keys()) {
      const outline = createOutline(mesh, mesh.name.includes('body') ? 0.0018 : 0.001)
      mesh.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready xuangui')
    return () => {
      rig.mixer.stopAllAction()
      for (const outline of outlines) {
        outline.removeFromParent()
        ;(outline.material as Material).dispose()
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
    clip.reset().setEffectiveWeight(1).fadeIn(0.32)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    let timer: number | undefined
    if (action === 'special') {
      const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
      timer = window.setTimeout(() => audio.woodSplit(pan), 700)
    }
    return () => { clip.fadeOut(0.32); clearTimeout(timer) }
  }, [action, rig, camera, point])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const group = root.current
    if (!group) return
    rig.mixer.update(dt)
    if (import.meta.env.DEV) group.userData.animationTime = rig.clips[action].time
    if (action === 'walk') {
      angle.current -= SPEED / RADIUS * dt
      group.position.set(Math.cos(angle.current) * RADIUS, 0, Math.sin(angle.current) * RADIUS)
      group.rotation.y = Math.PI - angle.current
      const current = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      for (const beat of [0, 0.25, 0.5, 0.75]) {
        if ((phase.current < beat && current >= beat) || (beat === 0 && current < phase.current)) audio.footstep(0, 0.18)
      }
      phase.current = current
    }
    const specialTime = rig.clips.special.time
    const display = action === 'special' ? Math.sin(Math.min(1, specialTime / SPECIAL_SECONDS) * Math.PI) : 0
    if (waterMaterial.current) {
      const uniforms = waterMaterial.current.uniforms
      uniforms.uTime.value += dt
      uniforms.uDisplay.value = MathUtils.damp(uniforms.uDisplay.value, display, 8, dt)
    }
    if (action === 'special' && specialTime >= SPECIAL_SECONDS - 0.001) setAction('idle')
    if (controls) {
      group.getWorldPosition(point)
      point.y = 0.46
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="xuangui_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} />
    <mesh name="xuangui_water" rotation-x={-Math.PI / 2} position-y={0.012} renderOrder={2}>
      <planeGeometry args={[3.2, 3.2]} />
      <shaderMaterial ref={waterMaterial} uniforms={water} transparent depthWrite={false} blending={NormalBlending}
        vertexShader={`varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`}
        fragmentShader={`
          uniform float uTime; uniform float uDisplay; varying vec2 vUv;
          void main() {
            vec2 p = (vUv - 0.5) * 3.2;
            float d = length(p * vec2(1.0, 0.82));
            float wash = 0.0;
            for (int i = 0; i < 3; i++) {
              float life = fract(uTime * 0.25 + float(i) / 3.0);
              float ring = abs(d - 0.35 - life * 1.05);
              wash += (1.0 - smoothstep(0.008, 0.042, ring)) * sin(life * 3.14159265);
            }
            float grain = 0.84 + 0.16 * sin(p.x * 121.0 + sin(p.y * 103.0));
            float alpha = wash * grain * uDisplay * 0.25;
            if (alpha < 0.002) discard;
            gl_FragColor = vec4(0.31, 0.46, 0.46, alpha);
            #include <colorspace_fragment>
          }
        `} />
    </mesh>
  </group>
}

useGLTF.preload(URL)
