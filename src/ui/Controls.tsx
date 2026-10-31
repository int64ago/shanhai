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
  const narrating = useApp((s) => s.narrating)
  const toggleNarration = useApp((s) => s.toggleNarration)
  const setCatalogOpen = useApp((s) => s.setCatalogOpen)

  return (
    <div className="controls">
      <button
        className="seal-btn"
        onClick={() => setCatalogOpen(true)}
        aria-label="打开山海总目"
        title="山海总目：检索《山海经》十八卷全部异兽与造型考据（快捷键 M）"
      >
        总目
      </button>
      <button
        className={`seal-btn${narrating ? ' is-active' : ''}`}
        onClick={toggleNarration}
        aria-label={narrating ? '停止评书解说' : '播放评书解说'}
        title="百炼 CosyVoice（龙三叔）说书人语音解说"
      >
        {narrating ? '止语' : '说书'}
      </button>
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
