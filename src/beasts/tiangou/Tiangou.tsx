import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Color, NormalBlending, type ShaderMaterial } from 'three'
import { Quadruped, type QuadrupedEffectProps } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'
import { NOISE_GLSL } from '../../scene/noise.glsl'

const call = (pan: number) => audio.tiangouCall(pan)

/** 「可以御凶」的写意补足：足边一圈淡金水彩环纹向外晕开，古经未记其具体形态。 */
function Ward({ intensity }: QuadrupedEffectProps) {
  const material = useRef<ShaderMaterial>(null)
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: 0 },
    uCore: { value: new Color('#e6cf9a') },
    uEdge: { value: new Color('#a97f3c') },
  }), [])

  useFrame((_, rawDt) => {
    if (!material.current) return
    material.current.uniforms.uTime.value += Math.min(rawDt, 0.05)
    material.current.uniforms.uIntensity.value = Math.min(intensity.current / 1.8, 1)
  })

  return (
    <mesh rotation-x={-Math.PI / 2} position-y={0.035} renderOrder={2}>
      <planeGeometry args={[3.2, 3.2]} />
      <shaderMaterial
        ref={material}
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
            vec2 p = (vUv - 0.5) * 3.2;
            float radius = length(p) + (fbm(p * 3.0) - 0.5) * 0.05;
            float grain = fbm(p * 9.0);
            float wash = 0.0;
            float edge = 0.0;
            for (int i = 0; i < 2; i++) {
              float life = fract(uTime * 0.3 + float(i) * 0.5);
              float d = abs(radius - (0.38 + life * 0.72));
              float fade = sin(life * 3.14159);
              wash += (1.0 - smoothstep(0.015, 0.11, d)) * fade;
              edge += (1.0 - smoothstep(0.004, 0.02, d)) * fade;
            }
            float alpha = (wash * 0.34 + edge * 0.6) * uIntensity * (0.75 + grain * 0.25);
            if (alpha < 0.002) discard;
            gl_FragColor = vec4(mix(uCore, uEdge, clamp(edge + grain * 0.25, 0.0, 1.0)), alpha);
            #include <colorspace_fragment>
          }
        `}
      />
    </mesh>
  )
}

export function Tiangou() {
  return <Quadruped
    id="tiangou"
    tailCount={1}
    tailUrl="/models/zheng/tail.glb"
    tailGirth={0.085}
    tailColor="#f6ead2"
    tailSaturation={0.1}
    specialEffect={Ward}
    onCall={call}
  />
}
