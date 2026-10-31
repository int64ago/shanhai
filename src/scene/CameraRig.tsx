import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'
import { PerspectiveCamera } from 'three'

const BASE_FOV = 32

// 竖屏时把垂直视角放宽，保证神兽的水平宽度仍然完整入画；
// 宽屏时整体构图右移，让出左侧古籍卡片的位置
export function CameraRig() {
  const camera = useThree((s) => s.camera)
  const aspect = useThree((s) => s.size.width / s.size.height)

  useEffect(() => {
    if (!(camera instanceof PerspectiveCamera)) return
    const minAspect = 1.2
    if (aspect >= minAspect) {
      camera.fov = BASE_FOV
    } else {
      const halfH = Math.tan((BASE_FOV * Math.PI) / 360) * (minAspect / aspect)
      camera.fov = Math.min(70, (Math.atan(halfH) * 360) / Math.PI)
    }
    camera.filmOffset = aspect > 1.3 ? -6 : 0
    camera.updateProjectionMatrix()
  }, [camera, aspect])

  return null
}
