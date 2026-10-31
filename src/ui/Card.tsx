import { BEASTS } from '../app/beasts'
import { useApp } from '../app/store'

interface BeastContent {
  source: { book: string; text: string }[]
  inferred: { item: string; basis: string }[]
}

const CONTENT = Object.fromEntries(
  Object.entries(import.meta.glob<BeastContent>('../../content/beasts/*.json', { eager: true, import: 'default' })).map(
    ([path, data]) => [path.split('/').pop()!.replace('.json', ''), data],
  ),
)

// 古籍卡片：原文用墨色，设计推断用朱色细框另标，两者绝不混排
export function Card() {
  const selected = useApp((s) => s.selected)
  const beast = BEASTS.find((b) => b.id === selected)
  if (!beast) return null
  const content = CONTENT[beast.id]

  return (
    <aside className="card">
      <h2 className="card-name">{beast.name}</h2>
      {content ? (
        content.source.map((s) => (
          <p className="card-source" key={s.book}>
            <span className="card-label">原文</span>
            {s.text}
            <cite>——《{s.book}》</cite>
          </p>
        ))
      ) : (
        <p className="card-source">
          <span className="card-label">原文</span>
          {beast.epithet}
          <cite>——《山海经·{beast.source}》</cite>
        </p>
      )}
      {content && content.inferred.length > 0 && (
        <div className="card-inferred">
          <span className="card-label is-inferred">设计</span>
          {content.inferred.map((i) => (
            <p key={i.item} title={i.basis}>
              {i.item}
            </p>
          ))}
        </div>
      )}
      {!beast.ready && <p className="card-note">模型制作中，当前为占位</p>}
    </aside>
  )
}
