import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, PerformanceMonitor } from '@react-three/drei'
import { NoToneMapping, SRGBColorSpace } from 'three'
import { useApp, useQuality } from '../app/store'
import { PALETTE } from './palette'
import { Sky } from './Sky'
import { Mountains } from './Mountains'
import { Mist } from './Mist'
import { ContactShadows } from '@react-three/drei'
import { PaperGround } from './PaperGround'
import { INK } from '../systems/ink/palette'
import { Effects } from './Effects'
import { PlaceholderBeast } from './PlaceholderBeast'
import { Jiuweihu } from '../beasts/jiuweihu/Jiuweihu'
import { Dijiang } from '../beasts/dijiang/Dijiang'
import { Bo } from '../beasts/bo/Bo'
import { Bifang } from '../beasts/bifang/Bifang'
import { Lushu } from '../beasts/lushu/Lushu'
import { CameraRig } from './CameraRig'

export function Stage() {
  const { dpr } = useQuality()
  const stepQuality = useApp((s) => s.stepQuality)
  const selected = useApp((s) => s.selected)

  return (
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
      <Suspense fallback={null}>
        {selected === 'jiuweihu' ? (
          <Jiuweihu />
        ) : selected === 'dijiang' ? (
          <Dijiang />
        ) : selected === 'bo' ? (
          <Bo />
        ) : selected === 'bifang' ? (
          <Bifang />
        ) : selected === 'lushu' ? (
          <Lushu />
        ) : (
          <PlaceholderBeast />
        )}
      </Suspense>
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
  )
}
