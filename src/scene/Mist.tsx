import { useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { BackSide, ShaderMaterial } from 'three'
import { useQuality } from '../app/store'
import { NOISE_GLSL } from './noise.glsl'
import { PALETTE } from './palette'

// 环绕舞台的云雾带：几层透明圆柱，噪声镂空并缓慢漂移
export function Mist() {
  const { mistLayers } = useQuality()

  const layers = useMemo(
    () =>
      Array.from({ length: 6 }, (_, i) => ({
        radius: 14 + i * 9,
        height: 6 + i * 2.5,
        y: 0.6 + i * 0.9,
        material: new ShaderMaterial({
          side: BackSide,
          transparent: true,
          depthWrite: false,
          fog: false,
          uniforms: {
            uTime: { value: 0 },
            uColor: { value: PALETTE.mist },
            uSeed: { value: i * 13.7 },
            uOpacity: { value: 0.55 - i * 0.05 },
          },
          vertexShader: /* glsl */ `
            varying vec2 vUv;
            void main() {
              vUv = uv;
              gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
          `,
          fragmentShader: /* glsl */ `
            uniform float uTime;
            uniform vec3 uColor;
            uniform float uSeed;
            uniform float uOpacity;
            varying vec2 vUv;
            ${NOISE_GLSL}
            void main() {
              float a = vUv.x * 6.2831853 + uTime * 0.004;
              vec2 p = vec2(cos(a), sin(a)) * 3.0 + vec2(uSeed, vUv.y * 2.2 - uTime * 0.01);
              float n = fbm(p + fbm(p * 1.7 + uTime * 0.02));
              float band = smoothstep(0.0, 0.35, vUv.y) * smoothstep(1.0, 0.45, vUv.y);
              float alpha = smoothstep(0.42, 0.75, n) * band * uOpacity;
              if (alpha < 0.005) discard;
              gl_FragColor = vec4(uColor, alpha);
              #include <colorspace_fragment>
            }
          `,
        }),
      })),
    [],
  )

  useFrame((_, dt) => {
    for (const l of layers) l.material.uniforms.uTime.value += dt
  })

  return (
    <group>
      {layers.slice(0, mistLayers).map((l, i) => (
        <mesh key={i} material={l.material} position-y={l.y} renderOrder={-4 + i}>
          <cylinderGeometry args={[l.radius, l.radius, l.height, 128, 1, true]} />
        </mesh>
      ))}
    </group>
  )
}
