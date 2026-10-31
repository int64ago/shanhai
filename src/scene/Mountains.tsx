import { useMemo } from 'react'
import { BackSide, Color, ShaderMaterial } from 'three'
import { NOISE_GLSL } from './noise.glsl'
import { PALETTE } from './palette'

interface Layer {
  radius: number
  height: number
  seed: number
  /** 0 = 最近、最浓，1 = 最远、最淡 */
  depth: number
}

const LAYERS: Layer[] = [
  { radius: 150, height: 55, seed: 3.1, depth: 1 },
  { radius: 110, height: 38, seed: 7.7, depth: 0.7 },
  { radius: 75, height: 22, seed: 1.9, depth: 0.42 },
  { radius: 48, height: 9, seed: 5.3, depth: 0.15 },
]

function makeMaterial(layer: Layer) {
  const color = new Color().lerpColors(PALETTE.mountainNear, PALETTE.mountainFar, layer.depth)
  return new ShaderMaterial({
    side: BackSide,
    transparent: true,
    depthWrite: false,
    fog: false,
    uniforms: {
      uColor: { value: color },
      uMist: { value: PALETTE.mist },
      uSeed: { value: layer.seed },
      uDepth: { value: layer.depth },
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      uniform vec3 uMist;
      uniform float uSeed;
      uniform float uDepth;
      varying vec2 vUv;
      ${NOISE_GLSL}
      void main() {
        // 角度映射到圆上取噪声，保证 0/360° 处无缝
        float a = vUv.x * 6.2831853;
        vec2 p = vec2(cos(a), sin(a)) * (2.2 + uDepth) + uSeed;
        float ridge = 0.25 + 0.75 * pow(fbm(p * 1.6), 1.6) * 1.6;
        ridge += 0.06 * fbm(p * 9.0);
        float y = vUv.y;
        float edge = 0.004 + 0.01 * uDepth;
        float alpha = 1.0 - smoothstep(ridge - edge, ridge + edge, y);
        if (alpha < 0.01) discard;
        // 山顶墨色重、山脚被云雾吃掉，模拟“三远”中的留白
        float shade = mix(0.82, 1.08, fbm(p * 5.0 + y * 3.0));
        vec3 col = uColor * shade;
        float foot = smoothstep(ridge * 0.75, 0.0, y);
        col = mix(col, uMist, clamp(foot * 0.9 + uDepth * 0.25, 0.0, 1.0));
        gl_FragColor = vec4(col, alpha);
        #include <colorspace_fragment>
      }
    `,
  })
}

export function Mountains() {
  const materials = useMemo(() => LAYERS.map(makeMaterial), [])
  return (
    <group>
      {LAYERS.map((layer, i) => (
        <mesh key={i} material={materials[i]} position-y={layer.height / 2 - 2} renderOrder={-9 + i}>
          <cylinderGeometry args={[layer.radius, layer.radius, layer.height, 256, 1, true]} />
        </mesh>
      ))}
    </group>
  )
}
