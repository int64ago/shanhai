import { useEffect } from 'react'
import { useApp } from '../../app/store'
import { audio } from './AudioEngine'

// 首次点击 / 按键时解锁音频并开始环境音；之后同步静音状态
export function useAudio() {
  const muted = useApp((s) => s.muted)
  const unlocked = useApp((s) => s.audioUnlocked)
  const unlockAudio = useApp((s) => s.unlockAudio)

  useEffect(() => {
    if (unlocked) return
    const onGesture = () => {
      void audio.unlock().then(() => {
        audio.playAmbient('valley')
        unlockAudio()
      })
    }
    window.addEventListener('pointerdown', onGesture, { once: true })
    window.addEventListener('keydown', onGesture, { once: true })
    return () => {
      window.removeEventListener('pointerdown', onGesture)
      window.removeEventListener('keydown', onGesture)
    }
  }, [unlocked, unlockAudio])

  useEffect(() => {
    audio.setMuted(muted)
  }, [muted])
}
