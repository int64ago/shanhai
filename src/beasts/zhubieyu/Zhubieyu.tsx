import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js'
import { AnimationMixer, Color, DoubleSide, LoopOnce, LoopRepeat, MathUtils, Mesh, SkinnedMesh, Vector3, type ShaderMaterial, type AnimationAction, type Group, type Material, type MeshStandardMaterial } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

const URL = '/models/zhubieyu/body.glb'
// Inverse circular sole trajectories in rig_zhubieyu.py use these same values.
const RADIUS = 1
const SPEED = 0.10

export function Zhubieyu() {
  const body = useGLTF(URL)
  const action = useApp(s => s.action)
  const setAction = useApp(s => s.setAction)
  const camera = useThree(s => s.camera)
  const controls = useThree(s => s.controls) as unknown as { target: Vector3 } | null
  const root = useRef<Group>(null)
  const angle = useRef(Math.PI / 2)
  const point = useMemo(() => new Vector3(), [])
  const previousPhase = useRef(0)
  const rig = useMemo(() => {
    const scene = clone(body.scene)
    const mixer = new AnimationMixer(scene)
    const clips: Record<string, AnimationAction> = {}
    for (const clip of body.animations) clips[clip.name] = mixer.clipAction(clip)
    for (const name of ['idle', 'walk', 'special']) {
      if (!clips[name]) throw new Error(`珠蟞鱼缺少 ${name} 动画`)
    }
    return { scene, mixer, clips }
  }, [body])
  const ripple = useRef<ShaderMaterial>(null)
  const rippleUniforms = useMemo(() => ({
    time: { value: 0 }, strength: { value: 0 }, color: { value: new Color('#527f7b') },
  }), [])

  useEffect(() => {
    const originals = new Map<Mesh, Material | Material[]>()
    const owned: Material[] = []
    const outlines: Mesh[] = []
    rig.scene.traverse(node => {
      if (!(node instanceof Mesh)) return
      originals.set(node, node.material)
      node.frustumCulled = false
      const source = node.material as MeshStandardMaterial
      const material = createInkMaterial({ map: source.map ?? null, tint: source.map ? '#ffffff' : `#${source.color.getHexString()}`, saturation: 0.76 })
      material.side = DoubleSide
      node.material = material
      owned.push(material)
    })
    for (const node of originals.keys()) {
      const fine = /eye|pupil|glint|pearl/.test(node.name)
      const outline = createOutline(node, fine ? 0.0008 : 0.0018)
      node.parent!.add(outline)
      outlines.push(outline)
    }
    if (import.meta.env.DEV) console.info('[beast] ready zhubieyu')
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
    clip.reset().setEffectiveWeight(1).fadeIn(0.3)
    clip.setLoop(action === 'special' ? LoopOnce : LoopRepeat, action === 'special' ? 1 : Infinity)
    clip.clampWhenFinished = action === 'special'
    clip.play()
    let timer: number | undefined
    let stopSound: (() => void) | undefined
    if (action === 'special') {
      timer = window.setTimeout(() => {
        const pan = root.current ? MathUtils.clamp(root.current.getWorldPosition(point).project(camera).x, -1, 1) * 0.8 : 0
        stopSound = audio.zhubieyuCall(pan)
      }, 200)
    }
    return () => { clip.fadeOut(0.3); clearTimeout(timer); stopSound?.() }
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
      const phase = rig.clips.walk.time / rig.clips.walk.getClip().duration % 1
      if (phase < previousPhase.current || (previousPhase.current < 0.5 && phase >= 0.5)) audio.footstep(0, 0.13)
      previousPhase.current = phase
    }
    const specialTime = rig.clips.special.time
    if (action === 'special' && specialTime >= 4.8 - 0.001) setAction('idle')
    const material = ripple.current
    if (material) {
      material.uniforms.time.value += dt
      const strength = action === 'special' ? Math.sin(Math.PI * Math.min(1, specialTime / 4.8)) : action === 'walk' ? 0.18 : 0.04
      material.uniforms.strength.value = MathUtils.damp(material.uniforms.strength.value, strength, 4, dt)
    }
    if (controls) {
      group.getWorldPosition(point)
      point.y = 0.46
      controls.target.lerp(point, 1 - Math.exp(-2 * dt))
    }
  })

  return <group ref={root} name="zhubieyu_root" position={[0, 0, RADIUS]} rotation-y={Math.PI / 2}>
    <primitive object={rig.scene} />
    <mesh name="zhubieyu_watercolor_ripples" rotation-x={-Math.PI / 2} position-y={0.012} userData={{ watercolorEffect: true }}>
      <planeGeometry args={[2.5, 2.5]} />
      <shaderMaterial ref={ripple} transparent depthWrite={false} uniforms={rippleUniforms}
        vertexShader="varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}"
        fragmentShader={`varying vec2 vUv; uniform float time; uniform float strength; uniform vec3 color;
          void main(){vec2 p=(vUv-.5)*2.;float r=length(p);float a=atan(p.y,p.x);
          float edge=fract(r*3.5-time*.24+.015*sin(a*9.+r*14.));
          float band=exp(-pow((edge-.5)/.07,2.));
          float alpha=.24*strength*band*smoothstep(.12,.35,r)*(1.-smoothstep(.65,1.,r));
          gl_FragColor=vec4(color,alpha);}`}
      />
    </mesh>
  </group>
}

useGLTF.preload(URL)
