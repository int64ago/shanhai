import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { Box3, CylinderGeometry, Group, MathUtils, Matrix4, Mesh, Object3D, Raycaster, Vector3 } from 'three'
import { useApp } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline, inkify } from '../../systems/ink/inkify'
import { Quadruped } from '../Quadruped'

const HEAD_SCALE = 0.5
const NECK_LENGTH = 0.044
const MOUNTS = [
  ...[-0.22, -0.11, 0, 0.11, 0.22].map((x) => ({ x, y: 0.52 })),
  ...[-0.165, -0.055, 0.055, 0.165].map((x) => ({ x, y: 0.66 })),
]

/** 九首共享同一静态人首母件，各颈独立转动，头颅不受躯干蒙皮拉扯。 */
function NineHeads({ scene }: { scene: Object3D }) {
  const source = useGLTF('/models/kaiming/head.glb')
  const action = useApp((s) => s.action)
  const motion = useRef({ time: 0, alert: 0, gait: 0 })
  const rig = useMemo(() => {
    // Clone before inkifying: the cached GLTF scene stays untouched, including
    // during StrictMode's discarded memo invocation.
    const master = source.scene.clone(true)
    inkify(master, { saturation: 0.88, outline: 0.004 })
    master.traverse((node) => { if (node instanceof Mesh) node.frustumCulled = false })
    const neckGeometry = new CylinderGeometry(0.022, 0.028, NECK_LENGTH, 16, 1)
    const neckMaterial = createInkMaterial({ map: null, tint: '#d5ad82', saturation: 0.88 })
    const heads = MOUNTS.map((mount, index) => {
      const holder = new Object3D()
      holder.name = `kaiming_head_mount_${index + 1}`
      holder.matrixAutoUpdate = false
      const neckPivot = new Group()
      neckPivot.name = `kaiming_neck_${index + 1}`
      const neck = new Mesh(neckGeometry, neckMaterial)
      neck.position.y = NECK_LENGTH / 2 - 0.012
      neck.frustumCulled = false
      neckPivot.add(neck, createOutline(neck, 0.002))
      const skullPivot = new Group()
      skullPivot.name = `kaiming_skull_${index + 1}`
      skullPivot.position.y = NECK_LENGTH - 0.016
      const head = master.clone(true)
      head.name = `kaiming_head_${index + 1}`
      head.scale.setScalar(HEAD_SCALE)
      skullPivot.add(head)
      neckPivot.add(skullPivot)
      holder.add(neckPivot)
      return { holder, neckPivot, skullPivot, mount, phase: index * 2.39996 }
    })
    return { heads }
  }, [source])

  useEffect(() => {
    // updateWorldMatrix alone bypasses SkinnedMesh's bindMatrixInverse update.
    // Refresh it after the outer beast group transform before skin raycasts.
    scene.updateWorldMatrix(true, false)
    scene.updateMatrixWorld(true)
    const chest = scene.getObjectByName('chest')
    if (!chest) throw new Error('开明兽缺少 chest 骨骼')
    const sceneInverse = scene.matrixWorld.clone().invert()
    const inverseRest = new Matrix4().multiplyMatrices(sceneInverse, chest.matrixWorld).invert()
    const surfaces: Mesh[] = []
    const bounds = new Box3()
    const vertex = new Vector3()
    scene.traverse((node) => {
      if (!(node instanceof Mesh) || node.userData.inkOutline) return
      surfaces.push(node)
      const toScene = new Matrix4().multiplyMatrices(sceneInverse, node.matrixWorld)
      const positions = node.geometry.getAttribute('position')
      for (let i = 0; i < positions.count; i++) {
        bounds.expandByPoint(node.getVertexPosition(i, vertex).applyMatrix4(toScene))
      }
    })
    const direction = new Vector3(0, 0, -1).transformDirection(scene.matrixWorld)
    const ray = new Raycaster()
    // Resolve every mount before attaching any head, so later raycasts never
    // intersect a previously attached head or its outline.
    const positions = rig.heads.map(({ mount }, index) => {
      const origin = new Vector3(mount.x, mount.y, bounds.max.z + 1).applyMatrix4(scene.matrixWorld)
      ray.set(origin, direction)
      const hit = ray.intersectObjects(surfaces, false)[0]
      if (!hit) throw new Error(`开明兽第 ${index + 1} 首挂点未落在躯干表面`)
      const position = hit.point.applyMatrix4(sceneInverse)
      position.z -= 0.018
      return position
    })
    rig.heads.forEach(({ holder }, index) => {
      holder.matrix.copy(inverseRest).multiply(new Matrix4().makeTranslation(positions[index]))
      chest.add(holder)
    })
    return () => { for (const { holder } of rig.heads) chest.remove(holder) }
  }, [scene, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const pose = motion.current
    pose.time += dt
    pose.alert = MathUtils.damp(pose.alert, action === 'special' ? 1 : 0, 3.5, dt)
    pose.gait = MathUtils.damp(pose.gait, action === 'walk' ? 1 : 0, 4, dt)
    rig.heads.forEach(({ neckPivot, skullPivot, mount, phase }) => {
      const t = pose.time
      neckPivot.rotation.y = mount.x * 0.5 + (0.018 + pose.alert * 0.025) * Math.sin(t * 0.9 + phase)
      neckPivot.rotation.x = -pose.alert * 0.055 + 0.012 * Math.sin(t * 1.15 + phase)
      neckPivot.rotation.z = 0.012 * Math.sin(t * 0.78 + phase * 1.3)
      skullPivot.rotation.x = 0.018 * Math.sin(t * 1.4 + phase) + pose.gait * 0.014 * Math.sin(t * 3.8 + phase)
      skullPivot.rotation.y = 0.012 * Math.cos(t * 0.83 + phase)
    })
  })
  return null
}

const call = (pan: number) => audio.kaimingCall(pan)

export function Kaiming() {
  return <Quadruped
    id="kaiming"
    initialHeading={Math.PI / 2}
    appendages={NineHeads}
    tailCount={1}
    tailUrl="/models/luwu/tail.glb"
    tailGirth={0.065}
    tailColor="#ffffff"
    tailSaturation={0.88}
    specialEffect={null}
    onCall={call}
  />
}
