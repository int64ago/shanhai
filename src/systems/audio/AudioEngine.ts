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
  private narrationEl: HTMLAudioElement | null = null
  private narrationTimer = 0
  private onNarrationEnd: (() => void) | null = null

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
    if (this.narrationEl) this.narrationEl.muted = muted
    if (!this.ctx) return
    this.master.gain.setTargetAtTime(muted ? 0 : 1, this.ctx.currentTime, 0.15)
  }

  /**
   * 播放百炼 CosyVoice (longsanshu 龙三叔) 评书人语音解说：
   * 开场先敲一声清脆醒木，同时压低背景风声与古琴，解说结束自动恢复。
   */
  async playNarration(beastId: string, onEnd?: () => void) {
    await this.unlock()
    this.stopNarration()
    this.onNarrationEnd = onEnd ?? null

    // 压低环境音，衬托说书人声
    if (this.ctx) {
      this.ambient.gain.setTargetAtTime(0.24, this.ctx.currentTime, 0.2)
    }
    this.xingmu()

    const el = new Audio(`/audio/narration/${beastId}.mp3`)
    el.muted = this.muted
    el.volume = 0.95
    this.narrationEl = el

    const finish = () => {
      if (this.narrationEl !== el) return
      this.narrationEl = null
      if (this.ctx) {
        this.ambient.gain.setTargetAtTime(0.8, this.ctx.currentTime, 0.5)
      }
      const cb = this.onNarrationEnd
      this.onNarrationEnd = null
      cb?.()
    }

    el.addEventListener('ended', finish, { once: true })
    el.addEventListener('error', finish, { once: true })

    this.narrationTimer = window.setTimeout(() => {
      if (this.narrationEl === el) {
        void el.play().catch(finish)
      }
    }, 220)
  }

  stopNarration() {
    if (this.narrationTimer) {
      clearTimeout(this.narrationTimer)
      this.narrationTimer = 0
    }
    if (this.narrationEl) {
      const el = this.narrationEl
      this.narrationEl = null
      el.pause()
      el.src = ''
    }
    if (this.ctx) {
      this.ambient.gain.setTargetAtTime(0.8, this.ctx.currentTime, 0.4)
    }
    const cb = this.onNarrationEnd
    this.onNarrationEnd = null
    cb?.()
  }

  /** 说书人开场醒木（惊堂木）：短促硬木叩击共振 + 堂音混响 */
  private xingmu() {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const noise = ctx.createBufferSource()
    noise.buffer = this.noise(0.06)
    const bp = ctx.createBiquadFilter()
    bp.type = 'bandpass'
    bp.frequency.setValueAtTime(1650, t)
    bp.Q.value = 3.2
    const ng = ctx.createGain()
    ng.gain.setValueAtTime(0, t)
    ng.gain.linearRampToValueAtTime(0.32, t + 0.002)
    ng.gain.exponentialRampToValueAtTime(0.001, t + 0.055)

    const wood = ctx.createOscillator()
    wood.type = 'triangle'
    wood.frequency.setValueAtTime(820, t)
    wood.frequency.exponentialRampToValueAtTime(340, t + 0.045)
    const wg = ctx.createGain()
    wg.gain.setValueAtTime(0, t)
    wg.gain.linearRampToValueAtTime(0.28, t + 0.002)
    wg.gain.exponentialRampToValueAtTime(0.001, t + 0.05)

    noise.connect(bp).connect(ng).connect(this.sfx)
    wood.connect(wg).connect(this.sfx)
    noise.start(t)
    wood.start(t)
    wood.stop(t + 0.06)
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

  /**
   * 驳「其音如鼓，食虎豹，可以御兵」：三声沉雷战鼓锤击 + 低沉虎啸胸腔共鸣 + 金铁辟兵余音。
   */
  boDrumRoar(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const p = this.panner(pan)
    const reverb = ctx.createConvolver()
    reverb.buffer = this.impulse(2.6)
    const wet = ctx.createGain()
    wet.gain.value = 0.42
    p.connect(this.sfx)
    p.connect(reverb).connect(wet).connect(this.sfx)

    // 三声雷鼓（「音如鼓」）
    for (const [offset, fStart, fEnd, amp] of [
      [0, 128, 44, 0.52],
      [0.28, 118, 42, 0.42],
      [0.62, 142, 38, 0.62],
    ] as const) {
      const t0 = ctx.currentTime + offset
      const drum = ctx.createOscillator()
      drum.type = 'sine'
      drum.frequency.setValueAtTime(fStart, t0)
      drum.frequency.exponentialRampToValueAtTime(fEnd, t0 + 0.34)
      const dg = ctx.createGain()
      dg.gain.setValueAtTime(0, t0)
      dg.gain.linearRampToValueAtTime(amp, t0 + 0.008)
      dg.gain.exponentialRampToValueAtTime(0.001, t0 + 0.42)
      drum.connect(dg).connect(p)
      drum.start(t0)
      drum.stop(t0 + 0.45)

      // 鼓皮击打瞬态
      const skin = ctx.createBufferSource()
      skin.buffer = this.noise(0.09)
      const lp = ctx.createBiquadFilter()
      lp.type = 'bandpass'
      lp.frequency.setValueAtTime(360, t0)
      lp.Q.value = 1.6
      const sg = ctx.createGain()
      sg.gain.setValueAtTime(0, t0)
      sg.gain.linearRampToValueAtTime(amp * 0.45, t0 + 0.004)
      sg.gain.exponentialRampToValueAtTime(0.001, t0 + 0.08)
      skin.connect(lp).connect(sg).connect(p)
      skin.start(t0)
    }

    // 胸腔低吼 + 独角破甲金铁泛音（「食虎豹，可以御兵」）
    const tRoar = ctx.currentTime + 0.12
    const growl = ctx.createOscillator()
    growl.type = 'sawtooth'
    growl.frequency.setValueAtTime(92, tRoar)
    growl.frequency.linearRampToValueAtTime(118, tRoar + 0.35)
    growl.frequency.exponentialRampToValueAtTime(64, tRoar + 1.45)
    const bp = ctx.createBiquadFilter()
    bp.type = 'bandpass'
    bp.frequency.setValueAtTime(240, tRoar)
    bp.Q.value = 2.8
    const gg = ctx.createGain()
    gg.gain.setValueAtTime(0, tRoar)
    gg.gain.linearRampToValueAtTime(0.28, tRoar + 0.14)
    gg.gain.exponentialRampToValueAtTime(0.001, tRoar + 1.5)
    growl.connect(bp).connect(gg).connect(p)
    growl.start(tRoar)
    growl.stop(tRoar + 1.55)
  }

  /**
   * 毕方「其鸣自訆也，见则其邑有讹火」：双音节仙鹤高唳（模拟“毕—方—”自呼其名）+ 丹火爆燃呼啸。
   */
  bifangCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const p = this.panner(pan)
    const reverb = ctx.createConvolver()
    reverb.buffer = this.impulse(2.8)
    const wet = ctx.createGain()
    wet.gain.value = 0.45
    p.connect(this.sfx)
    p.connect(reverb).connect(wet).connect(this.sfx)

    // 双音节鹤唳：第一声短促下切（“毕”），第二声清越悠扬上扬（“方—”）
    for (const [offset, dur, f0, f1, f2] of [
      [0.0, 0.28, 1180, 1340, 860],
      [0.36, 0.92, 920, 1280, 1120],
    ] as const) {
      const t0 = ctx.currentTime + offset
      const osc = ctx.createOscillator()
      osc.type = 'sawtooth'
      osc.frequency.setValueAtTime(f0, t0)
      osc.frequency.exponentialRampToValueAtTime(f1, t0 + dur * 0.35)
      osc.frequency.exponentialRampToValueAtTime(f2, t0 + dur)

      const bp1 = ctx.createBiquadFilter()
      bp1.type = 'bandpass'
      bp1.frequency.setValueAtTime(1450, t0)
      bp1.Q.value = 5.5

      const g = ctx.createGain()
      g.gain.setValueAtTime(0, t0)
      g.gain.linearRampToValueAtTime(0.34, t0 + 0.025)
      g.gain.exponentialRampToValueAtTime(0.001, t0 + dur)

      osc.connect(bp1).connect(g).connect(p)
      osc.start(t0)
      osc.stop(t0 + dur + 0.03)
    }

    // 讹火流焰（顺接 foxFire 丹火呼啸）
    this.foxFire(pan)
  }

  /** 九凤原文未记鸣声；九个错落低音仅作九首展示的听觉推断。 */
  jiufengCall() {
    const ctx = this.ctx
    if (!ctx) return
    for (let i = 0; i < 9; i++) {
      const t = ctx.currentTime + i * 0.13
      const out = this.panner((i % 5 - 2) * 0.18)
      out.connect(this.sfx)
      const osc = ctx.createOscillator()
      osc.type = 'sine'
      const hz = [220, 247, 294, 330, 392, 262, 294, 330, 440][i]
      osc.frequency.setValueAtTime(hz * 1.03, t)
      osc.frequency.exponentialRampToValueAtTime(hz * 0.97, t + 0.4)
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.1, t + 0.06)
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.44)
      osc.connect(gain).connect(out)
      osc.start(t)
      osc.stop(t + 0.46)
      osc.onended = () => { osc.disconnect(); gain.disconnect(); out.disconnect() }
    }
  }

  /** 蛊雕「其音如婴儿之音」的拟声；具体声调和节奏为推断。 */
  gudiaoCry() {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(0)
    out.connect(this.sfx)
    for (let i = 0; i < 3; i++) {
      const t = ctx.currentTime + i * 0.72
      const osc = ctx.createOscillator()
      osc.type = 'sawtooth'
      osc.frequency.setValueAtTime(470 + i * 30, t)
      osc.frequency.exponentialRampToValueAtTime(780 + i * 25, t + 0.18)
      osc.frequency.exponentialRampToValueAtTime(390 + i * 20, t + 0.58)
      const tremolo = ctx.createOscillator()
      tremolo.frequency.value = 6.5
      const depth = ctx.createGain()
      depth.gain.value = 22
      tremolo.connect(depth).connect(osc.frequency)
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.value = 1250
      filter.Q.value = 1.6
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.075, t + 0.09)
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.62)
      osc.connect(filter).connect(gain).connect(out)
      osc.start(t)
      tremolo.start(t)
      osc.stop(t + 0.65)
      tremolo.stop(t + 0.65)
      tremolo.onended = () => {
        osc.disconnect(); tremolo.disconnect(); depth.disconnect(); filter.disconnect(); gain.disconnect()
        if (i === 2) out.disconnect()
      }
    }
  }

  /** 鵸鵌「善笑」的短促三首应答；实际音色和节奏为艺术推断。 */
  qituLaugh() {
    const ctx = this.ctx
    if (!ctx) return
    for (let voice = 0; voice < 3; voice++) {
      const out = this.panner((voice - 1) * 0.4)
      out.connect(this.sfx)
      for (let syllable = 0; syllable < 4; syllable++) {
        const t = ctx.currentTime + voice * 0.17 + syllable * 0.19
        const osc = ctx.createOscillator()
        osc.type = 'triangle'
        const hz = 620 + voice * 125 - syllable * 35
        osc.frequency.setValueAtTime(hz * 1.25, t)
        osc.frequency.exponentialRampToValueAtTime(hz * 0.8, t + 0.13)
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.value = 1350 + voice * 180
        filter.Q.value = 1.8
        const gain = ctx.createGain()
        gain.gain.setValueAtTime(0, t)
        gain.gain.linearRampToValueAtTime(0.11, t + 0.018)
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.15)
        osc.connect(filter).connect(gain).connect(out)
        osc.start(t)
        osc.stop(t + 0.17)
      }
    }
  }

  /** 三青鸟两篇原文均未记鸣声；三声错落鸟鸣为听觉推断。 */
  qingniaoCall() {
    const ctx = this.ctx
    if (!ctx) return
    for (const [i, hz] of [1680, 2020, 1840].entries()) {
      const out = this.panner((i - 1) * 0.45)
      out.connect(this.sfx)
      const t = ctx.currentTime + i * 0.28
      const osc = ctx.createOscillator()
      osc.type = 'triangle'
      osc.frequency.setValueAtTime(hz, t)
      osc.frequency.exponentialRampToValueAtTime(hz * 1.3, t + 0.08)
      osc.frequency.exponentialRampToValueAtTime(hz * 0.9, t + 0.21)
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.11, t + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.24)
      osc.connect(gain).connect(out)
      osc.start(t)
      osc.stop(t + 0.27)
    }
  }

  /** 鴖原文未记鸣声；清短双哨仅为鸟类听觉推断。 */
  minBirdCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [offset, start, end] of [[0, 2350, 3100], [0.24, 2800, 3550]]) {
      const t = ctx.currentTime + offset
      const osc = ctx.createOscillator()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(start, t)
      osc.frequency.exponentialRampToValueAtTime(end, t + 0.11)
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.12, t + 0.018)
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.16)
      osc.connect(gain).connect(out)
      osc.start(t)
      osc.stop(t + 0.18)
    }
  }

  /** 精卫「其鸣自詨」：近似自呼「精—卫」的双声鸦鸣，音色与节奏为艺术推断。 */
  jingweiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [offset, duration, start, end] of [[0, 0.25, 920, 1140], [0.34, 0.48, 1080, 680]]) {
      const t = ctx.currentTime + offset
      const osc = ctx.createOscillator()
      osc.type = 'sawtooth'
      osc.frequency.setValueAtTime(start, t)
      osc.frequency.exponentialRampToValueAtTime(end, t + duration)
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.value = 1650
      filter.Q.value = 2.4
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.22, t + 0.025)
      gain.gain.exponentialRampToValueAtTime(0.001, t + duration)
      osc.connect(filter).connect(gain).connect(out)
      osc.start(t)
      osc.stop(t + duration + 0.03)
    }
  }

  /** 鹿蜀「其音如谣」：五声短句与柔和的声带泛音。 */
  lushuSong(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [i, degree] of [0, 4, 7, 9, 7, 4, 2, 0].entries()) {
      const t = ctx.currentTime + i * 0.32
      const hz = BASE_HZ * 2 * 2 ** (degree / 12)
      for (const [ratio, level] of [[1, 0.18], [2, 0.05], [3, 0.018]]) {
        const osc = ctx.createOscillator()
        osc.frequency.setValueAtTime(hz * ratio * 0.97, t)
        osc.frequency.exponentialRampToValueAtTime(hz * ratio, t + 0.08)
        const gain = ctx.createGain()
        gain.gain.setValueAtTime(0, t)
        gain.gain.linearRampToValueAtTime(level, t + 0.06)
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.55)
        osc.connect(gain).connect(out)
        osc.start(t)
        osc.stop(t + 0.6)
      }
    }
  }

  /** 夫诸原文未记鸣声；以清越鹿鸣与泉水轻响作交互听觉补足。 */
  fuzhuCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    const t = ctx.currentTime

    for (const [offset, duration, hz] of [[0, 0.62, 660], [0.74, 0.86, 550]]) {
      const start = t + offset
      for (const [ratio, level] of [[1, 0.17], [2, 0.045], [3, 0.012]]) {
        const voice = ctx.createOscillator()
        voice.type = 'sine'
        voice.frequency.setValueAtTime(hz * ratio * 0.88, start)
        voice.frequency.exponentialRampToValueAtTime(hz * ratio, start + 0.14)
        voice.frequency.exponentialRampToValueAtTime(hz * ratio * 0.76, start + duration)
        const gain = ctx.createGain()
        gain.gain.setValueAtTime(0, start)
        gain.gain.linearRampToValueAtTime(level, start + 0.065)
        gain.gain.exponentialRampToValueAtTime(0.001, start + duration)
        voice.connect(gain).connect(out)
        voice.start(start)
        voice.stop(start + duration + 0.03)
      }
    }

    const water = ctx.createBufferSource()
    water.buffer = this.noise(2.8)
    const filter = ctx.createBiquadFilter()
    filter.type = 'bandpass'
    filter.Q.value = 0.7
    filter.frequency.setValueAtTime(680, t)
    filter.frequency.exponentialRampToValueAtTime(1700, t + 0.8)
    filter.frequency.exponentialRampToValueAtTime(480, t + 2.7)
    const gain = ctx.createGain()
    gain.gain.setValueAtTime(0, t)
    gain.gain.linearRampToValueAtTime(0.1, t + 0.5)
    gain.gain.exponentialRampToValueAtTime(0.001, t + 2.75)
    water.connect(filter).connect(gain).connect(out)
    water.start(t)
  }

  /** 封豨粗重鼻息：据野猪习性作艺术演绎，《海内经》未记其声。 */
  fengxiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    const t = ctx.currentTime
    const duration = 1.3
    const voice = ctx.createOscillator()
    voice.type = 'sawtooth'
    voice.frequency.setValueAtTime(88, t)
    voice.frequency.exponentialRampToValueAtTime(68, t + duration)
    const throat = ctx.createBiquadFilter()
    throat.type = 'bandpass'
    throat.frequency.setValueAtTime(340, t)
    throat.frequency.exponentialRampToValueAtTime(230, t + duration)
    throat.Q.value = 2.4
    const envelope = ctx.createGain()
    envelope.gain.setValueAtTime(0, t)
    envelope.gain.linearRampToValueAtTime(0.32, t + 0.08)
    envelope.gain.linearRampToValueAtTime(0.18, t + 0.65)
    envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
    voice.connect(throat).connect(envelope)
    const breath = ctx.createBufferSource()
    breath.buffer = this.noise(duration)
    const filter = ctx.createBiquadFilter()
    filter.type = 'bandpass'
    filter.frequency.value = 720
    filter.Q.value = 0.7
    const rasp = ctx.createGain()
    rasp.gain.value = 0.18
    breath.connect(filter).connect(rasp).connect(envelope)
    envelope.connect(out)
    voice.start(t)
    voice.stop(t + duration + 0.03)
    breath.start(t)
  }

  /** 狪狪「其鸣自訆」：两拍圆润鼻音豚鸣，节律借今音，非古音复原。 */
  tongtongCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [offset, hz, duration] of [[0, 135, 0.32], [0.43, 142, 0.44]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(hz * 0.88, t)
      voice.frequency.exponentialRampToValueAtTime(hz, t + 0.06)
      voice.frequency.exponentialRampToValueAtTime(hz * 0.78, t + duration)
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.22, t + 0.035)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
      for (const [frequency, level] of [[420, 1], [1120, 0.22]]) {
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.value = frequency
        filter.Q.value = 3.8
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(filter).connect(gain).connect(envelope)
      }
      const breath = ctx.createBufferSource()
      breath.buffer = this.noise(duration)
      const lowpass = ctx.createBiquadFilter()
      lowpass.type = 'lowpass'
      lowpass.frequency.value = 650
      const gain = ctx.createGain()
      gain.gain.value = 0.1
      breath.connect(lowpass).connect(gain).connect(envelope)
      envelope.connect(out)
      voice.start(t)
      voice.stop(t + duration + 0.02)
      breath.start(t)
    }
  }

  /** 当康「其鸣自叫」：两音节鼻腔豚鸣，具体音色为艺术演绎。 */
  dangkangCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)

    for (const [offset, duration, hz, formant] of [[0, 0.34, 155, 680], [0.46, 0.58, 128, 480]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(hz * 0.85, t)
      voice.frequency.exponentialRampToValueAtTime(hz * 1.15, t + duration * 0.3)
      voice.frequency.exponentialRampToValueAtTime(hz * 0.72, t + duration)
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.28, t + 0.045)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)

      // 双共振峰保留低沉鼻音与较弱的口腔泛音。
      for (const [frequency, level] of [[formant, 1], [formant * 2.6, 0.3]]) {
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.setValueAtTime(frequency, t)
        filter.Q.value = 4.5
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(filter).connect(gain).connect(envelope)
      }
      const breath = ctx.createBufferSource()
      breath.buffer = this.noise(duration)
      const lowpass = ctx.createBiquadFilter()
      lowpass.type = 'lowpass'
      lowpass.frequency.value = 950
      const breathGain = ctx.createGain()
      breathGain.gain.value = 0.15
      breath.connect(lowpass).connect(breathGain).connect(envelope)
      envelope.connect(out)
      voice.start(t)
      voice.stop(t + duration + 0.03)
      breath.start(t)
    }
  }

  /** 英招「其音如橊」声义未定；短颤鸣的音色和音高只是演绎。 */
  yingzhaoCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const voice = ctx.createOscillator()
    const vibrato = ctx.createOscillator()
    const depth = ctx.createGain()
    const envelope = ctx.createGain()
    const filter = ctx.createBiquadFilter()
    const out = this.panner(pan)
    voice.type = 'triangle'
    voice.frequency.setValueAtTime(410, t)
    voice.frequency.exponentialRampToValueAtTime(280, t + 0.65)
    vibrato.frequency.value = 19
    depth.gain.value = 45
    vibrato.connect(depth).connect(voice.frequency)
    filter.type = 'bandpass'
    filter.frequency.value = 1100
    filter.Q.value = 0.8
    envelope.gain.setValueAtTime(0, t)
    envelope.gain.linearRampToValueAtTime(0.24, t + 0.06)
    envelope.gain.exponentialRampToValueAtTime(0.001, t + 0.7)
    voice.connect(filter).connect(envelope).connect(out).connect(this.sfx)
    voice.start(t); vibrato.start(t)
    voice.stop(t + 0.72); vibrato.stop(t + 0.72)
    voice.onended = () => {
      voice.disconnect(); vibrato.disconnect(); depth.disconnect()
      envelope.disconnect(); filter.disconnect(); out.disconnect()
    }
  }

  /** 并封原文未记鸣声；前后两声错时低哼为交互艺术补足。 */
  bingfengCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    for (const [delay, pitch, side] of [[0, 115, pan - 0.15], [0.58, 94, pan + 0.15]]) {
      const out = this.panner(Math.max(-1, Math.min(1, side)))
      out.connect(this.sfx)
      const t = ctx.currentTime + delay
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(pitch, t)
      voice.frequency.exponentialRampToValueAtTime(pitch * 0.67, t + 0.55)
      const filter = ctx.createBiquadFilter()
      filter.type = 'lowpass'
      filter.frequency.value = 520
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.26, t + 0.04)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + 0.55)
      voice.connect(filter).connect(envelope).connect(out)
      voice.start(t)
      voice.stop(t + 0.57)
      voice.onended = () => { voice.disconnect(); filter.disconnect(); envelope.disconnect(); out.disconnect() }
    }
  }

  /** 猼訑原文未记声音；据羊形补一声轻柔颤音羊鸣，非原文记载。 */
  boyiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const duration = 0.82
    const voice = ctx.createOscillator()
    voice.type = 'sawtooth'
    voice.frequency.setValueAtTime(245, t)
    voice.frequency.exponentialRampToValueAtTime(180, t + duration)
    const vibrato = ctx.createOscillator()
    vibrato.frequency.value = 13
    const depth = ctx.createGain()
    depth.gain.value = 16
    vibrato.connect(depth).connect(voice.frequency)
    const filter = ctx.createBiquadFilter()
    filter.type = 'bandpass'
    filter.frequency.setValueAtTime(1250, t)
    filter.frequency.exponentialRampToValueAtTime(850, t + duration)
    filter.Q.value = 1.3
    const envelope = ctx.createGain()
    envelope.gain.setValueAtTime(0, t)
    envelope.gain.linearRampToValueAtTime(0.20, t + 0.07)
    envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
    const out = this.panner(pan)
    voice.connect(filter).connect(envelope).connect(out).connect(this.sfx)
    voice.start(t)
    vibrato.start(t)
    voice.stop(t + duration + 0.02)
    vibrato.stop(t + duration + 0.02)
    voice.onended = () => {
      voice.disconnect(); vibrato.disconnect(); depth.disconnect()
      filter.disconnect(); envelope.disconnect(); out.disconnect()
    }
  }

  /** 耳鼠「其音如獆犬」：两声短吠，音高与节奏为听觉演绎。 */
  ershuCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [index, offset] of [0, 0.28].entries()) {
      const t = ctx.currentTime + offset
      const duration = 0.20 + index * 0.035
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(330 - index * 35, t)
      voice.frequency.exponentialRampToValueAtTime(150, t + duration)
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.setValueAtTime(1100, t)
      filter.frequency.exponentialRampToValueAtTime(560, t + duration)
      filter.Q.value = 1.5
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.24, t + 0.012)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
      voice.connect(filter).connect(envelope).connect(out)
      voice.start(t)
      voice.stop(t + duration + 0.02)
      voice.onended = () => {
        voice.disconnect()
        filter.disconnect()
        envelope.disconnect()
        if (index === 1) out.disconnect()
      }
    }
  }

  /** 天马「其鸣自訆」：借今音的两个音节作犬声演绎，非古音复原。 */
  tianmaCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [offset, duration, hz, formant] of [[0, 0.38, 290, 1700], [0.48, 0.52, 220, 780]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(hz * 0.78, t)
      voice.frequency.exponentialRampToValueAtTime(hz, t + 0.05)
      voice.frequency.exponentialRampToValueAtTime(hz * 0.62, t + duration)
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.setValueAtTime(formant, t)
      filter.frequency.exponentialRampToValueAtTime(formant * 0.7, t + duration)
      filter.Q.value = 1.8
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.3, t + 0.025)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
      voice.connect(filter).connect(envelope).connect(out)
      voice.start(t)
      voice.stop(t + duration + 0.03)
    }
  }

  /** 乘黄原文未记鸣声；据「状如狐」补一声短促轻鸣，音高与音色为交互演绎。 */
  chenghuangCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    const t = ctx.currentTime
    const duration = 0.48
    const voice = ctx.createOscillator()
    voice.type = 'triangle'
    voice.frequency.setValueAtTime(590, t)
    voice.frequency.exponentialRampToValueAtTime(840, t + 0.07)
    voice.frequency.exponentialRampToValueAtTime(460, t + duration)
    const filter = ctx.createBiquadFilter()
    filter.type = 'bandpass'
    filter.frequency.value = 1400
    filter.Q.value = 1.2
    const gain = ctx.createGain()
    gain.gain.setValueAtTime(0, t)
    gain.gain.linearRampToValueAtTime(0.2, t + 0.025)
    gain.gain.exponentialRampToValueAtTime(0.001, t + duration)
    voice.connect(filter).connect(gain).connect(out)
    voice.start(t)
    voice.stop(t + duration + 0.03)
    voice.onended = () => { voice.disconnect(); filter.disconnect(); gain.disconnect(); out.disconnect() }
  }

  /** 天狗「其音如榴榴」：两声相连的颤音；郭璞注「或作猫猫」，故取近猫鸣的音色，音高与节奏为听觉演绎。 */
  tiangouCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)

    for (const [offset, duration, hz] of [[0, 0.44, 560], [0.5, 0.62, 640]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(hz * 0.8, t)
      voice.frequency.exponentialRampToValueAtTime(hz, t + duration * 0.3)
      voice.frequency.exponentialRampToValueAtTime(hz * 0.68, t + duration)

      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.26, t + 0.05)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)

      // 猫鸣由「i」滑向「u」：两个共振峰随音节下移。
      for (const [start, end, level] of [[1500, 760, 1], [3200, 1900, 0.4]]) {
        const formant = ctx.createBiquadFilter()
        formant.type = 'bandpass'
        formant.frequency.setValueAtTime(start, t)
        formant.frequency.exponentialRampToValueAtTime(end, t + duration)
        formant.Q.value = 3.2
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(formant).connect(gain).connect(envelope)
      }

      // 「榴」的舌颤：快速振幅调制。
      const trill = ctx.createGain()
      trill.gain.value = 0.72
      const flutter = ctx.createOscillator()
      flutter.frequency.value = 23
      const depth = ctx.createGain()
      depth.gain.value = 0.28
      flutter.connect(depth).connect(trill.gain)
      envelope.connect(trill).connect(out)

      voice.start(t)
      flutter.start(t)
      voice.stop(t + duration + 0.03)
      flutter.stop(t + duration + 0.03)
    }
  }

  /** 汤谷载日乌的两声短鸣；正文未记鸣声，具体声色为艺术演绎。 */
  jinwuCall() {
    const ctx = this.ctx
    if (!ctx) return
    for (const [i, pitch] of [255, 225].entries()) {
      const t = ctx.currentTime + i * 0.48
      const out = this.panner(i === 0 ? -0.12 : 0.12)
      out.connect(this.sfx)
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(pitch * 1.12, t)
      voice.frequency.exponentialRampToValueAtTime(pitch, t + 0.075)
      voice.frequency.exponentialRampToValueAtTime(pitch * 0.78, t + 0.30)
      const tone = ctx.createBiquadFilter()
      tone.type = 'bandpass'
      tone.frequency.setValueAtTime(1250, t)
      tone.frequency.exponentialRampToValueAtTime(780, t + 0.30)
      tone.Q.value = 1.5
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.22, t + 0.025)
      gain.gain.exponentialRampToValueAtTime(0.0005, t + 0.34)
      voice.connect(tone).connect(gain).connect(out)
      voice.onended = () => { voice.disconnect(); tone.disconnect(); gain.disconnect(); out.disconnect() }
      voice.start(t)
      voice.stop(t + 0.36)
    }
  }

  /** 屏蓬左右首相应的低吟；本条没有记载鸣声。 */
  screenPengCall() {
    const ctx = this.ctx
    if (!ctx) return
    for (const [i, pan] of [-0.3, 0.3].entries()) {
      const t = ctx.currentTime + i * 0.42
      const out = this.panner(pan)
      out.connect(this.sfx)
      const voice = ctx.createOscillator()
      voice.type = 'triangle'
      voice.frequency.setValueAtTime(i === 0 ? 145 : 160, t)
      voice.frequency.exponentialRampToValueAtTime(i === 0 ? 106 : 118, t + 0.32)
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.14, t + 0.045)
      gain.gain.exponentialRampToValueAtTime(0.0005, t + 0.36)
      voice.connect(gain).connect(out)
      voice.start(t)
      voice.stop(t + 0.38)
    }
  }

  /** 凤凰「自歌自舞」的和鸣；具体音阶与音色为艺术补足。 */
  fenghuangCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [i, pitch] of [659.25, 783.99, 987.77, 783.99].entries()) {
      const t = ctx.currentTime + i * 0.19
      const tone = ctx.createOscillator()
      tone.type = 'triangle'
      tone.frequency.setValueAtTime(pitch * 0.93, t)
      tone.frequency.exponentialRampToValueAtTime(pitch, t + 0.055)
      tone.frequency.exponentialRampToValueAtTime(pitch * 0.98, t + 0.30)
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.085, t + 0.025)
      gain.gain.exponentialRampToValueAtTime(0.0005, t + 0.31)
      tone.connect(gain).connect(out)
      tone.start(t)
      tone.stop(t + 0.33)
    }
  }

  /** 鬿雀的短促粗鸣为听觉补足；本条古经没有记载鸣声。 */
  qiqueCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const delay of [0, 0.22]) {
      const t = ctx.currentTime + delay
      const tone = ctx.createOscillator()
      tone.type = 'sawtooth'
      tone.frequency.setValueAtTime(520, t)
      tone.frequency.exponentialRampToValueAtTime(290, t + 0.19)
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.value = 1500
      filter.Q.value = 1.5
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.13, t + 0.012)
      gain.gain.exponentialRampToValueAtTime(0.0005, t + 0.20)
      tone.connect(filter).connect(gain).connect(out)
      tone.start(t)
      tone.stop(t + 0.22)
    }
  }

  /** 驺吾的温和猫科低吟，属于听觉补足；《海内北经》未记鸣声。 */
  zouwuCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    const t = ctx.currentTime
    for (const [ratio, level] of [[1, 0.16], [2, 0.065], [3, 0.025]]) {
      const tone = ctx.createOscillator()
      tone.type = 'sine'
      tone.frequency.setValueAtTime(125 * ratio, t)
      tone.frequency.exponentialRampToValueAtTime(82 * ratio, t + 0.7)
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(level, t + 0.1)
      gain.gain.exponentialRampToValueAtTime(0.0005, t + 0.85)
      tone.connect(gain).connect(out)
      tone.start(t)
      tone.stop(t + 0.9)
    }
  }

  /** 狰「其音如击石」：石块短击与不成整数比的石磬余振，节奏为交互演绎。 */
  zhengCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)

    for (const [offset, pitch, strength] of [[0, 740, 1], [0.3, 610, 0.78], [0.72, 880, 0.9]]) {
      const t = ctx.currentTime + offset
      for (const [ratio, level, decay] of [[1, 0.2, 0.85], [1.47, 0.1, 0.52], [2.09, 0.05, 0.28], [2.71, 0.025, 0.16]]) {
        const tone = ctx.createOscillator()
        tone.type = 'sine'
        tone.frequency.setValueAtTime(pitch * ratio * 1.015, t)
        tone.frequency.exponentialRampToValueAtTime(pitch * ratio, t + 0.025)
        const gain = ctx.createGain()
        gain.gain.setValueAtTime(0, t)
        gain.gain.linearRampToValueAtTime(level * strength, t + 0.003)
        gain.gain.exponentialRampToValueAtTime(0.0005, t + decay)
        tone.connect(gain).connect(out)
        tone.start(t)
        tone.stop(t + decay + 0.03)
      }

      const impact = ctx.createBufferSource()
      impact.buffer = this.noise(0.065)
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.value = 2400
      filter.Q.value = 0.8
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.12 * strength, t + 0.002)
      gain.gain.exponentialRampToValueAtTime(0.0005, t + 0.06)
      impact.connect(filter).connect(gain).connect(out)
      impact.start(t)
    }
  }

  /**
   * 孟极「其鸣自呼」：两音节豹类喉音，音高走势按今音 mèng（降）jí（升）模拟，属听觉演绎。
   * 延后 1.9 秒发声，对应 alert 动作中伏地之后昂首的时刻。
   */
  mengjiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    const syllables = [
      { offset: 1.9, duration: 0.5, from: 250, to: 150, formants: [[420, 1], [1150, 0.35]] },
      { offset: 2.5, duration: 0.46, from: 205, to: 300, formants: [[340, 0.75], [2250, 0.55]] },
    ]

    for (const { offset, duration, from, to, formants } of syllables) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(from, t)
      voice.frequency.exponentialRampToValueAtTime(to, t + duration)
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.3, t + 0.05)
      envelope.gain.setValueAtTime(0.3, t + duration * 0.55)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
      for (const [frequency, level] of formants) {
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.value = frequency
        filter.Q.value = 5
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(filter).connect(gain).connect(envelope)
      }
      // 喉间气声，让两音节偏兽吼而非人声。
      const breath = ctx.createBufferSource()
      breath.buffer = this.noise(duration)
      const lowpass = ctx.createBiquadFilter()
      lowpass.type = 'lowpass'
      lowpass.frequency.value = 1300
      const breathGain = ctx.createGain()
      breathGain.gain.value = 0.2
      breath.connect(lowpass).connect(breathGain).connect(envelope)
      envelope.connect(out)
      voice.start(t)
      voice.stop(t + duration + 0.03)
      breath.start(t)
    }
  }

  /** 《中山经》未记朏朏鸣声；轻柔呼噜与一声短咪是据「状如狸」「已忧」的听觉演绎。 */
  feifeiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const duration = 2.6
    const out = this.panner(pan)
    out.connect(this.sfx)

    const purr = ctx.createOscillator()
    purr.type = 'triangle'
    purr.frequency.setValueAtTime(58, t)
    purr.frequency.linearRampToValueAtTime(52, t + duration)
    const filter = ctx.createBiquadFilter()
    filter.type = 'lowpass'
    filter.frequency.value = 420
    const flutter = ctx.createGain()
    flutter.gain.value = 0.5
    const rate = ctx.createOscillator()
    rate.frequency.value = 23
    const depth = ctx.createGain()
    depth.gain.value = 0.5
    rate.connect(depth).connect(flutter.gain)
    const envelope = ctx.createGain()
    envelope.gain.setValueAtTime(0, t)
    envelope.gain.linearRampToValueAtTime(0.3, t + 0.5)
    envelope.gain.setValueAtTime(0.3, t + duration - 0.9)
    envelope.gain.exponentialRampToValueAtTime(0.0005, t + duration)
    purr.connect(filter).connect(flutter).connect(envelope).connect(out)
    purr.start(t)
    rate.start(t)
    purr.stop(t + duration + 0.03)
    rate.stop(t + duration + 0.03)

    const mew = ctx.createOscillator()
    mew.type = 'sine'
    const start = t + 0.28
    mew.frequency.setValueAtTime(620, start)
    mew.frequency.exponentialRampToValueAtTime(860, start + 0.12)
    mew.frequency.exponentialRampToValueAtTime(540, start + 0.46)
    const gain = ctx.createGain()
    gain.gain.setValueAtTime(0, start)
    gain.gain.linearRampToValueAtTime(0.07, start + 0.06)
    gain.gain.exponentialRampToValueAtTime(0.0005, start + 0.5)
    mew.connect(gain).connect(out)
    mew.start(start)
    mew.stop(start + 0.53)
  }

  /** 诸怀「其音如鸣雁」：分节鼻音雁叫，音高与节奏为听觉演绎。 */
  zhuhuaiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [offset, duration, pitch] of [[0, 0.46, 390], [0.6, 0.58, 330], [1.4, 0.42, 420]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(pitch * 0.8, t)
      voice.frequency.exponentialRampToValueAtTime(pitch * 1.18, t + 0.08)
      voice.frequency.exponentialRampToValueAtTime(pitch * 0.76, t + duration)
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.23, t + 0.045)
      envelope.gain.setValueAtTime(0.19, t + duration * 0.6)
      envelope.gain.exponentialRampToValueAtTime(0.0005, t + duration)
      for (const [frequency, level] of [[950, 1], [1800, 0.4]]) {
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.value = frequency
        filter.Q.value = 3.5
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(filter).connect(gain).connect(envelope)
      }
      envelope.connect(out)
      voice.start(t)
      voice.stop(t + duration + 0.02)
    }
  }

  /** 讙「其音如夺百声」：错落重叠的短鸣与啸声，具体音色为听觉演绎。 */
  huanCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    const voices: [number, number, number, number, OscillatorType][] = [
      [0, 0.82, 260, 470, 'sawtooth'],
      [0.12, 0.34, 1250, 760, 'sine'],
      [0.35, 0.62, 540, 310, 'triangle'],
      [0.65, 0.44, 830, 1430, 'sine'],
    ]
    for (const [offset, duration, from, to, type] of voices) {
      const t = ctx.currentTime + offset
      const tone = ctx.createOscillator()
      tone.type = type
      tone.frequency.setValueAtTime(from, t)
      tone.frequency.exponentialRampToValueAtTime(to, t + duration)
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.value = type === 'sawtooth' ? 1150 : 2300
      filter.Q.value = 1.5
      const gain = ctx.createGain()
      gain.gain.setValueAtTime(0, t)
      gain.gain.linearRampToValueAtTime(0.22, t + 0.025)
      gain.gain.exponentialRampToValueAtTime(0.001, t + duration)
      const vibrato = ctx.createOscillator()
      vibrato.frequency.value = 12 + offset * 9
      const depth = ctx.createGain()
      depth.gain.value = from * 0.045
      vibrato.connect(depth).connect(tone.frequency)
      tone.connect(filter).connect(gain).connect(out)
      tone.start(t)
      vibrato.start(t)
      tone.stop(t + duration + 0.03)
      vibrato.stop(t + duration + 0.03)
    }
  }

  /** 《海内北经》未记穷奇鸣声；低沉虎啸与气声为「状如虎」的交互艺术补足。 */
  qiongqiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const t = ctx.currentTime
    const duration = 1.8
    const out = this.panner(pan)
    out.connect(this.sfx)

    const voice = ctx.createOscillator()
    voice.type = 'sawtooth'
    voice.frequency.setValueAtTime(86, t)
    voice.frequency.exponentialRampToValueAtTime(124, t + 0.22)
    voice.frequency.exponentialRampToValueAtTime(57, t + duration)
    const envelope = ctx.createGain()
    envelope.gain.setValueAtTime(0, t)
    envelope.gain.linearRampToValueAtTime(0.4, t + 0.1)
    envelope.gain.linearRampToValueAtTime(0.3, t + 0.55)
    envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)

    // 宽共振峰模拟胸腔和喉部，快速振幅调制带出粗粝的咆哮质感。
    for (const [hz, level] of [[290, 1], [850, 0.45]]) {
      const filter = ctx.createBiquadFilter()
      filter.type = 'bandpass'
      filter.frequency.setValueAtTime(hz, t)
      filter.frequency.exponentialRampToValueAtTime(hz * 0.65, t + duration)
      filter.Q.value = 1.8
      const gain = ctx.createGain()
      gain.gain.value = level
      voice.connect(filter).connect(gain).connect(envelope)
    }
    const roughness = ctx.createGain()
    roughness.gain.value = 0.78
    const rasp = ctx.createOscillator()
    rasp.frequency.setValueAtTime(27, t)
    rasp.frequency.linearRampToValueAtTime(18, t + duration)
    const raspDepth = ctx.createGain()
    raspDepth.gain.value = 0.19
    rasp.connect(raspDepth).connect(roughness.gain)
    envelope.connect(roughness).connect(out)

    const breath = ctx.createBufferSource()
    breath.buffer = this.noise(duration)
    const lowpass = ctx.createBiquadFilter()
    lowpass.type = 'lowpass'
    lowpass.frequency.value = 1350
    const breathGain = ctx.createGain()
    breathGain.gain.value = 0.22
    breath.connect(lowpass).connect(breathGain).connect(envelope)

    voice.start(t)
    rasp.start(t)
    breath.start(t)
    voice.stop(t + duration + 0.03)
    rasp.stop(t + duration + 0.03)
  }

  /** 《西次三经》未记陆吾鸣声；据「虎身」沿用合成虎啸，属于交互艺术补足。 */
  luwuCall(pan = 0) {
    this.qiongqiCall(pan)
  }

  /** 《海内西经》未记开明兽鸣声；据「类虎」沿用合成虎啸，属于交互艺术补足。 */
  kaimingCall(pan = 0) {
    this.qiongqiCall(pan)
  }

  /** 狸力「其音如狗吠」：起音陡、音高速降的短吠；三声节奏与音高为交互演绎。 */
  liliCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)

    for (const [offset, duration, hz] of [[0, 0.15, 410], [0.24, 0.13, 450], [0.62, 0.2, 370]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(hz, t)
      voice.frequency.exponentialRampToValueAtTime(hz * 1.3, t + duration * 0.18)
      voice.frequency.exponentialRampToValueAtTime(hz * 0.55, t + duration)
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.34, t + 0.012)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)

      // 两道共振峰给出张口吠叫的「汪」，比豚鸣的鼻音明亮。
      for (const [frequency, level] of [[1050, 1], [2500, 0.45]]) {
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.setValueAtTime(frequency * 1.2, t)
        filter.frequency.exponentialRampToValueAtTime(frequency * 0.8, t + duration)
        filter.Q.value = 3.2
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(filter).connect(gain).connect(envelope)
      }
      const rasp = ctx.createBufferSource()
      rasp.buffer = this.noise(duration)
      const highpass = ctx.createBiquadFilter()
      highpass.type = 'highpass'
      highpass.frequency.value = 1400
      const raspGain = ctx.createGain()
      raspGain.gain.value = 0.12
      rasp.connect(highpass).connect(raspGain).connect(envelope)
      envelope.connect(out)
      voice.start(t)
      voice.stop(t + duration + 0.03)
      rasp.start(t)
    }
  }

  /** 狍鸮「其音如婴儿」：滑音与双共振峰合成啼声，不使用真人录音。 */
  taotieCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [offset, duration, hz] of [[0, 0.65, 520], [0.83, 0.85, 610]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      voice.frequency.setValueAtTime(hz * 0.8, t)
      voice.frequency.linearRampToValueAtTime(hz * 1.2, t + 0.17)
      voice.frequency.exponentialRampToValueAtTime(hz * 0.72, t + duration)
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.24, t + 0.08)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
      envelope.connect(out)
      for (const [frequency, level] of [[1100, 1], [2300, 0.35]]) {
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.value = frequency
        filter.Q.value = 2.1
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(filter).connect(gain).connect(envelope)
      }
      const vibrato = ctx.createOscillator()
      vibrato.frequency.value = 6
      const depth = ctx.createGain()
      depth.gain.value = 14
      vibrato.connect(depth).connect(voice.frequency)
      voice.start(t)
      vibrato.start(t)
      voice.stop(t + duration + 0.03)
      vibrato.stop(t + duration + 0.03)
    }
  }

  /** 獙獙「其音如鸿雁」：三声上扬的鼻音雁鸣；声数、音高与共振峰为听感推断，不使用真实录音。 */
  bibiCall(pan = 0) {
    const ctx = this.ctx
    if (!ctx) return
    const out = this.panner(pan)
    out.connect(this.sfx)
    for (const [offset, duration, hz] of [[0, 0.34, 340], [0.46, 0.34, 390], [0.95, 0.6, 360]]) {
      const t = ctx.currentTime + offset
      const voice = ctx.createOscillator()
      voice.type = 'sawtooth'
      // 雁鸣的「嘎-昂」：起音陡升后略回落，尾音下滑。
      voice.frequency.setValueAtTime(hz * 0.72, t)
      voice.frequency.exponentialRampToValueAtTime(hz * 1.18, t + 0.07)
      voice.frequency.linearRampToValueAtTime(hz, t + duration * 0.6)
      voice.frequency.exponentialRampToValueAtTime(hz * 0.8, t + duration)
      const envelope = ctx.createGain()
      envelope.gain.setValueAtTime(0, t)
      envelope.gain.linearRampToValueAtTime(0.26, t + 0.03)
      envelope.gain.linearRampToValueAtTime(0.18, t + duration * 0.6)
      envelope.gain.exponentialRampToValueAtTime(0.001, t + duration)
      envelope.connect(out)
      // 窄高共振峰带出禽类鸣管的鼻音，有别于走兽的胸腔低频。
      for (const [frequency, level] of [[950, 1], [1900, 0.7], [3100, 0.25]]) {
        const filter = ctx.createBiquadFilter()
        filter.type = 'bandpass'
        filter.frequency.value = frequency
        filter.Q.value = 3.2
        const gain = ctx.createGain()
        gain.gain.value = level
        voice.connect(filter).connect(gain).connect(envelope)
      }
      voice.start(t)
      voice.stop(t + duration + 0.03)
    }
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
