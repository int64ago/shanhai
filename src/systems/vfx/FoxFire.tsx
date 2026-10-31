import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  Object3D,
  Points,
  ShaderMaterial,
  Vector3,
} from 'three'
import { NOISE_GLSL } from '../../scene/noise.glsl'

const PER_EMITTER = 48
const _p = new Vector3()

interface Props {
  /** 发射点（尾尖/翼尖），世界坐标每帧读取 */
  emitters: Object3D[]
  /** 0 = 熄灭，1 = 微焰，>1 = 神通爆发 */
  intensity: { current: number }
  coreColor?: string
  edgeColor?: string
}

/**
 * 水彩灵火（狐火青绿 / 帝江丹火朱金）：向上飘散的颜料晕团，中心淡、边缘积色水痕。
 * 用普通混合而不是叠加发光，否则在浅色宣纸上会被冲成白色看不见。
 */
export function FoxFire({ emitters, intensity, coreColor = '#a9d6cf', edgeColor = '#2f7d79' }: Props) {
  const count = Math.max(emitters.length, 1) * PER_EMITTER
  const ref = useRef<Points>(null)

  const { geometry, material, state } = useMemo(() => {
    const geometry = new BufferGeometry()
    geometry.setAttribute('position', new BufferAttribute(new Float32Array(count * 3), 3))
    geometry.setAttribute('aLife', new BufferAttribute(new Float32Array(count), 1))
    geometry.setAttribute('aSeed', new BufferAttribute(new Float32Array(count).map(() => Math.random()), 1))
    const material = new ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: {
        uTime: { value: 0 },
        uCore: { value: new Color(coreColor) },
        uEdge: { value: new Color(edgeColor) },
        uScale: { value: 1 },
      },
      vertexShader: /* glsl */ `
        attribute float aLife;
        attribute float aSeed;
        uniform float uScale;
        varying float vLife;
        varying float vSeed;
        void main() {
          vLife = aLife;
          vSeed = aSeed;
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          float size = (0.05 + 0.05 * aSeed) * uScale * sin(3.14159 * clamp(aLife, 0.0, 1.0)) * (1.0 - 0.5 * aLife);
          gl_PointSize = size * 900.0 / -mv.z;
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: /* glsl */ `
        uniform float uTime;
        uniform vec3 uCore;
        uniform vec3 uEdge;
        varying float vLife;
        varying float vSeed;
        ${NOISE_GLSL}
        void main() {
          if (vLife <= 0.0) discard;
          vec2 uv = gl_PointCoord * 2.0 - 1.0;
          // 噪声扰动边缘，做出水墨晕散的焰形而不是圆点
          float n = fbm(uv * 2.2 + vec2(vSeed * 17.0, -uTime * 1.5));
          float d = length(uv * vec2(1.0, 0.8)) + (n - 0.5) * 0.7;
          float a = smoothstep(1.0, 0.15, d);
          if (a < 0.01) discard;
          float edge = smoothstep(0.35, 0.85, d);
          vec3 col = mix(uCore, uEdge, edge);
          gl_FragColor = vec4(col, a * (1.0 - vLife) * 0.7);
          #include <colorspace_fragment>
        }
      `,
    })
    const state = {
      vel: new Float32Array(count * 3),
      life: geometry.getAttribute('aLife') as BufferAttribute,
      pos: geometry.getAttribute('position') as BufferAttribute,
      next: new Int32Array(Math.max(emitters.length, 1)),
      carry: new Float32Array(Math.max(emitters.length, 1)),
    }
    return { geometry, material, state }
  }, [count, emitters.length, coreColor, edgeColor])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const k = intensity.current
    material.uniforms.uTime.value += dt
    material.uniforms.uScale.value = 0.7 + Math.min(k, 2) * 0.25
    const { vel, life, pos } = state

    // 生成：强度越高发射越快
    const rate = Math.min(k, 2.5) * 9
    emitters.forEach((e, ei) => {
      state.carry[ei] += rate * dt
      e.getWorldPosition(_p)
      while (state.carry[ei] >= 1) {
        state.carry[ei] -= 1
        const i = ei * PER_EMITTER + state.next[ei]
        state.next[ei] = (state.next[ei] + 1) % PER_EMITTER
        pos.setXYZ(i, _p.x + (Math.random() - 0.5) * 0.04, _p.y + (Math.random() - 0.5) * 0.04, _p.z + (Math.random() - 0.5) * 0.04)
        vel[i * 3] = (Math.random() - 0.5) * 0.15
        vel[i * 3 + 1] = 0.25 + Math.random() * 0.35 * (0.5 + k * 0.5)
        vel[i * 3 + 2] = (Math.random() - 0.5) * 0.15
        life.setX(i, 0.0001)
      }
    })

    // 更新：上升、轻微湍流、寿命约 0.8–1.2 秒
    for (let i = 0; i < count; i++) {
      const l = life.getX(i)
      if (l <= 0) continue
      const nl = l + dt * 1.0
      if (nl >= 1) {
        life.setX(i, 0)
        continue
      }
      life.setX(i, nl)
      vel[i * 3] += Math.sin(nl * 9 + i) * 0.4 * dt
      vel[i * 3 + 2] += Math.cos(nl * 7 + i) * 0.4 * dt
      pos.setXYZ(i, pos.getX(i) + vel[i * 3] * dt, pos.getY(i) + vel[i * 3 + 1] * dt, pos.getZ(i) + vel[i * 3 + 2] * dt)
    }
    pos.needsUpdate = true
    life.needsUpdate = true
  })

  return <points ref={ref} geometry={geometry} material={material} frustumCulled={false} renderOrder={5} />
}
