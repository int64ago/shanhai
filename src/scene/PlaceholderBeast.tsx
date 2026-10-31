import { useEffect, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import type { Group } from 'three'
import { useApp } from '../app/store'
import { inkify } from '../systems/ink/inkify'

const URL = '/models/_placeholder/fox.glb'

// 未完成神兽的水墨意象素胚：左侧古籍卡已完整呈现其《山海经》原文、解剖构型与 3D 造型拆解参考
export function PlaceholderBeast() {
  const { scene } = useGLTF(URL)
  const selected = useApp((s) => s.selected)
  const ref = useRef<Group>(null)

  useEffect(() => {
    void inkify(scene, { saturation: 0.38 })
    console.log('[beast] ready', selected)
  }, [scene, selected])

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
