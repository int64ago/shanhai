import { useEffect, useMemo, useRef } from 'react'
import { BEASTS, REGIONS } from '../app/beasts'
import { useApp, type RegionFilter } from '../app/store'

// 底部山海长卷：上部为八大卷域竹简切换栏 + 「山海总目」入口，下部为竖排兽名卷轴
export function Scroll() {
  const selected = useApp((s) => s.selected)
  const select = useApp((s) => s.select)
  const regionFilter = useApp((s) => s.regionFilter)
  const setRegionFilter = useApp((s) => s.setRegionFilter)
  const setCatalogOpen = useApp((s) => s.setCatalogOpen)

  const paperRef = useRef<HTMLOListElement>(null)
  const activeRef = useRef<HTMLButtonElement>(null)

  const readyCount = useMemo(() => BEASTS.filter((b) => b.ready).length, [])

  const filtered = useMemo(() => {
    if (regionFilter === 'all') return BEASTS
    if (regionFilter === 'ready') return BEASTS.filter((b) => b.ready)
    return BEASTS.filter((b) => b.region === regionFilter)
  }, [regionFilter])

  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }, [selected, regionFilter])

  const scrollBy = (dx: number) => {
    paperRef.current?.scrollBy({ left: dx, behavior: 'smooth' })
  }

  const tabs: { id: RegionFilter; label: string; count: number }[] = [
    { id: 'all', label: '全卷', count: BEASTS.length },
    { id: 'ready', label: '已现', count: readyCount },
    ...REGIONS.map((r) => ({
      id: r.id as RegionFilter,
      label: r.short,
      count: BEASTS.filter((b) => b.region === r.id).length,
    })),
  ]

  return (
    <nav className="scroll-wrap" aria-label="山海图鉴卷轴">
      <div className="scroll-bar">
        <div className="scroll-tabs" role="tablist" aria-label="山海经卷域">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={regionFilter === t.id}
              className={`scroll-tab${regionFilter === t.id ? ' is-active' : ''}`}
              onClick={() => setRegionFilter(t.id)}
            >
              <span>{t.label}</span>
              <small>{t.count}</small>
            </button>
          ))}
        </div>
        <button
          className="catalog-trigger"
          onClick={() => setCatalogOpen(true)}
          title="展开《山海经》十八卷百兽考据与造型总目（快捷键 M）"
        >
          山海总目 · {BEASTS.length}
        </button>
      </div>

      <div className="scroll">
        <div className="scroll-rod" />
        <button className="scroll-arrow" onClick={() => scrollBy(-320)} aria-label="向左翻卷" title="向左翻卷">
          ‹
        </button>
        <ol
          ref={paperRef}
          className="scroll-paper"
          onWheel={(e) => {
            if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && paperRef.current) {
              paperRef.current.scrollLeft += e.deltaY
            }
          }}
        >
          {filtered.map((b) => {
            const active = b.id === selected
            return (
              <li key={b.id}>
                <button
                  ref={active ? activeRef : undefined}
                  className={`scroll-item${active ? ' is-active' : ''}${b.ready ? ' is-ready' : ' is-pending'}`}
                  onClick={() => select(b.id)}
                  title={`${b.name}（${b.pinyin}）· 《${b.source}》${b.ready ? ' [已现世]' : ' [待铸造]'}`}
                >
                  {b.name}
                  {b.ready && <i className="ready-dot" aria-hidden="true" />}
                </button>
              </li>
            )
          })}
        </ol>
        <button className="scroll-arrow" onClick={() => scrollBy(320)} aria-label="向右翻卷" title="向右翻卷">
          ›
        </button>
        <div className="scroll-rod" />
      </div>
    </nav>
  )
}
