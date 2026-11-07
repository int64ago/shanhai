import { useEffect, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { DoubleSide, MathUtils, Mesh, type Group, type Material, type Object3D } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { Quadruped } from '../Quadruped'

const call = (pan: number) => audio.tianmaCall(pan)
const ALTITUDE = 0.4
const DRIFT = 0.12

/** 高模毛褶局部面朝向不齐；双面体表遮住关节内侧的外壳墨线。 */
function DogSurface({ scene }: { scene: Object3D }) {
  useEffect(() => {
    const sides = new Map<Material, Material['side']>()
    scene.traverse((node) => {
      if (!(node instanceof Mesh) || node.userData.inkOutline) return
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
        if (!sides.has(material)) sides.set(material, material.side)
        material.side = DoubleSide
        material.needsUpdate = true
      }
    })
    return () => {
      for (const [material, side] of sides) {
        material.side = side
        material.needsUpdate = true
      }
    }
  }, [scene])
  return null
}

/** 与 rig_tianma.py 的 4.6 秒收足动作同步；升降两端速度为零。 */
function flightEnvelope(seconds: number) {
  return MathUtils.smoothstep(seconds, 0.3, 1.2) * (1 - MathUtils.smoothstep(seconds, 3.0, 4.3))
}

export function Tianma() {
  const action = useApp((s) => s.action)
  const flight = useRef<Group>(null)
  const elapsed = useRef(0)
  const startingHeight = useRef(0)

  useEffect(() => {
    if (action === 'special') {
      elapsed.current = 0
      startingHeight.current = flight.current?.position.y ?? 0
    }
  }, [action])

  useFrame((_, rawDt) => {
    const group = flight.current
    if (!group) return
    const dt = Math.min(rawDt, 0.05)
    if (action === 'special') {
      elapsed.current += dt
      const lift = flightEnvelope(elapsed.current)
      // 白犬整体轻提前送，不补绘翼、云或地面粒子。
      const restart = startingHeight.current * (1 - MathUtils.smoothstep(elapsed.current, 0, 0.3))
      group.position.y = restart + ALTITUDE * lift
      group.position.x = group.position.y * (DRIFT / ALTITUDE)
    } else {
      // 用户在空中切换动作时从当前高度落下，不瞬移回地面。
      group.position.y = MathUtils.damp(group.position.y, 0, 6, dt)
      group.position.x = MathUtils.damp(group.position.x, 0, 6, dt)
      if (group.position.y < 0.0001) group.position.set(0, 0, 0)
    }
  })

  return <group ref={flight} name="tianma_flight">
    <Quadruped
      id="tianma"
      appendages={DogSurface}
      tailCount={1}
      tailUrl="/models/zheng/tail.glb"
      tailGirth={0.085}
      tailColor="#ffffff"
      tailSaturation={0.05}
      specialTailElevation={-0.12}
      specialEffect={null}
      onCall={call}
    />
  </group>
}
