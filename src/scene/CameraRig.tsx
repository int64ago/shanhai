import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'
import { PerspectiveCamera } from 'three'
import { useApp } from '../app/store'

const BASE_FOV = 32

// 竖屏时把垂直视角放宽，保证神兽的水平宽度仍然完整入画；
// 宽屏时整体构图右移，让出左侧古籍卡片的位置
export function CameraRig() {
  const camera = useThree((s) => s.camera)
  const aspect = useThree((s) => s.size.width / s.size.height)
  const width = useThree((s) => s.size.width)
  const selected = useApp((s) => s.selected)

  useEffect(() => {
    if (!(camera instanceof PerspectiveCamera)) return
    // The long, low snake needs room above the selector and beside the text card.
    const bashe = selected === 'bashe'
    const fov = bashe ? 40 : BASE_FOV
    const minAspect = 1.2
    if (aspect >= minAspect) {
      camera.fov = fov
    } else {
      const halfH = Math.tan((fov * Math.PI) / 360) * (minAspect / aspect)
      camera.fov = Math.min(bashe ? 75 : 70, (Math.atan(halfH) * 360) / Math.PI)
    }
    const snakeOffset = width >= 600 ? (aspect > 1.3 ? -9 : -3.5) : 0
    camera.filmOffset = bashe ? snakeOffset : aspect > 1.3 ? -6 : 0
    camera.updateProjectionMatrix()
  }, [camera, aspect, width, selected])

  return null
}
