import { Quadruped } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'

const call = (pan: number) => audio.luwuCall(pan)

export function Luwu() {
  return <Quadruped
    id="luwu"
    tailCount={9}
    tailUrl="/models/luwu/tail.glb"
    tailGirth={0.065}
    tailColor="#ffffff"
    tailSaturation={0.88}
    specialEffect={null}
    onCall={call}
  />
}
