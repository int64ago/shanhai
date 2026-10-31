import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { Mesh } from 'three'

// 神兽模型到位前的占位体，用来调光照和材质
export function Placeholder() {
  const ref = useRef<Mesh>(null)

  useFrame((state) => {
    if (!ref.current) return
    const t = state.clock.elapsedTime
    ref.current.position.y = 0.9 + Math.sin(t * 1.2) * 0.05
    ref.current.rotation.y = t * 0.2
  })

  return (
    <mesh ref={ref} castShadow>
      <torusKnotGeometry args={[0.45, 0.16, 256, 32]} />
      <meshPhysicalMaterial color="#5f7a6a" roughness={0.25} metalness={0.1} clearcoat={0.6} />
    </mesh>
  )
}
