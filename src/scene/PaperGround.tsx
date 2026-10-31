import { useMemo } from 'react'
import { Color, ShaderMaterial } from 'three'
import { INK } from '../systems/ink/palette'
import { NOISE_GLSL } from './noise.glsl'
import { PALETTE } from './palette'

// 宣纸地面：近处几笔淡墨皴擦，越远越淡，和山脚云雾接成一片留白
export function PaperGround() {
  const material = useMemo(
    () =>
      new ShaderMaterial({
        fog: false,
        uniforms: {
          uPaper: { value: new Color(INK.paper) },
          uWash: { value: new Color(INK.wash) },
          uMist: { value: PALETTE.mist },
        },
        vertexShader: /* glsl */ `
          varying vec3 vWorld;
          void main() {
            vec4 w = modelMatrix * vec4(position, 1.0);
            vWorld = w.xyz;
            gl_Position = projectionMatrix * viewMatrix * w;
          }
        `,
        fragmentShader: /* glsl */ `
          uniform vec3 uPaper;
          uniform vec3 uWash;
          uniform vec3 uMist;
          varying vec3 vWorld;
          ${NOISE_GLSL}
          void main() {
            vec2 p = vWorld.xz;
            float r = length(p);
            // 横向拉长的皴擦笔触
            float stroke = fbm(vec2(p.x * 0.35, p.y * 1.4) + 4.0);
            float dry = fbm(p * 6.0);
            float wash = smoothstep(0.6, 0.78, stroke + (dry - 0.5) * 0.25);
            wash *= smoothstep(12.0, 4.0, r) * smoothstep(1.2, 3.0, r);
            vec3 col = mix(uPaper, uWash, wash * 0.22);
            col *= 0.96 + 0.05 * dry;
            col = mix(col, uMist, smoothstep(6.0, 22.0, r));
            gl_FragColor = vec4(col, 1.0);
            #include <colorspace_fragment>
          }
        `,
      }),
    [],
  )

  return (
    <mesh rotation-x={-Math.PI / 2} material={material} renderOrder={-2}>
      <circleGeometry args={[45, 96]} />
    </mesh>
  )
}
