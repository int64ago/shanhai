import { Quadruped } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'

const call = (pan: number) => audio.mengjiCall(pan)

/** 「是善伏」靠 alert 动作的伏地表现；古经未记神异特效，故不加粒子。 */
export function Mengji() {
  return <Quadruped
    id="mengji"
    tailCount={1}
    tailGirth={0.075}
    tailColor="#ffffff"
    tailSaturation={0}
    specialTailElevation={0.05}
    specialEffect={null}
    onCall={call}
  />
}
