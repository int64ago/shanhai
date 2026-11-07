import { Quadruped } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'

const call = (pan: number) => audio.huanCall(pan)

/** 一目已离线嵌入去双目的狸身；三尾复用经验证的狰尾母件，分别生成骨链。 */
export function Huan() {
  return <Quadruped
    id="huan"
    tailCount={3}
    tailUrl="/models/zheng/tail.glb"
    tailGirth={0.065}
    tailColor="#d3c2a0"
    tailSaturation={0.12}
    outline={0.003}
    specialEffect={null}
    onCall={call}
  />
}
