import { useEffect, useMemo, useState } from 'react'
import {
  ARCHETYPE_LABELS,
  BEASTS,
  REGIONS,
  type BeastArchetype,
  type BeastRegion,
} from '../app/beasts'
import { useApp } from '../app/store'
import { audio } from '../systems/audio/AudioEngine'

export function CatalogModal() {
  const open = useApp((s) => s.catalogOpen)
  const setOpen = useApp((s) => s.setCatalogOpen)
  const selected = useApp((s) => s.selected)
  const select = useApp((s) => s.select)
  const setRegionFilter = useApp((s) => s.setRegionFilter)

  const [query, setQuery] = useState('')
  const [region, setRegion] = useState<'all' | 'ready' | BeastRegion>('all')
  const [arch, setArch] = useState<'all' | BeastArchetype>('all')
  const [playingId, setPlayingId] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        setOpen(false)
      } else if ((e.key === 'm' || e.key === 'M') && !open) {
        const tag = (e.target as HTMLElement | null)?.tagName
        if (tag !== 'INPUT' && tag !== 'TEXTAREA') {
          e.preventDefault()
          setOpen(true)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return BEASTS.filter((b) => {
      if (region === 'ready' && !b.ready) return false
      if (region !== 'all' && region !== 'ready' && b.region !== region) return false
      if (arch !== 'all' && b.archetype !== arch) return false
      if (!q) return true
      return (
        b.name.includes(q) ||
        b.pinyin.toLowerCase().includes(q) ||
        b.source.includes(q) ||
        b.quote.includes(q) ||
        b.anatomy.toLowerCase().includes(q) ||
        b.palette.includes(q)
      )
    })
  }, [query, region, arch])

  if (!open) return null

  const readyCount = BEASTS.filter((b) => b.ready).length

  const handlePlayPreview = (id: string) => {
    if (playingId === id) {
      audio.stopNarration()
      setPlayingId(null)
      return
    }
    setPlayingId(id)
    void audio.playNarration(id, () => {
      setPlayingId((cur) => (cur === id ? null : cur))
    })
  }

  return (
    <div className="catalog-backdrop" onClick={() => setOpen(false)} role="dialog" aria-modal="true" aria-label="山海总目">
      <div className="catalog-panel" onClick={(e) => e.stopPropagation()}>
        <header className="catalog-header">
          <div>
            <h2 className="catalog-title">
              山海总目 · 十八卷异兽造型考
              <span className="catalog-badge">
                收录 {BEASTS.length} 尊 · 已现世 {readyCount} 尊
              </span>
            </h2>
            <p className="catalog-sub">
              按《五藏山经》《海外四经》《海内四经》《大荒及海内经》汇考原典、五大解剖构型与 3D 异体挂接蓝图
            </p>
          </div>
          <div className="catalog-search-wrap">
            <input
              type="search"
              className="catalog-search"
              placeholder="搜兽名 / 拼音 / 九首 / 一足 / 无面目..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="catalog-close" onClick={() => setOpen(false)} aria-label="关闭总目">
              ✕
            </button>
          </div>
        </header>

        <div className="catalog-filters">
          <div className="filter-row">
            <span className="filter-label">卷域</span>
            <button className={`filter-chip${region === 'all' ? ' is-active' : ''}`} onClick={() => setRegion('all')}>
              全部 ({BEASTS.length})
            </button>
            <button className={`filter-chip${region === 'ready' ? ' is-active' : ''}`} onClick={() => setRegion('ready')}>
              已现世 ({readyCount})
            </button>
            {REGIONS.map((r) => (
              <button
                key={r.id}
                className={`filter-chip${region === r.id ? ' is-active' : ''}`}
                onClick={() => setRegion(r.id)}
              >
                {r.name} ({BEASTS.filter((b) => b.region === r.id).length})
              </button>
            ))}
          </div>

          <div className="filter-row">
            <span className="filter-label">构型</span>
            <button className={`filter-chip${arch === 'all' ? ' is-active' : ''}`} onClick={() => setArch('all')}>
              全部构型
            </button>
            {(Object.keys(ARCHETYPE_LABELS) as BeastArchetype[]).map((k) => (
              <button
                key={k}
                className={`filter-chip${arch === k ? ' is-active' : ''}`}
                onClick={() => setArch(k)}
                title={ARCHETYPE_LABELS[k].desc}
              >
                {ARCHETYPE_LABELS[k].name} ({BEASTS.filter((b) => b.archetype === k).length})
              </button>
            ))}
          </div>
        </div>

        <div className="catalog-grid">
          {filtered.map((b) => {
            const isSelected = b.id === selected
            const isPlaying = playingId === b.id
            return (
              <article
                key={b.id}
                className={`beast-card${isSelected ? ' is-selected' : ''}${b.ready ? ' is-ready' : ''}`}
              >
                <div className="beast-card-top">
                  <div>
                    <h3 className="beast-card-name">
                      {b.name}
                      <span className="beast-card-pinyin">{b.pinyin}</span>
                    </h3>
                    <span className="beast-card-source">《{b.source}》</span>
                  </div>
                  <div className="beast-card-badges">
                    <span className="arch-tag">{ARCHETYPE_LABELS[b.archetype].name}</span>
                    <span className={`status-seal${b.ready ? ' is-ready' : ''}`}>
                      {b.ready ? '已现世' : '待铸'}
                    </span>
                  </div>
                </div>

                <blockquote className="beast-card-quote">“{b.quote}”</blockquote>

                <div className="beast-card-blueprint">
                  <div>
                    <strong>造型拆解：</strong>
                    {b.anatomy}
                  </div>
                  <div>
                    <strong>设色气韵：</strong>
                    {b.palette}
                  </div>
                </div>

                <div className="beast-card-actions">
                  <button
                    className={`card-act-btn${isPlaying ? ' is-playing' : ''}`}
                    onClick={() => handlePlayPreview(b.id)}
                  >
                    {isPlaying ? '■ 停止评书' : '▶ 听龙三叔评书'}
                  </button>
                  <button
                    className="card-act-btn is-primary"
                    onClick={() => {
                      select(b.id)
                      setRegionFilter(b.region)
                      setOpen(false)
                    }}
                  >
                    展卷观兽 →
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      </div>
    </div>
  )
}
