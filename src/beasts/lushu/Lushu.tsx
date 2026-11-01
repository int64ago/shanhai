import { Quadruped } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'

const sing = (pan: number) => audio.lushuSong(pan)

export function Lushu() {
  return <Quadruped id="lushu" tailCount={1} tailColor="#b94328" onCall={sing} />
}
