import { useMemo } from 'react'
import { EffectComposer } from '@react-three/postprocessing'
import { useQuality } from '../app/store'
import { PaperEffect } from './PaperEffect'

// 水墨风格不需要写实后期（AO、景深、色调映射），只保留纸面质感
export function Effects() {
  const { multisampling } = useQuality()
  const paper = useMemo(() => new PaperEffect(), [])

  return (
    <EffectComposer multisampling={multisampling} key={multisampling}>
      <primitive object={paper} />
    </EffectComposer>
  )
}
