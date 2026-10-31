/**
 * 音频引擎：一个 AudioContext + 总线（master → ambient / sfx / voice）。
 *
 * M1 阶段的环境音是程序合成的（风声 + 古琴泛音式拨弦），不依赖素材文件；
 * 正式素材到位后 playAmbient 改为加载 public/audio/ambient/*.ogg，接口不变。
 */

const PENTATONIC = [0, 2, 4, 7, 9] // 宫商角徵羽
const BASE_HZ = 146.83 // D3

class AudioEngine {
  private ctx: AudioContext | null = null
  private master!: GainNode
  private ambient!: GainNode
  sfx!: GainNode
  private stopAmbient: (() => void) | null = null
  private muted = false

  get context() {
    return this.ctx
  }

  /** 必须在用户手势回调里调用，浏览器才允许出声 */
  async unlock() {
    if (!this.ctx) {
      this.ctx = new AudioContext()
      this.master = this.ctx.createGain()
      this.master.gain.value = this.muted ? 0 : 1
      this.master.connect(this.ctx.destination)
      this.ambient = this.ctx.createGain()
      this.ambient.gain.value = 0.8
      this.ambient.connect(this.master)
      this.sfx = this.ctx.createGain()
      this.sfx.connect(this.master)
    }
    if (this.ctx.state === 'suspended') await this.ctx.resume()
  }

  setMuted(muted: boolean) {
    this.muted = muted
    if (!this.ctx) return
    this.master.gain.setTargetAtTime(muted ? 0 : 1, this.ctx.currentTime, 0.15)
  }

  playAmbient(scene: 'valley') {
    if (!this.ctx || this.stopAmbient) return
    void scene
    const stops = [this.wind(), this.qin()]
    this.stopAmbient = () => stops.forEach((s) => s())
  }

  /** 山风：粉噪声过带通，中心频率和音量被慢速 LFO 推动，听起来像一阵阵风 */
  private wind() {
    const ctx = this.ctx!
    const length = ctx.sampleRate * 4
    const buffer = ctx.createBuffer(2, length, ctx.sampleRate)
    for (let ch = 0; ch < 2; ch++) {
      const data = buffer.getChannelData(ch)
      let b0 = 0, b1 = 0, b2 = 0
      for (let i = 0; i < length; i++) {
        const white = Math.random() * 2 - 1
        b0 = 0.99765 * b0 + white * 0.099046
        b1 = 0.963 * b1 + white * 0.2965164
        b2 = 0.57 * b2 + white * 1.0526913
        data[i] = (b0 + b1 + b2 + white * 0.1848) * 0.12
      }
    }
    const src = ctx.createBufferSource()
    src.buffer = buffer
    src.loop = true

    const band = ctx.createBiquadFilter()
    band.type = 'bandpass'
    band.frequency.value = 420
    band.Q.value = 0.7

    const gain = ctx.createGain()
    gain.gain.value = 0
    gain.gain.setTargetAtTime(0.35, ctx.currentTime, 2)

    const lfo = ctx.createOscillator()
    lfo.frequency.value = 0.07
    const lfoToFreq = ctx.createGain()
    lfoToFreq.gain.value = 260
    const lfoToGain = ctx.createGain()
    lfoToGain.gain.value = 0.18
    lfo.connect(lfoToFreq).connect(band.frequency)
    lfo.connect(lfoToGain).connect(gain.gain)

    src.connect(band).connect(gain).connect(this.ambient)
    src.start()
    lfo.start()
    return () => {
      gain.gain.setTargetAtTime(0, ctx.currentTime, 0.5)
      src.stop(ctx.currentTime + 2)
      lfo.stop(ctx.currentTime + 2)
    }
  }

  /** 稀疏的五声音阶拨弦（Karplus-Strong），间隔 4–11 秒，带长混响尾 */
  private qin() {
    const ctx = this.ctx!
    const out = ctx.createGain()
    out.gain.value = 0.22
    const reverb = ctx.createConvolver()
    reverb.buffer = this.impulse(4.5)
    const wet = ctx.createGain()
    wet.gain.value = 0.55
    out.connect(this.ambient)
    out.connect(reverb).connect(wet).connect(this.ambient)

    let timer = 0
    const schedule = () => {
      const degree = PENTATONIC[Math.floor(Math.random() * PENTATONIC.length)]
      const octave = Math.random() < 0.3 ? 2 : 1
      this.pluck(BASE_HZ * octave * 2 ** (degree / 12), out)
      if (Math.random() < 0.35) {
        const d2 = PENTATONIC[Math.floor(Math.random() * PENTATONIC.length)]
        setTimeout(() => this.pluck(BASE_HZ * 2 ** (d2 / 12), out), 350 + Math.random() * 500)
      }
      timer = window.setTimeout(schedule, 4000 + Math.random() * 7000)
    }
    timer = window.setTimeout(schedule, 2500)
    return () => clearTimeout(timer)
  }

  private pluck(freq: number, dest: AudioNode) {
    const ctx = this.ctx!
    const seconds = 3.5
    const length = Math.floor(ctx.sampleRate * seconds)
    const buffer = ctx.createBuffer(1, length, ctx.sampleRate)
    const data = buffer.getChannelData(0)
    const period = Math.round(ctx.sampleRate / freq)
    for (let i = 0; i < period; i++) data[i] = Math.random() * 2 - 1
    for (let i = period; i < length; i++) {
      data[i] = 0.4985 * (data[i - period] + data[i - period + 1])
    }
    const src = ctx.createBufferSource()
    src.buffer = buffer
    const tone = ctx.createBiquadFilter()
    tone.type = 'lowpass'
    tone.frequency.value = 2200
    const pan = ctx.createStereoPanner()
    pan.pan.value = Math.random() * 0.8 - 0.4
    src.connect(tone).connect(pan).connect(dest)
    src.start()
  }

  // ---------------------------------------------------------------- 神兽音效（合成占位，素材到位后替换）

  /** 软爪落在草地上：短促的低通噪声 */
  footstep(pan = 0, gain = 0.5) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const src = ctx.createBufferSource()
    src.buffer = this.noise(0.12)
    src.playbackRate.value = 0.8 + Math.random() * 0.4
    const lp = ctx.createBiquadFilter()
    lp.type = 'lowpass'
    lp.frequency.value = 500 + Math.random() * 300
    const g = ctx.createGain()
    g.gain.setValueAtTime(0, t)
    g.gain.linearRampToValueAtTime(gain * 0.5, t + 0.008)
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.1)
    src.connect(lp).connect(g).connect(this.panner(pan)).connect(this.sfx)
    src.start(t)
  }

  /**
   * 「其音如婴儿」：锯齿波过两组共振峰（近似元音 a），音高先扬后抑并带颤音，
   * 叠一层气声，再送入长混响，听感介于婴啼与狐鸣之间。
   */
  infantCry(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const dur = 1.3
    const out = ctx.createGain()
    out.gain.value = 0.55
    const reverb = ctx.createConvolver()
    reverb.buffer = this.impulse(3)
    const wet = ctx.createGain()
    wet.gain.value = 0.35
    const p = this.panner(pan)
    out.connect(p).connect(this.sfx)
    out.connect(reverb).connect(wet).connect(this.sfx)

    const osc = ctx.createOscillator()
    osc.type = 'sawtooth'
    const f0 = 430 + Math.random() * 60
    osc.frequency.setValueAtTime(f0 * 0.85, t)
    osc.frequency.linearRampToValueAtTime(f0 * 1.25, t + 0.25)
    osc.frequency.linearRampToValueAtTime(f0 * 1.1, t + 0.7)
    osc.frequency.exponentialRampToValueAtTime(f0 * 0.7, t + dur)
    const vib = ctx.createOscillator()
    vib.frequency.value = 7
    const vibGain = ctx.createGain()
    vibGain.gain.value = f0 * 0.025
    vib.connect(vibGain).connect(osc.frequency)

    const env = ctx.createGain()
    env.gain.setValueAtTime(0, t)
    env.gain.linearRampToValueAtTime(1, t + 0.08)
    env.gain.setValueAtTime(1, t + dur * 0.6)
    env.gain.exponentialRampToValueAtTime(0.001, t + dur)

    for (const [freq, q, g] of [[1000, 8, 1], [1650, 10, 0.6], [3000, 12, 0.25]] as const) {
      const bp = ctx.createBiquadFilter()
      bp.type = 'bandpass'
      bp.frequency.setValueAtTime(freq * 0.8, t)
      bp.frequency.linearRampToValueAtTime(freq, t + 0.2)
      bp.Q.value = q
      const fg = ctx.createGain()
      fg.gain.value = g
      osc.connect(bp).connect(fg).connect(env)
    }
    const breath = ctx.createBufferSource()
    breath.buffer = this.noise(dur)
    const bhp = ctx.createBiquadFilter()
    bhp.type = 'bandpass'
    bhp.frequency.value = 2500
    bhp.Q.value = 0.8
    const bg = ctx.createGain()
    bg.gain.value = 0.08
    breath.connect(bhp).connect(bg).connect(env)
    env.connect(out)

    osc.start(t)
    vib.start(t)
    breath.start(t)
    osc.stop(t + dur + 0.05)
    vib.stop(t + dur + 0.05)
  }

  /** 狐火燃起：带通噪声由低到高扫频的呼啸 + 低频鼓胀 */
  foxFire(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const src = ctx.createBufferSource()
    src.buffer = this.noise(2.2)
    const bp = ctx.createBiquadFilter()
    bp.type = 'bandpass'
    bp.Q.value = 1.2
    bp.frequency.setValueAtTime(200, t)
    bp.frequency.exponentialRampToValueAtTime(2400, t + 0.9)
    bp.frequency.exponentialRampToValueAtTime(900, t + 2.1)
    const g = ctx.createGain()
    g.gain.setValueAtTime(0, t)
    g.gain.linearRampToValueAtTime(0.5, t + 0.35)
    g.gain.exponentialRampToValueAtTime(0.001, t + 2.1)
    const sub = ctx.createOscillator()
    sub.frequency.setValueAtTime(55, t)
    sub.frequency.exponentialRampToValueAtTime(90, t + 0.6)
    const sg = ctx.createGain()
    sg.gain.setValueAtTime(0, t)
    sg.gain.linearRampToValueAtTime(0.35, t + 0.15)
    sg.gain.exponentialRampToValueAtTime(0.001, t + 1.2)
    const p = this.panner(pan)
    src.connect(bp).connect(g).connect(p)
    sub.connect(sg).connect(p)
    p.connect(this.sfx)
    src.start(t)
    sub.start(t)
    sub.stop(t + 1.3)
  }

  /**
   * 帝江「是识歌舞」：浑厚囊腔鼓拍 + 五声音阶青铜编钟双音泛音，奏一小段欢快节拍。
   */
  dijiangSong(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const p = this.panner(pan)
    const reverb = ctx.createConvolver()
    reverb.buffer = this.impulse(2.8)
    const wet = ctx.createGain()
    wet.gain.value = 0.4
    p.connect(this.sfx)
    p.connect(reverb).connect(wet).connect(this.sfx)

    // 四拍小曲（徵-宫-商-徵，高八度编钟双音 + 囊鼓）
    const notes = [7, 12, 14, 19, 16, 12]
    notes.forEach((deg, idx) => {
      const t0 = ctx.currentTime + idx * 0.34
      const freq = BASE_HZ * 2 * 2 ** (deg / 12)
      // 编钟正鼓音 + 侧鼓音（小三度泛音列）
      for (const [ratio, amp, decay] of [
        [1, 0.22, 1.4],
        [1.2, 0.12, 0.9],
        [2.76, 0.06, 0.45],
      ] as const) {
        const osc = ctx.createOscillator()
        osc.type = 'sine'
        osc.frequency.setValueAtTime(freq * ratio, t0)
        const g = ctx.createGain()
        g.gain.setValueAtTime(0, t0)
        g.gain.linearRampToValueAtTime(amp, t0 + 0.008)
        g.gain.exponentialRampToValueAtTime(0.0008, t0 + decay)
        osc.connect(g).connect(p)
        osc.start(t0)
        osc.stop(t0 + decay + 0.05)
      }
      // 浑厚囊鼓（强拍）
      if (idx % 2 === 0) {
        const drum = ctx.createOscillator()
        drum.type = 'sine'
        drum.frequency.setValueAtTime(115, t0)
        drum.frequency.exponentialRampToValueAtTime(52, t0 + 0.22)
        const dg = ctx.createGain()
        dg.gain.setValueAtTime(0, t0)
        dg.gain.linearRampToValueAtTime(0.38, t0 + 0.01)
        dg.gain.exponentialRampToValueAtTime(0.001, t0 + 0.28)
        drum.connect(dg).connect(p)
        drum.start(t0)
        drum.stop(t0 + 0.3)
      }
    })
  }

  /** 帝江四翼拍动：柔和的鼓风声 */
  wingFlutter(pan = 0, gain = 0.4) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const src = ctx.createBufferSource()
    src.buffer = this.noise(0.24)
    const bp = ctx.createBiquadFilter()
    bp.type = 'bandpass'
    bp.frequency.setValueAtTime(320, t)
    bp.frequency.exponentialRampToValueAtTime(680, t + 0.1)
    bp.frequency.exponentialRampToValueAtTime(260, t + 0.22)
    bp.Q.value = 1.4
    const g = ctx.createGain()
    g.gain.setValueAtTime(0, t)
    g.gain.linearRampToValueAtTime(gain * 0.45, t + 0.04)
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.22)
    src.connect(bp).connect(g).connect(this.panner(pan)).connect(this.sfx)
    src.start(t)
  }

  private noiseCache = new Map<number, AudioBuffer>()

  private noise(seconds: number) {
    const ctx = this.ctx!
    const key = Math.round(seconds * 100)
    let buf = this.noiseCache.get(key)
    if (!buf) {
      buf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * seconds), ctx.sampleRate)
      const d = buf.getChannelData(0)
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1
      this.noiseCache.set(key, buf)
    }
    return buf
  }

  private panner(pan: number) {
    const p = this.ctx!.createStereoPanner()
    p.pan.value = Math.max(-1, Math.min(1, pan))
    return p
  }

  private impulse(seconds: number) {
    const ctx = this.ctx!
    const length = Math.floor(ctx.sampleRate * seconds)
    const buffer = ctx.createBuffer(2, length, ctx.sampleRate)
    for (let ch = 0; ch < 2; ch++) {
      const data = buffer.getChannelData(ch)
      for (let i = 0; i < length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** 3
    }
    return buffer
  }
}

export const audio = new AudioEngine()
