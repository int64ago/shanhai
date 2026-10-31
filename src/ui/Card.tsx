import { ARCHETYPE_LABELS, BEASTS } from '../app/beasts'
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

// 古籍卡片：原文用墨色，设计推断/造型形制用朱色细框另标，附生僻字注音与评书人语音开关
export function Card() {
  const selected = useApp((s) => s.selected)
  const narrating = useApp((s) => s.narrating)
  const toggleNarration = useApp((s) => s.toggleNarration)

  const beast = BEASTS.find((b) => b.id === selected)
  if (!beast) return null
  const content = CONTENT[beast.id]
  const arch = ARCHETYPE_LABELS[beast.archetype]

  return (
    <>
      <aside className="card">
        <div className="card-head">
          <h2 className="card-name">{beast.name}</h2>
          <span className="card-pinyin">{beast.pinyin}</span>
          <button
            className={`story-btn${narrating ? ' is-playing' : ''}`}
            onClick={toggleNarration}
            title={narrating ? '停止评书解说' : '听龙三叔评书解说（百炼 CosyVoice）'}
          >
            {narrating ? '止语' : '说书'}
          </button>
        </div>

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
            {beast.quote}
            <cite>——《{beast.source}》</cite>
          </p>
        )}

        {content && content.inferred.length > 0 ? (
          <div className="card-inferred">
            <span className="card-label is-inferred">设计</span>
            {content.inferred.map((i) => (
              <p key={i.item} title={i.basis}>
                {i.item}
              </p>
            ))}
          </div>
        ) : (
          <div className="card-inferred">
            <span className="card-label is-inferred">形制</span>
            <p>
              构型：{arch.name}（{beast.archetype}）
            </p>
            <p>拆解：{beast.anatomy}</p>
            <p>设色：{beast.palette}</p>
          </div>
        )}

        {!beast.ready && <p className="card-note">模型待铸 · 已备造型考据与评书解说</p>}
      </aside>

      {narrating && (
        <div className="story-caption" role="status" aria-live="polite">
          <span className="story-badge">评书 · 龙三叔</span>
          <p>{beast.story}</p>
        </div>
      )}
    </>
  )
}
