import { useEffect, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import type { Group } from 'three'
import { inkify } from '../systems/ink/inkify'

const URL = '/models/_placeholder/fox.glb'

// 未完成神兽的占位：Rodin 最低档生成的普通狐狸，只有呼吸
export function PlaceholderBeast() {
  const { scene } = useGLTF(URL)
  const ref = useRef<Group>(null)

  useEffect(() => void inkify(scene, { saturation: 0.5 }), [scene])

  useFrame((state) => {
    const g = ref.current
    if (!g) return
    const t = state.clock.elapsedTime
    g.scale.y = 1 + Math.sin(t * 1.6) * 0.006
  })

  return (
    <group ref={ref} rotation-y={Math.PI / 2 - 0.35}>
      <primitive object={scene} />
    </group>
  )
}

useGLTF.preload(URL)
