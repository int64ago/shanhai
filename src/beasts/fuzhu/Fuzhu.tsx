import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { BufferAttribute, Color, NormalBlending, type ShaderMaterial } from 'three'
import { Quadruped, type QuadrupedEffectProps } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'
import { NOISE_GLSL } from '../../scene/noise.glsl'

const call = (pan: number) => audio.fuzhuCall(pan)

/** 「见则其邑大水」的写意补足：足边淡石青水雾，地面层层晕开的水纹。 */
function Water({ intensity }: QuadrupedEffectProps) {
  const ripple = useRef<ShaderMaterial>(null)
  const mist = useRef<ShaderMaterial>(null)
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: 0 },
    uCore: { value: new Color('#c4d9d5') },
    uEdge: { value: new Color('#527f89') },
  }), [])
  const particles = useMemo(() => {
    const count = 64
    return {
      positions: new BufferAttribute(new Float32Array(count * 3), 3),
      seeds: new BufferAttribute(Float32Array.from({ length: count }, (_, i) => (i + 0.5) / count), 1),
    }
  }, [])

  useFrame((_, rawDt) => {
    for (const material of [ripple.current, mist.current]) {
      if (!material) continue
      material.uniforms.uTime.value += Math.min(rawDt, 0.05)
      material.uniforms.uIntensity.value = Math.min(intensity.current / 1.8, 1)
    }
  })

  return <>
    <mesh rotation-x={-Math.PI / 2} position-y={0.035} renderOrder={2}>
      <planeGeometry args={[3.8, 3.8]} />
      <shaderMaterial
        ref={ripple}
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
            vec2 p = (vUv - 0.5) * 3.8;
            float grain = fbm(p * 9.0);
            float radius = length(p) + (fbm(p * 3.0) - 0.5) * 0.055;
            float wash = 0.0;
            float edge = 0.0;
            for (int i = 0; i < 4; i++) {
              float life = fract(uTime * 0.28 + float(i) * 0.25);
              float r = 0.24 + life * 1.46;
              float d = abs(radius - r);
              float fade = sin(life * 3.14159) * (1.0 - life);
              wash += (1.0 - smoothstep(0.012, 0.09, d)) * fade;
              edge += (1.0 - smoothstep(0.005, 0.022, d)) * fade;
            }
            float alpha = (wash * 0.42 + edge * 0.62) * uIntensity * (0.75 + grain * 0.25);
            if (alpha < 0.002) discard;
            gl_FragColor = vec4(mix(uCore, uEdge, clamp(edge + grain * 0.25, 0.0, 1.0)), alpha);
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
        ref={mist}
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
            float life = fract(aSeed * 17.0 + uTime * 0.34);
            float angle = aSeed * 127.0 + life * 0.48;
            float radius = 0.38 + fract(aSeed * 23.0) * 0.36 + life * 0.18;
            vec3 p = vec3(cos(angle) * radius, 0.04 + life * 0.65, sin(angle) * radius * 1.15);
            p.x += sin(uTime * 0.65 + aSeed * 39.0) * life * 0.09;
            vec4 mv = modelViewMatrix * vec4(p, 1.0);
            vLife = life;
            vSeed = aSeed;
            float size = (0.1 + fract(aSeed * 31.0) * 0.09) * sin(life * 3.14159);
            gl_PointSize = clamp(size * 900.0 / max(-mv.z, 0.1), 1.0, 150.0);
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
            float grain = fbm(uv * 2.6 + vec2(vSeed * 41.0, -uTime * 0.12));
            float d = length(uv * vec2(0.85, 1.0)) + (grain - 0.5) * 0.4;
            float alpha = (1.0 - smoothstep(0.25, 0.98, d)) * sin(vLife * 3.14159) * 0.16 * uIntensity;
            if (alpha < 0.002) discard;
            float edge = smoothstep(0.3, 0.85, d);
            gl_FragColor = vec4(mix(uCore, uEdge, edge * 0.7), alpha);
            #include <colorspace_fragment>
          }
        `}
      />
    </points>
  </>
}

export function Fuzhu() {
  return <Quadruped id="fuzhu" outline={0.003} outlineDepthBias={0.025} onCall={call} specialEffect={Water} />
}
