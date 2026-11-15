import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

type BeastModule = Record<string, unknown>
type BeastModuleLoader = () => Promise<{ default: ComponentType }>

const BEAST_MODULES = import.meta.glob<BeastModule>('../beasts/*/*.tsx')

function toComponentName(id: string): string {
  return id
    .split('_')
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join('')
}

function buildLoaders(): Record<string, BeastModuleLoader> {
  const loaders: Record<string, BeastModuleLoader> = {}
  const entries = Object.entries(BEAST_MODULES).sort(([a], [b]) => a.localeCompare(b))

  for (const [path, importModule] of entries) {
    const match = /^\.\.\/beasts\/([^/]+)\/([^/]+)\.tsx$/.exec(path)
    if (!match) continue
    const [, id, fileStem] = match
    const expectedName = toComponentName(id)
    // Prefer the canonical <PascalCaseId>.tsx entry if multiple files exist in a folder
    if (loaders[id] && fileStem !== expectedName) continue

    loaders[id] = async () => {
      const mod = await importModule()
      const candidate =
        (typeof mod.default === 'function' ? mod.default : undefined) ??
        (typeof mod[expectedName] === 'function' ? mod[expectedName] : undefined) ??
        (typeof mod[fileStem] === 'function' ? mod[fileStem] : undefined) ??
        Object.values(mod).find((value) => typeof value === 'function')

      if (typeof candidate !== 'function') {
        throw new Error(`Beast module ${path} does not export a React component`)
      }
      return { default: candidate as ComponentType }
    }
  }

  return loaders
}

const PLACEHOLDER_LOADER: BeastModuleLoader = async () => {
  const mod = await import('./PlaceholderBeast')
  return { default: mod.PlaceholderBeast }
}

const BEAST_LOADERS = buildLoaders()
const componentCache = new Map<string, LazyExoticComponent<ComponentType>>()

export function getBeastComponent(id: string): LazyExoticComponent<ComponentType> {
  const key = Object.hasOwn(BEAST_LOADERS, id) ? id : '_placeholder'
  let component = componentCache.get(key)
  if (!component) {
    const loader = BEAST_LOADERS[key] ?? PLACEHOLDER_LOADER
    component = lazy(loader)
    componentCache.set(key, component)
  }
  return component
}

export function resetBeastComponent(id: string): void {
  const key = Object.hasOwn(BEAST_LOADERS, id) ? id : '_placeholder'
  componentCache.delete(key)
}
