import { Quadruped } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'

const call = (pan: number) => audio.zhengCall(pan)

export function Zheng() {
  return <Quadruped
    id="zheng"
    tailCount={5}
    tailUrl="/models/zheng/tail.glb"
    tailGirth={0.065}
    tailColor="#ffffff"
    tailSaturation={0.88}
    specialEffect={null}
    onCall={call}
  />
}
