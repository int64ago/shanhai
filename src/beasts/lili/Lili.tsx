import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { BufferAttribute, Color, NormalBlending, type ShaderMaterial } from 'three'
import { Quadruped, type QuadrupedEffectProps } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'
import { NOISE_GLSL } from '../../scene/noise.glsl'

const call = (pan: number) => audio.liliCall(pan)

/** 「见则其县多土功」的写意补足：足边黄土尘晕与抛起的土块，原文并未记载此兽掘土。 */
function Earthwork({ intensity }: QuadrupedEffectProps) {
  const dust = useRef<ShaderMaterial>(null)
  const clods = useRef<ShaderMaterial>(null)
  const time = useRef(0)
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: 0 },
    uCore: { value: new Color('#c9a26a') },
    uEdge: { value: new Color('#6e4526') },
  }), [])
  // 均匀种子与解析轨迹让 StrictMode 重挂载后仍保持同一批土块。
  const particles = useMemo(() => {
    const count = 72
    return {
      positions: new BufferAttribute(new Float32Array(count * 3), 3),
      seeds: new BufferAttribute(Float32Array.from({ length: count }, (_, i) => (i + 0.5) / count), 1),
    }
  }, [])

  useFrame((_, rawDt) => {
    // R3F 会复制 uniforms；更新实际材质，并用同一时钟同步尘晕与土块。
    time.current += Math.min(rawDt, 0.05)
    for (const material of [dust.current, clods.current]) {
      if (!material) continue
      material.uniforms.uTime.value = time.current
      material.uniforms.uIntensity.value = Math.min(intensity.current / 1.8, 1)
    }
  })

  return <>
    <mesh rotation-x={-Math.PI / 2} position-y={0.03} renderOrder={2}>
      <planeGeometry args={[3.6, 3.6]} />
      <shaderMaterial
        ref={dust}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={NormalBlending}
        vertexShader={/* glsl */ `
          varying vec2 vUv;
          void main() {
            vUv = uv;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `}
        fragmentShader={/* glsl */ `
          uniform float uTime;
          uniform float uIntensity;
          uniform vec3 uCore;
          uniform vec3 uEdge;
          varying vec2 vUv;
          ${NOISE_GLSL}
          void main() {
            vec2 p = (vUv - 0.5) * 3.6;
            float grain = fbm(p * 8.0);
            float radius = length(p * vec2(1.0, 0.72)) + (fbm(p * 2.6) - 0.5) * 0.3;
            float wash = 0.0;
            float edge = 0.0;
            for (int i = 0; i < 3; i++) {
              float life = fract(uTime * 0.34 + float(i) / 3.0);
              float d = abs(radius - (0.32 + life * 1.05));
              float fade = sin(life * 3.14159) * (1.0 - life * 0.6);
              wash += (1.0 - smoothstep(0.03, 0.26, d)) * fade;
              edge += (1.0 - smoothstep(0.01, 0.05, d)) * fade;
            }
            float alpha = (wash * 0.34 + edge * 0.22) * uIntensity * (0.55 + grain * 0.6);
            if (alpha < 0.002) discard;
            gl_FragColor = vec4(mix(uCore, uEdge, clamp(edge * 0.8 + grain * 0.3, 0.0, 1.0)), alpha);
            #include <colorspace_fragment>
          }
        `}
      />
    </mesh>
    <points frustumCulled={false} renderOrder={3}>
      <bufferGeometry>
        <primitive attach="attributes-position" object={particles.positions} />
        <primitive attach="attributes-aSeed" object={particles.seeds} />
      </bufferGeometry>
      <shaderMaterial
        ref={clods}
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
            float life = fract(aSeed * 17.0 + uTime * 0.62);
            float angle = aSeed * 239.996;
            float start = 0.3 + fract(aSeed * 23.0) * 0.28;
            float reach = start + life * (0.2 + fract(aSeed * 31.0) * 0.3);
            float height = (0.28 + fract(aSeed * 13.0) * 0.5) * 4.0 * life * (1.0 - life);
            vec3 p = vec3(cos(angle) * reach, 0.03 + height, sin(angle) * reach * 1.35);
            vec4 mv = modelViewMatrix * vec4(p, 1.0);
            vLife = life;
            vSeed = aSeed;
            float size = 0.03 + fract(aSeed * 37.0) * 0.045;
            gl_PointSize = clamp(size * 900.0 / max(-mv.z, 0.1), 1.0, 70.0) * step(0.001, uIntensity);
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
            float angle = vSeed * 41.0 + uTime * (fract(vSeed * 11.0) - 0.5) * 3.0;
            uv = mat2(cos(angle), -sin(angle), sin(angle), cos(angle)) * uv;
            float grain = fbm(uv * 3.2 + vSeed * 31.0);
            // 方棱土块：切比雪夫距离加噪声破边，焦褐沉积在边缘。
            float d = max(abs(uv.x), abs(uv.y) * 1.2) + (grain - 0.5) * 0.5;
            float coverage = 1.0 - smoothstep(0.58, 0.8, d);
            float edge = smoothstep(0.3, 0.72, d);
            float alpha = coverage * min(sin(vLife * 3.14159) * 2.2, 1.0) * uIntensity * 0.86;
            if (alpha < 0.002) discard;
            gl_FragColor = vec4(mix(uCore, uEdge, edge * 0.75 + grain * 0.25), alpha);
            #include <colorspace_fragment>
          }
        `}
      />
    </points>
  </>
}

export function Lili() {
  return <Quadruped id="lili" outline={0.003} onCall={call} specialEffect={Earthwork} />
}
