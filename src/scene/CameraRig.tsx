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
  const height = useThree((s) => s.size.height)
  const selected = useApp((s) => s.selected)

  useEffect(() => {
    if (!(camera instanceof PerspectiveCamera)) return
    // The long, low snake needs room above the selector and beside the text card.
    const bashe = selected === 'bashe'
    const xiangliu = selected === 'xiangliu'
    const xiangliuTablet = xiangliu && width > 640 && aspect <= 1.3
    const xingxingTablet = selected === 'xingxing' && width > 640 && aspect <= 1.3
    const jiaochong = selected === 'jiaochong'
    const jiaochongTablet = jiaochong && width > 640 && aspect <= 1.3
    const yinglong = selected === 'yinglong'
    const yinglongTablet = yinglong && width > 640 && aspect <= 1.3
    const jimeng = selected === 'jimeng'
    const jimengTablet = jimeng && width > 640 && aspect <= 1.3
    const zhulong = selected === 'zhulong'
    const zhulongTablet = zhulong && width > 640 && aspect <= 1.3
    const leishen = selected === 'leishen'
    const leishenTablet = leishen && width > 640 && aspect <= 1.3
    const lingyu = selected === 'lingyu'
    const lingyuTablet = lingyu && width > 640 && aspect <= 1.3
    const kuafu = selected === 'kuafu'
    const tianwuDesktop = selected === 'tianwu' && width > 1000 && aspect > 1.3
    const fov = tianwuDesktop ? 38 : xiangliu ? (xiangliuTablet ? 62 : 44) : kuafu ? 40 : lingyu ? (lingyuTablet ? 47 : 38) : leishen ? 54 : zhulong ? (zhulongTablet ? 54 : 42) : jimeng ? (jimengTablet ? 52 : 42) : yinglong ? (yinglongTablet ? 60 : 44) : bashe ? 40 : jiaochongTablet ? 50 : jiaochong ? 42 : xingxingTablet && width < 760 ? 36 : BASE_FOV
    const minAspect = 1.2
    if (aspect >= minAspect) {
      camera.fov = fov
    } else {
      const halfH = Math.tan((fov * Math.PI) / 360) * (minAspect / aspect)
      camera.fov = Math.min(xiangliu ? (xiangliuTablet ? 94 : 85) : kuafu ? 80 : selected === 'shuhu' ? 58 : yinglong ? 85 : zhulong || leishen ? 80 : bashe || jiaochong || jimeng || lingyu ? 75 : 70, (Math.atan(halfH) * 360) / Math.PI)
    }
    const snakeOffset = width >= 600 ? (aspect > 1.3 ? -9 : -3.5) : 0
    // The full source/design card remains visible above 640px; keep Xingxing
    // beside it on portrait tablets as well as on wide desktop screens.
    const xingxingOffset = xingxingTablet ? -5.5 : aspect > 1.3 ? -6 : 0
    // Fit both heads and outstretched hands beside the portrait source card.
    const jiaochongOffset = jiaochongTablet ? (width < 760 ? -8 : -6.5) : aspect > 1.3 ? -6 : 0
    const yinglongOffset = yinglongTablet ? -5 : aspect > 1.3 ? -7 : 0
    const jimengOffset = jimengTablet ? -5 : aspect > 1.3 ? -6 : 0
    const zhulongOffset = zhulongTablet ? -5 : aspect > 1.3 ? -7 : 0
    const leishenOffset = leishenTablet ? (width < 760 ? -8 : -6) : aspect > 1.3 ? -7 : 0
    const lingyuOffset = lingyuTablet ? (width < 760 ? -8 : -6) : aspect > 1.3 ? -7 : 0
    const xiangliuOffset = xiangliuTablet ? (width < 760 ? -6 : -5) : aspect > 1.3 ? -5 : 0
    camera.filmOffset = xiangliu ? xiangliuOffset : lingyu ? lingyuOffset : leishen ? leishenOffset : zhulong ? zhulongOffset : jimeng ? jimengOffset : yinglong ? yinglongOffset : bashe ? snakeOffset : jiaochong ? jiaochongOffset : xingxingOffset
    if (xiangliuTablet) camera.setViewOffset(width, height, 0, -height * .07, width, height)
    else camera.clearViewOffset()
    // These four silhouettes need room beside the scrollable portrait-tablet card.
    // Apply after the existing rules so phone and desktop framing stay unchanged.
    if (width > 640 && width <= 1000 && aspect <= 1.3 && ['kui', 'shuhu', 'kuafu', 'xixiyu'].includes(selected)) {
      const tabletFov = selected === 'kuafu' ? 44 : 36
      const halfH = Math.tan((tabletFov * Math.PI) / 360) * Math.max(1, minAspect / aspect)
      const minTabletFov = selected === 'kuafu' ? 64 : 54
      camera.fov = Math.max(minTabletFov, Math.min(selected === 'kuafu' ? 80 : selected === 'shuhu' ? 58 : 70, (Math.atan(halfH) * 360) / Math.PI))
      camera.filmOffset = -3
    }
    // Keep Qiangliang's raised head and planted feet eight pixels clear of tablet UI.
    if (selected === 'qiangliang' && width > 640 && width <= 1000 && aspect <= 1.3) {
      const halfH = Math.tan((34 * Math.PI) / 360) * Math.max(1, minAspect / aspect)
      camera.fov = Math.max(50, Math.min(70, (Math.atan(halfH) * 360) / Math.PI))
      camera.filmOffset = -1
    }
    camera.updateProjectionMatrix()
  }, [camera, aspect, width, height, selected])

  return null
}
