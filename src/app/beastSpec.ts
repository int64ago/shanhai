import type { BeastArchetype } from './beasts'

export interface BeastSourceQuote {
  book: string
  text: string
}

export interface BeastInferredNote {
  item: string
  basis: string
}

export interface BeastPartSpec {
  id: string
  /** Relative path to Rodin job JSON, e.g. "pipeline/rodin/jobs/jiuweihu-body-i2m.json" */
  job?: string
  /** Optional raw/<jobId> directory name override (defaults to job JSON's `id`) */
  jobId?: string
  instances?: number
  /** Target normalization length in meters for build_beast.sh */
  length?: number
  /** Texture max size when compressed by gltf-transform (default: 2048 for body, 1024 for parts) */
  texSize?: number
}

export interface BeastRecipeSpec {
  mode?: 'archetype' | 'custom'
  bodyLength?: number
  trimTail?: boolean
  /** Relative to pipeline/blender/ or repo root */
  prepareScript?: string
  /** Relative to pipeline/blender/ or repo root */
  rigScript?: string
  /** Relative to repo root */
  qaScript?: string
}

export interface BeastContentSpec {
  id: string
  name: string
  archetype: BeastArchetype
  source: BeastSourceQuote[]
  inferred: BeastInferredNote[]
  parts?: BeastPartSpec[]
  recipe?: BeastRecipeSpec
  scale?: Record<string, unknown>
  palette?: Record<string, unknown>
  actions?: string[]
  sounds?: Record<string, unknown>
  references?: { url: string; note: string }[]
  production?: Record<string, unknown>
  sourceVerification?: Record<string, unknown>
}

export function toBeastComponentName(id: string): string {
  return id
    .split('_')
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join('')
}
