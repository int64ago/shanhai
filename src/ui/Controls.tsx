import { useApp, type Quality } from '../app/store'

const LABEL: Record<Quality, string> = { high: '高', medium: '中', low: '低' }
const NEXT: Record<Quality, Quality> = { high: 'medium', medium: 'low', low: 'high' }

export function Controls() {
  const muted = useApp((s) => s.muted)
  const unlocked = useApp((s) => s.audioUnlocked)
  const toggleMuted = useApp((s) => s.toggleMuted)
  const quality = useApp((s) => s.quality)
  const locked = useApp((s) => s.qualityLocked)
  const setQuality = useApp((s) => s.setQuality)

  return (
    <div className="controls">
      <button
        className="seal-btn"
        onClick={toggleMuted}
        aria-label={muted ? '开启声音' : '静音'}
        title={unlocked ? undefined : '点击画面任意处开启声音'}
      >
        {muted ? '无声' : '有声'}
      </button>
      <button
        className="seal-btn"
        onClick={() => setQuality(NEXT[quality])}
        aria-label="切换画质"
        title={locked ? '画质已手动锁定' : '画质随帧率自动调整'}
      >
        画{LABEL[quality]}
      </button>
    </div>
  )
}
