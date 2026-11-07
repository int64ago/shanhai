import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { BufferAttribute, Color, NormalBlending, type ShaderMaterial } from 'three'
import { Quadruped, type QuadrupedEffectProps } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'
import { NOISE_GLSL } from '../../scene/noise.glsl'

const call = (pan: number) => audio.feifeiCall(pan)

/** 「养之可以已忧」的写意补足：身周缓缓升起、淡去的暖金水彩光点。 */
function Solace({ intensity }: QuadrupedEffectProps) {
  const material = useRef<ShaderMaterial>(null)
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: 0 },
    uCore: { value: new Color('#f0d9a4') },
    uEdge: { value: new Color('#c08a44') },
  }), [])
  const particles = useMemo(() => {
    const count = 44
    return {
      positions: new BufferAttribute(new Float32Array(count * 3), 3),
      seeds: new BufferAttribute(Float32Array.from({ length: count }, (_, i) => (i + 0.5) / count), 1),
    }
  }, [])

  useFrame((_, rawDt) => {
    if (!material.current) return
    material.current.uniforms.uTime.value += Math.min(rawDt, 0.05)
    material.current.uniforms.uIntensity.value = Math.min(intensity.current / 1.8, 1)
  })

  return <points frustumCulled={false} renderOrder={3}>
    <bufferGeometry>
      <primitive attach="attributes-position" object={particles.positions} />
      <primitive attach="attributes-aSeed" object={particles.seeds} />
    </bufferGeometry>
    <shaderMaterial
      ref={material}
      uniforms={uniforms}
      transparent
      depthWrite={false}
      blending={NormalBlending}
      vertexShader={/* glsl */ `
        attribute float aSeed;
        uniform float uTime;
        uniform float uIntensity;
        varying float vLife;
        varying float vSeed;
        void main() {
          float life = fract(aSeed * 13.0 + uTime * 0.22);
          float angle = aSeed * 97.0 + life * 0.9;
          float radius = 0.34 + fract(aSeed * 29.0) * 0.34;
          vec3 p = vec3(cos(angle) * radius, 0.16 + life * 0.85, sin(angle) * radius * 1.3);
          p.x += sin(uTime * 0.5 + aSeed * 31.0) * 0.05;
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vLife = life;
          vSeed = aSeed;
          float size = (0.045 + fract(aSeed * 37.0) * 0.04) * sin(life * 3.14159);
          gl_PointSize = clamp(size * 900.0 / max(-mv.z, 0.1), 1.0, 70.0);
          gl_PointSize *= step(0.001, uIntensity);
          gl_Position = projectionMatrix * mv;
        }
      `}
      fragmentShader={/* glsl */ `
        uniform float uTime;
        uniform float uIntensity;
        uniform vec3 uCore;
        uniform vec3 uEdge;
        varying float vLife;
        varying float vSeed;
        ${NOISE_GLSL}
        void main() {
          vec2 uv = gl_PointCoord * 2.0 - 1.0;
          float grain = fbm(uv * 2.4 + vec2(vSeed * 37.0, -uTime * 0.1));
          float d = length(uv) + (grain - 0.5) * 0.3;
          float alpha = (1.0 - smoothstep(0.3, 0.96, d)) * sin(vLife * 3.14159) * 0.62 * uIntensity;
          if (alpha < 0.002) discard;
          gl_FragColor = vec4(mix(uCore, uEdge, smoothstep(0.25, 0.85, d)), alpha);
          #include <colorspace_fragment>
        }
      `}
    />
  </points>
}

export function Feifei() {
  return <Quadruped
    id="feifei"
    tailCount={1}
    tailUrl="/models/feifei/tail.glb"
    tailGirth={0.13}
    tailColor="#ffffff"
    tailSaturation={0.88}
    specialEffect={Solace}
    onCall={call}
  />
}
