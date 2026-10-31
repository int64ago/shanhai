import { create } from 'zustand'
import type { BeastRegion } from './beasts'
import { audio } from '../systems/audio/AudioEngine'

export type Quality = 'high' | 'medium' | 'low'

/** 通用动作槽：每只神兽把自己的动作映射到这几个槽上 */
export type BeastAction = 'idle' | 'walk' | 'special'

export type RegionFilter = 'all' | 'ready' | BeastRegion

export interface QualitySettings {
  dpr: number
  multisampling: number
  mistLayers: number
}

export const QUALITY: Record<Quality, QualitySettings> = {
  high: { dpr: 2, multisampling: 4, mistLayers: 6 },
  medium: { dpr: 1.5, multisampling: 2, mistLayers: 4 },
  low: { dpr: 1, multisampling: 0, mistLayers: 2 },
}

const ORDER: Quality[] = ['low', 'medium', 'high']

interface AppState {
  quality: Quality
  /** 用户手动锁定后不再自动升降档 */
  qualityLocked: boolean
  setQuality: (q: Quality, lock?: boolean) => void
  stepQuality: (dir: 1 | -1) => void

  selected: string
  select: (id: string) => void

  regionFilter: RegionFilter
  setRegionFilter: (f: RegionFilter) => void

  catalogOpen: boolean
  setCatalogOpen: (open: boolean) => void

  narrating: boolean
  toggleNarration: () => void
  stopNarration: () => void

  action: BeastAction
  setAction: (a: BeastAction) => void

  muted: boolean
  audioUnlocked: boolean
  toggleMuted: () => void
  unlockAudio: () => void
}

// 调试用：?beast=<id>&action=walk|special 直接切到对应神兽与动作，方便截图验收
function initialBeast(): string {
  return new URLSearchParams(location.search).get('beast') || 'jiuweihu'
}

function initialAction(): BeastAction {
  const a = new URLSearchParams(location.search).get('action')
  return a === 'walk' || a === 'special' ? a : 'idle'
}

function readMuted(): boolean {
  try {
    return localStorage.getItem('shanhai:muted') === '1'
  } catch {
    return false
  }
}

export const useApp = create<AppState>((set, get) => ({
  quality: 'high',
  qualityLocked: false,
  setQuality: (quality, lock = true) => set({ quality, qualityLocked: lock }),
  stepQuality: (dir) => {
    const { quality, qualityLocked } = get()
    if (qualityLocked) return
    const next = ORDER[ORDER.indexOf(quality) + dir]
    if (next) set({ quality: next })
  },

  selected: initialBeast(),
  select: (selected) => {
    const wasNarrating = get().narrating
    if (wasNarrating) {
      audio.stopNarration()
    }
    set({ selected, action: 'idle', narrating: false })
  },

  regionFilter: 'all',
  setRegionFilter: (regionFilter) => set({ regionFilter }),

  catalogOpen: false,
  setCatalogOpen: (catalogOpen) => set({ catalogOpen }),

  narrating: false,
  toggleNarration: () => {
    const { narrating, selected, muted } = get()
    if (narrating) {
      audio.stopNarration()
      set({ narrating: false })
      return
    }
    if (muted) {
      try {
        localStorage.setItem('shanhai:muted', '0')
      } catch {
        // ignore
      }
      audio.setMuted(false)
      set({ muted: false })
    }
    set({ narrating: true, audioUnlocked: true })
    void audio.playNarration(selected, () => {
      set({ narrating: false })
    })
  },
  stopNarration: () => {
    audio.stopNarration()
    set({ narrating: false })
  },

  action: initialAction(),
  setAction: (action) => set({ action }),

  muted: readMuted(),
  audioUnlocked: false,
  toggleMuted: () => {
    const muted = !get().muted
    try {
      localStorage.setItem('shanhai:muted', muted ? '1' : '0')
    } catch {
      // 隐私模式下写不了，忽略
    }
    set({ muted })
  },
  unlockAudio: () => set({ audioUnlocked: true }),
}))

export const useQuality = () => QUALITY[useApp((s) => s.quality)]
