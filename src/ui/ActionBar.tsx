import { useEffect } from 'react'
import { BEASTS } from '../app/beasts'
import { useApp, type BeastAction } from '../app/store'

const ITEMS: { id: BeastAction; label: string; key: string }[] = [
  { id: 'idle', label: '静', key: '1' },
  { id: 'walk', label: '行', key: '2' },
  { id: 'special', label: '神通', key: '3' },
]

export function ActionBar() {
  const action = useApp((s) => s.action)
  const setAction = useApp((s) => s.setAction)
  const selected = useApp((s) => s.selected)
  const ready = BEASTS.find((b) => b.id === selected)?.ready ?? false

  useEffect(() => {
    if (!ready) return
    const onKey = (e: KeyboardEvent) => {
      const item = ITEMS.find((i) => i.key === e.key)
      if (item) setAction(item.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ready, setAction])

  if (!ready) return null

  return (
    <div className="actions" role="toolbar" aria-label="动作">
      {ITEMS.map((i) => (
        <button
          key={i.id}
          className={`action-btn${action === i.id ? ' is-active' : ''}`}
          onClick={() => setAction(i.id)}
          title={`快捷键 ${i.key}`}
        >
          {i.label}
        </button>
      ))}
    </div>
  )
}
