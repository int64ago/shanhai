import { Quadruped } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'

const call = (pan: number) => audio.bingfengCall(pan)

/** 前后两颗头已分别绑定，黑彘身无原生尾或额外挂件。 */
export function Bingfeng() {
  return <Quadruped id="bingfeng" initialHeading={Math.PI * 0.75} outline={0.003} specialEffect={null} onCall={call} />
}
