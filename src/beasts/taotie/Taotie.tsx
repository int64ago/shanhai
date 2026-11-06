import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Box3, Group, Matrix4, Mesh, Object3D, Quaternion, Raycaster, SphereGeometry, TorusGeometry, Vector3 } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { Quadruped } from '../Quadruped'

const FORWARD = new Vector3(0, 0, 1)

/** 原文的目位在腋下，眼眶、虹膜与数量是明确标注的造型补足。 */
function UnderarmEyes({ scene }: { scene: Object3D }) {
  const action = useApp((s) => s.action)
  const time = useRef(0)
  const rig = useMemo(() => {
    const sclera = createInkMaterial({ map: null, tint: '#e4d1a3', saturation: 0.72 })
    const iris = createInkMaterial({ map: null, tint: '#b98435', saturation: 0.9 })
    const pupil = createInkMaterial({ map: null, tint: '#191a15', saturation: 0.2 })
    const socket = createInkMaterial({ map: null, tint: '#6f3428', saturation: 0.75 })
    const eyes = ([1, -1] as const).map((side) => {
      const holder = new Object3D()
      holder.name = `taotie_eye_${side === 1 ? 'l' : 'r'}`
      holder.matrixAutoUpdate = false
      const eye = new Group()
      eye.quaternion.copy(new Quaternion().setFromUnitVectors(FORWARD, new Vector3(side * 0.92, 0.08, 0.38).normalize()))
      const ball = new Group()
      const white = new Mesh(new SphereGeometry(0.033, 24, 16), sclera)
      white.scale.set(1, 0.8, 0.58)
      const color = new Mesh(new SphereGeometry(0.022, 24, 16), iris)
      color.position.z = 0.017
      color.scale.set(1, 1, 0.24)
      const dark = new Mesh(new SphereGeometry(0.011, 20, 12), pupil)
      dark.position.z = 0.022
      dark.scale.set(0.65, 1.4, 0.2)
      const rim = new Mesh(new TorusGeometry(0.032, 0.007, 8, 32), socket)
      rim.scale.y = 0.82
      for (const mesh of [white, color, dark]) {
        mesh.frustumCulled = false
        ball.add(mesh)
      }
      eye.add(ball, rim, createOutline(rim, 0.0015))
      holder.add(eye)
      return { holder, eye, ball, side }
    })
    return { eyes }
  }, [])

  useEffect(() => {
    // Refresh ancestors first, then use updateMatrixWorld so SkinnedMesh also
    // refreshes bindMatrixInverse for the outer beast group's transform.
    scene.updateWorldMatrix(true, false)
    scene.updateMatrixWorld(true)
    const chest = scene.getObjectByName('chest')
    if (!chest) throw new Error('饕餮缺少 chest 骨骼')
    const sceneInverse = scene.matrixWorld.clone().invert()
    const chestRest = new Matrix4().multiplyMatrices(sceneInverse, chest.matrixWorld)
    const inverseRest = chestRest.clone().invert()
    const bounds = new Box3()
    const surfaces: Mesh[] = []
    const vertex = new Vector3()
    scene.traverse((node) => {
      if (!(node instanceof Mesh) || node.userData.inkOutline) return
      surfaces.push(node)
      const matrix = new Matrix4().multiplyMatrices(sceneInverse, node.matrixWorld)
      const position = node.geometry.getAttribute('position')
      for (let i = 0; i < position.count; i++) {
        // Meshopt quantization is folded into the skin bind matrices. Read
        // skinned rest positions so raw [-1, 1] attributes do not move the eyes.
        bounds.expandByPoint(node.getVertexPosition(i, vertex).applyMatrix4(matrix))
      }
    })
    const height = bounds.max.y - bounds.min.y
    for (const item of rig.eyes) {
      const upper = scene.getObjectByName(`front_${item.side === 1 ? 'l' : 'r'}_upper`)
      if (!upper) throw new Error('饕餮缺少前肢骨骼')
      const root = new Vector3().setFromMatrixPosition(new Matrix4().multiplyMatrices(sceneInverse, upper.matrixWorld))
      const y = root.y - height * 0.10
      const z = root.z - height * 0.11
      // Intersect the actual skin behind the foreleg, rather than taking the
      // widest vertex in a neighborhood (which can belong to the shoulder).
      const origin = new Vector3(item.side * (Math.max(Math.abs(bounds.min.x), Math.abs(bounds.max.x)) + height), y, z).applyMatrix4(scene.matrixWorld)
      const direction = new Vector3(-item.side, 0, 0).transformDirection(scene.matrixWorld)
      const hit = new Raycaster(origin, direction).intersectObjects(surfaces, false)[0]
      if (!hit) throw new Error('饕餮腋下挂点缺少表面')
      const position = hit.point.applyMatrix4(sceneInverse)
      position.x -= item.side * 0.006
      item.holder.matrix.copy(inverseRest).multiply(new Matrix4().makeTranslation(position))
      chest.add(item.holder)
    }
    return () => { for (const item of rig.eyes) chest.remove(item.holder) }
  }, [scene, rig])

  useFrame((_, dt) => {
    time.current += Math.min(dt, 0.05)
    rig.eyes.forEach((item, i) => {
      const phase = (time.current + i * 0.16) % 5.7
      const blink = phase < 0.18 ? Math.max(0.08, Math.abs(phase - 0.09) / 0.09) : 1
      item.ball.scale.y = blink * (action === 'special' ? 1.12 : 1)
    })
  })
  return null
}

const call = (pan: number) => audio.taotieCall(pan)

export function Taotie() {
  return <Quadruped id="taotie" appendages={UnderarmEyes} specialEffect={null} onCall={call} />
}
