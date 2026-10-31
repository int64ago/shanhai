import { useMemo } from 'react'
import { BackSide, ShaderMaterial } from 'three'
import { NOISE_GLSL } from './noise.glsl'
import { PALETTE } from './palette'

// 宣纸色天幕：地平线暖白，向上渐入灰青，叠一层极淡的纸纹和云气
export function Sky() {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        side: BackSide,
        depthWrite: false,
        fog: false,
        uniforms: {
          uTop: { value: PALETTE.skyTop },
          uHorizon: { value: PALETTE.horizon },
        },
        vertexShader: /* glsl */ `
          varying vec3 vDir;
          void main() {
            vDir = normalize(position);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            gl_Position.z = gl_Position.w;
          }
        `,
        fragmentShader: /* glsl */ `
          uniform vec3 uTop;
          uniform vec3 uHorizon;
          varying vec3 vDir;
          ${NOISE_GLSL}
          void main() {
            float h = clamp(vDir.y, 0.0, 1.0);
            vec3 col = mix(uHorizon, uTop, smoothstep(0.0, 0.55, h));
            vec2 uv = vec2(atan(vDir.z, vDir.x) * 3.0, vDir.y * 6.0);
            float cloud = smoothstep(0.55, 0.85, fbm(uv * vec2(1.0, 2.5) + 3.0));
            col = mix(col, uHorizon * 1.04, cloud * 0.35 * smoothstep(0.05, 0.35, h));
            col *= 0.985 + 0.03 * hash12(gl_FragCoord.xy);
            gl_FragColor = vec4(col, 1.0);
            #include <colorspace_fragment>
          }
        `,
      }),
    [],
  )

  return (
    <mesh material={material} renderOrder={-10}>
      <sphereGeometry args={[400, 32, 16]} />
    </mesh>
  )
}
