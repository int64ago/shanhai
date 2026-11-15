import type { BeastRecipeSpec } from '../src/app/beastSpec.ts'

/** Keep historical optimizer defaults unless a recipe explicitly overrides them. */
export function resolveCompressionArgs(value: BeastRecipeSpec['compression']): string[] {
  if (value === undefined) return []
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('recipe.compression must be an object')
  }
  const allowed = new Set(['weld', 'resample', 'meshoptLevel'])
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new Error(`Unknown recipe.compression option: ${key}`)
  }
  const args: string[] = []
  for (const key of ['weld', 'resample'] as const) {
    if (value[key] === undefined) continue
    if (typeof value[key] !== 'boolean') throw new Error(`recipe.compression.${key} must be boolean`)
    args.push(`--${key}`, String(value[key]))
  }
  if (value.meshoptLevel !== undefined) {
    if (value.meshoptLevel !== 'medium' && value.meshoptLevel !== 'high') {
      throw new Error('recipe.compression.meshoptLevel must be medium or high')
    }
    args.push('--meshopt-level', value.meshoptLevel)
  }
  return args
}
