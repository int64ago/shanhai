import { Canvas } from '@react-three/fiber'
import { ContactShadows, OrbitControls } from '@react-three/drei'
import { ACESFilmicToneMapping, SRGBColorSpace } from 'three'
import { Placeholder } from './Placeholder'

// M0 空场景：后续 M1 在这里接 HDRI、后期和画质分级
export function Stage() {
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [3.5, 2, 5], fov: 35 }}
      gl={{ antialias: true, toneMapping: ACESFilmicToneMapping, outputColorSpace: SRGBColorSpace }}
    >
      <color attach="background" args={['#d9d4c7']} />
      <fog attach="fog" args={['#d9d4c7', 8, 30]} />

      <hemisphereLight args={['#f4efe2', '#6b6658', 0.6]} />
      <directionalLight
        position={[4, 6, 3]}
        intensity={2.2}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0002}
      />

      <Placeholder />

      <mesh rotation-x={-Math.PI / 2} receiveShadow>
        <circleGeometry args={[30, 64]} />
        <meshStandardMaterial color="#cfc8b8" roughness={0.95} />
      </mesh>
      <ContactShadows position={[0, 0.01, 0]} opacity={0.5} scale={8} blur={2.4} far={3} />

      <OrbitControls
        target={[0, 0.8, 0]}
        enablePan={false}
        minDistance={2.5}
        maxDistance={12}
        maxPolarAngle={Math.PI / 2 - 0.05}
      />
    </Canvas>
  )
}
