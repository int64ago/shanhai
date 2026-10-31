import { Stage } from '../scene/Stage'
import { Scroll } from '../ui/Scroll'
import { Card } from '../ui/Card'
import { Controls } from '../ui/Controls'
import { ActionBar } from '../ui/ActionBar'
import { useAudio } from '../systems/audio/useAudio'

export function App() {
  useAudio()

  return (
    <>
      <Stage />
      <header className="title">
        山海异兽录
        <span className="seal">试作</span>
      </header>
      <Card />
      <Controls />
      <ActionBar />
      <Scroll />
    </>
  )
}
