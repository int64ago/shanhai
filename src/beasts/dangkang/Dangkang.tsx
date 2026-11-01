import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { BufferAttribute, Color, NormalBlending, type ShaderMaterial } from 'three'
import { Quadruped, type QuadrupedEffectProps } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'
import { NOISE_GLSL } from '../../scene/noise.glsl'

const call = (pan: number) => audio.dangkangCall(pan)

/** 据「见则天下大穰」补足金粟意象，粒子并非原文所载器官或行为。 */
function Grain({ intensity }: QuadrupedEffectProps) {
  const material = useRef<ShaderMaterial>(null)
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: 0 },
    uCore: { value: new Color('#e6c783') },
    uEdge: { value: new Color('#9c642b') },
  }), [])
  // 均匀种子与解析轨迹让 StrictMode 重挂载后仍保持同一片金粟。
  const particles = useMemo(() => {
    const count = 96
    return {
      positions: new BufferAttribute(new Float32Array(count * 3), 3),
      seeds: new BufferAttribute(Float32Array.from({ length: count }, (_, i) => (i + 0.5) / count), 1),
    }
  }, [])

  useFrame((_, rawDt) => {
    const shader = material.current
    if (!shader) return
    shader.uniforms.uTime.value += Math.min(rawDt, 0.05)
    shader.uniforms.uIntensity.value = Math.min(intensity.current / 1.8, 1)
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
          float life = fract(aSeed * 19.0 + uTime * 0.3);
          float angle = aSeed * 239.996 + life * 0.38;
          float radius = 0.48 + fract(aSeed * 29.0) * 0.45 + life * 0.18;
          vec3 p = vec3(cos(angle) * radius, 0.06 + life * 1.05, sin(angle) * radius * 1.12);
          p.x += sin(uTime * 0.9 + aSeed * 47.0) * life * 0.06;
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vLife = life;
          vSeed = aSeed;
          float size = (0.045 + fract(aSeed * 37.0) * 0.04) * sin(life * 3.14159);
          gl_PointSize = clamp(size * 900.0 / max(-mv.z, 0.1), 1.0, 90.0);
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
          float angle = vSeed * 41.0 + sin(uTime * 0.7 + vSeed * 23.0) * 0.22;
          uv = mat2(cos(angle), -sin(angle), sin(angle), cos(angle)) * uv;
          float grain = fbm(uv * 4.0 + vSeed * 31.0);
          // 细长谷粒轮廓，中心淡染，边缘沉积赭金颜料。
          float d = length(uv * vec2(1.85, 1.0)) + (grain - 0.5) * 0.13;
          float coverage = 1.0 - smoothstep(0.65, 0.94, d);
          float edge = smoothstep(0.35, 0.86, d);
          float alpha = coverage * sin(vLife * 3.14159) * uIntensity * (0.48 + edge * 0.2);
          if (alpha < 0.002) discard;
          gl_FragColor = vec4(mix(uCore, uEdge, edge * 0.8 + grain * 0.1), alpha);
          #include <colorspace_fragment>
        }
      `}
    />
  </points>
}

export function Dangkang() {
  return <Quadruped id="dangkang" onCall={call} specialEffect={Grain} />
}
