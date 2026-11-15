import { Component, Suspense, useCallback, useEffect, useState, type ReactNode } from 'react'
import { Canvas } from '@react-three/fiber'
import { ContactShadows, OrbitControls, PerformanceMonitor, useGLTF, useProgress } from '@react-three/drei'
import { NoToneMapping, SRGBColorSpace } from 'three'
import { useApp, useQuality } from '../app/store'
import { INK } from '../systems/ink/palette'
import { getBeastComponent, resetBeastComponent } from './beastRegistry'
import { CameraRig } from './CameraRig'
import { Effects } from './Effects'
import { Mist } from './Mist'
import { Mountains } from './Mountains'
import { PALETTE } from './palette'
import { PaperGround } from './PaperGround'
import { Sky } from './Sky'

interface ErrorBoundaryProps {
  onError: (error: Error) => void
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
}

class BeastErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error) {
    this.props.onError(error)
  }

  render() {
    if (this.state.hasError) return null
    return this.props.children
  }
}

function SuspenseTracker({ onChange }: { onChange: (loading: boolean) => void }) {
  useEffect(() => {
    onChange(true)
    return () => onChange(false)
  }, [onChange])
  return null
}

function BeastReadyBeacon({
  readyKey,
  onReady,
}: {
  readyKey: string
  onReady: (key: string) => void
}) {
  useEffect(() => {
    onReady(readyKey)
  }, [readyKey, onReady])
  return null
}

function ActiveBeast({
  id,
  readyKey,
  onReady,
}: {
  id: string
  readyKey: string
  onReady: (key: string) => void
}) {
  const BeastComponent = getBeastComponent(id)
  return (
    <>
      <BeastComponent />
      <BeastReadyBeacon readyKey={readyKey} onReady={onReady} />
    </>
  )
}

function StageStatus({
  suspending,
  error,
  onRetry,
}: {
  suspending: boolean
  error: Error | null
  onRetry: (failedUrls: string[]) => void
}) {
  const { active, progress, errors } = useProgress()

  if (error) {
    return (
      <div className="stage-status stage-error" role="alert">
        <span>神兽现世受阻，未能载入模型</span>
        <button className="stage-retry" onClick={() => onRetry(errors)}>
          重试加载
        </button>
      </div>
    )
  }

  if (!suspending && !active) return null

  const pct = progress > 0 && progress < 100 ? ` · ${Math.round(progress)}%` : ''
  return (
    <div className="stage-status stage-loading" role="status" aria-live="polite">
      <span>展卷召兽{pct}</span>
    </div>
  )
}

export function Stage() {
  const { dpr } = useQuality()
  const stepQuality = useApp((s) => s.stepQuality)
  const selected = useApp((s) => s.selected)
  const [suspending, setSuspending] = useState(false)
  const [errorState, setErrorState] = useState<{ key: string; error: Error } | null>(null)
  const [retryKey, setRetryKey] = useState(0)
  const [readyKey, setReadyKey] = useState<string | null>(null)

  const activeKey = `${selected}:${retryKey}`
  const error = errorState?.key === activeKey ? errorState.error : null
  const stageState = error ? 'error' : readyKey === activeKey ? 'ready' : 'loading'

  const handleBoundaryError = useCallback(
    (err: Error) => {
      setErrorState({ key: activeKey, error: err })
    },
    [activeKey],
  )

  const handleRetry = useCallback(
    (failedUrls: string[]) => {
      for (const url of failedUrls) {
        try {
          useGLTF.clear(url)
        } catch {
          // ignore invalid or uncached path
        }
      }
      for (const part of ['body', 'head', 'tail', 'wing', 'leg']) {
        useGLTF.clear(`/models/${selected}/${part}.glb`)
      }
      useGLTF.clear('/models/_placeholder/fox.glb')
      resetBeastComponent(selected)
      setErrorState(null)
      setRetryKey((k) => k + 1)
    },
    [selected],
  )

  return (
    <>
      <Canvas
        dpr={[1, dpr]}
        camera={{ position: [3.2, 1.3, 3.8], fov: 32, near: 0.1, far: 1000 }}
        // 色调映射交给后期的 AgX，渲染器本身不做
        gl={{ antialias: false, toneMapping: NoToneMapping, outputColorSpace: SRGBColorSpace }}
      >
        <PerformanceMonitor onDecline={() => stepQuality(-1)} onIncline={() => stepQuality(1)} flipflops={3} />
        <CameraRig />
        <fog attach="fog" args={[PALETTE.mist, 10, 44]} />

        <Sky />
        <Mountains />
        <Mist />

        <PaperGround />
        <ContactShadows position={[0, 0.005, 0]} color={INK.ink} opacity={0.45} scale={10} blur={2.2} far={2} resolution={512} />
        <BeastErrorBoundary key={activeKey} onError={handleBoundaryError}>
          <Suspense fallback={<SuspenseTracker onChange={setSuspending} />}>
            <ActiveBeast id={selected} readyKey={activeKey} onReady={setReadyKey} />
          </Suspense>
        </BeastErrorBoundary>
        <Effects />

        <OrbitControls
          makeDefault
          target={[0, 0.6, 0]}
          enablePan={false}
          enableDamping
          minDistance={2.2}
          maxDistance={9}
          minPolarAngle={0.6}
          maxPolarAngle={Math.PI / 2 - 0.08}
        />
      </Canvas>
      <span hidden data-stage-beast={selected} data-stage-state={stageState} />
      <StageStatus suspending={suspending} error={error} onRetry={handleRetry} />
    </>
  )
}
