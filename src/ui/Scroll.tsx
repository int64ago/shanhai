import { BEASTS } from '../app/beasts'
import { useApp } from '../app/store'

// 底部图鉴卷轴：竖排兽名，未完成的以淡墨显示
export function Scroll() {
  const selected = useApp((s) => s.selected)
  const select = useApp((s) => s.select)

  return (
    <nav className="scroll" aria-label="图鉴">
      <div className="scroll-rod" />
      <ol className="scroll-paper">
        {BEASTS.map((b) => (
          <li key={b.id}>
            <button
              className={`scroll-item${b.id === selected ? ' is-active' : ''}${b.ready ? '' : ' is-pending'}`}
              onClick={() => select(b.id)}
              title={b.ready ? b.name : `${b.name}（制作中）`}
            >
              {b.name}
            </button>
          </li>
        ))}
      </ol>
      <div className="scroll-rod" />
    </nav>
  )
}
