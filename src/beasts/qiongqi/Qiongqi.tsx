import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { Box3, MathUtils, Matrix4, Mesh, Object3D, Vector3, type Texture } from 'three'
import { useApp, type BeastAction } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { Quadruped } from '../Quadruped'
import { createWing, prepareWingGeometry, WING_BONES } from '../dijiang/parts'

const WING_URL = '/models/qiongqi/wing.glb'
const TAU = Math.PI * 2

// 双翼数量、羽色、肩部挂点、威慑动作与虎啸均为「状如虎，有翼」的艺术补足。
const POSES: Record<BeastAction, { sweep: number; elevation: number; amplitude: number; speed: number; fold: number }> = {
  idle: { sweep: 0.48, elevation: 0.22, amplitude: 0.055, speed: 1.35, fold: 0.055 },
  walk: { sweep: 1.02, elevation: 0.12, amplitude: 0.075, speed: 2.8, fold: 0.2 },
  special: { sweep: 0.18, elevation: 0.38, amplitude: 0.52, speed: 5.4, fold: 0.025 },
}

/** 以胸骨静置位置与胸部表面求肩点，避免原生长尾拉大整体包围盒后把翼根挪到腰部。 */
function shoulderPositions(scene: Object3D, chest: Object3D) {
  scene.updateWorldMatrix(true, true)
  const sceneInverse = scene.matrixWorld.clone().invert()
  const chestRest = new Matrix4().multiplyMatrices(sceneInverse, chest.matrixWorld)
  const center = new Vector3().setFromMatrixPosition(chestRest)
  const bounds = new Box3()
  const points: Vector3[] = []
  scene.traverse((node) => {
    if (!(node instanceof Mesh) || node.userData.inkOutline) return
    const toScene = new Matrix4().multiplyMatrices(sceneInverse, node.matrixWorld)
    const positions = node.geometry.getAttribute('position')
    for (let i = 0; i < positions.count; i++) {
      const point = new Vector3().fromBufferAttribute(positions, i).applyMatrix4(toScene)
      bounds.expandByPoint(point)
      points.push(point)
    }
  })
  const height = bounds.max.y - bounds.min.y
  if (!(height > 0)) throw new Error('穷奇躯干缺少有效几何体')
  const z = center.z - height * 0.025
  const chestPoints = points.filter((p) => Math.abs(p.z - z) < height * 0.1 && p.y >= center.y)
  if (!chestPoints.length) throw new Error('穷奇胸骨未落在躯干内')
  const chestBounds = new Box3().setFromPoints(chestPoints)
  const y = center.y + (chestBounds.max.y - center.y) * 0.58
  const shoulderBand = chestPoints.filter((p) => Math.abs(p.y - y) < height * 0.06)
  const shoulderBounds = shoulderBand.length ? new Box3().setFromPoints(shoulderBand) : chestBounds
  return {
    chestRest,
    positions: [shoulderBounds.max.x, shoulderBounds.min.x].map((x) =>
      new Vector3(center.x + (x - center.x) * 0.975, y, z)),
  }
}

function QiongqiWings({ scene }: { scene: Object3D }) {
  const source = useGLTF(WING_URL)
  const action = useApp((s) => s.action)
  const motion = useRef({ ...POSES.idle, phase: 0, stroke: 0 })

  const rig = useMemo(() => {
    source.scene.updateMatrixWorld(true)
    let mesh: Mesh | undefined
    source.scene.traverse((node) => { if (!mesh && node instanceof Mesh) mesh = node })
    if (!mesh) throw new Error('穷奇单翼模型里没有网格')
    const { geometry, length } = prepareWingGeometry(mesh)
    const material = createInkMaterial({
      map: (mesh.material as { map?: Texture }).map ?? null,
      saturation: 0.88,
    })
    // 每侧一条独立骨链；共享母件几何和材质，不沿用帝江前翼的 1.32 倍比例。
    const wings = ([1, -1] as const).map((side) => {
      const wing = createWing(geometry, material, length, side, true)
      wing.pivot.scale.setScalar(1)
      wing.pivot.add(createOutline(wing.mesh, 0.0038))
      const holder = new Object3D()
      holder.name = side === 1 ? 'qiongqi_wing_l' : 'qiongqi_wing_r'
      holder.matrixAutoUpdate = false
      holder.add(wing.pivot)
      return { ...wing, holder }
    })
    return { wings }
  }, [source])

  useEffect(() => {
    const chest = scene.getObjectByName('chest')
    if (!chest) throw new Error('穷奇骨骼缺失: chest')
    const { chestRest, positions } = shoulderPositions(scene, chest)
    const inverseRest = chestRest.invert()
    rig.wings.forEach((wing, i) => {
      // 完整矩阵逆变换同时抵消静置旋转与缩放；scene 的逆矩阵已排除外层行走根节点。
      // 保留胸骨动画增量，使两翼始终随胸腔呼吸、迈步和蓄势。
      wing.holder.matrix.copy(inverseRest).multiply(new Matrix4().makeTranslation(positions[i]))
      chest.add(wing.holder)
    })
    return () => {
      for (const wing of rig.wings) chest.remove(wing.holder)
    }
  }, [scene, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const pose = motion.current
    const target = POSES[action]
    for (const key of Object.keys(target) as (keyof typeof target)[]) {
      pose[key] = MathUtils.damp(pose[key], target[key], 3.8, dt)
    }
    pose.phase += pose.speed * dt
    const stroke = Math.floor((pose.phase + Math.PI / 2) / TAU)
    if (action === 'special' && stroke > pose.stroke) audio.wingFlutter(0, 0.48)
    pose.stroke = stroke

    rig.wings.forEach((wing) => {
      // 绕 Y 转向另一侧，避免负缩放翻转外轮廓。两翼有轻微相差，各自独立变形。
      const phase = pose.phase + (wing.side === 1 ? 0 : 0.1)
      wing.pivot.rotation.order = 'YZX'
      wing.pivot.rotation.y = wing.side === 1 ? pose.sweep : Math.PI - pose.sweep
      wing.pivot.rotation.z = pose.elevation + pose.amplitude * Math.sin(phase)
      wing.pivot.rotation.x = -wing.side * (0.2 + 0.035 * Math.cos(phase))
      wing.bones.forEach((bone, j) => {
        const k = j / WING_BONES
        bone.rotation.y = wing.side * pose.fold * k
        bone.rotation.z = (0.025 + pose.amplitude * 0.22) * k * Math.sin(phase - j * 0.48)
      })
    })
  })

  return null
}

const call = (pan: number) => {
  audio.qiongqiCall(pan)
  audio.wingFlutter(pan, 0.48)
}

export function Qiongqi() {
  return <Quadruped id="qiongqi" appendages={QiongqiWings} specialEffect={null} onCall={call} />
}
