import { useEffect, useMemo, useRef } from 'react'
import { createPortal, useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import { Box3, MathUtils, Matrix4, Mesh, Object3D, Vector3, type Texture } from 'three'
import { useApp, type BeastAction } from '../../app/store'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { FoxFire } from '../../systems/vfx/FoxFire'
import { Quadruped } from '../Quadruped'
import { createWing, prepareWingGeometry, WING_BONES } from '../dijiang/parts'

const WING_URL = '/models/bibi/wing.glb'
const WING_SCALE = 0.85
const TAU = Math.PI * 2

// 原文只记「有翼」：双翼数量、肩部挂点、振翼动作与翼尖燥尘都是艺术补足。
const POSES: Record<BeastAction, { sweep: number; elevation: number; amplitude: number; speed: number; fold: number; dust: number }> = {
  idle: { sweep: 0.62, elevation: 0.2, amplitude: 0.05, speed: 1.3, fold: 0.06, dust: 0 },
  walk: { sweep: 1.05, elevation: 0.12, amplitude: 0.07, speed: 2.8, fold: 0.2, dust: 0 },
  special: { sweep: 0.2, elevation: 0.36, amplitude: 0.5, speed: 5.2, fold: 0.025, dust: 1.6 },
}

/** 肩点取在颈根之后的鬐甲两侧；狐颈高耸，按胸部包围盒取点会落到颈上。 */
function shoulderPositions(scene: Object3D, spine: Object3D) {
  scene.updateWorldMatrix(true, false)
  scene.updateMatrixWorld(true)
  const sceneInverse = scene.matrixWorld.clone().invert()
  const spineRest = new Matrix4().multiplyMatrices(sceneInverse, spine.matrixWorld)
  const center = new Vector3().setFromMatrixPosition(spineRest)
  const bounds = new Box3()
  const points: Vector3[] = []
  scene.traverse((node) => {
    if (!(node instanceof Mesh) || node.userData.inkOutline) return
    const count = node.geometry.getAttribute('position').count
    for (let i = 0; i < count; i++) {
      const point = node.getVertexPosition(i, new Vector3()).applyMatrix4(node.matrixWorld).applyMatrix4(sceneInverse)
      bounds.expandByPoint(point)
      points.push(point)
    }
  })
  const height = bounds.max.y - bounds.min.y
  if (!(height > 0)) throw new Error('獙獙躯干缺少有效几何体')
  const z = center.z + height * 0.055
  const slice = points.filter((p) => Math.abs(p.z - z) < height * 0.04 && p.y >= center.y)
  if (!slice.length) throw new Error('獙獙肩部切片为空')
  const y = new Box3().setFromPoints(slice).max.y - height * 0.09
  const band = slice.filter((p) => Math.abs(p.y - y) < height * 0.04)
  const shoulder = new Box3().setFromPoints(band.length ? band : slice)
  return {
    spineRest,
    positions: [shoulder.max.x, shoulder.min.x].map((x) => new Vector3(center.x + (x - center.x) * 0.9, y, z)),
  }
}

function BibiWings({ scene }: { scene: Object3D }) {
  const source = useGLTF(WING_URL)
  const action = useApp((s) => s.action)
  const world = useThree((s) => s.scene)
  const motion = useRef({ ...POSES.idle, phase: 0, stroke: 0 })
  const dust = useRef(0)

  const rig = useMemo(() => {
    source.scene.updateMatrixWorld(true)
    let mesh: Mesh | undefined
    source.scene.traverse((node) => { if (!mesh && node instanceof Mesh) mesh = node })
    if (!mesh) throw new Error('獙獙单翼模型里没有网格')
    const { geometry, length } = prepareWingGeometry(mesh)
    const material = createInkMaterial({
      map: (mesh.material as { map?: Texture }).map ?? null,
      saturation: 0.88,
    })
    const wings = ([1, -1] as const).map((side) => {
      const wing = createWing(geometry, material, length, side, true)
      wing.pivot.scale.setScalar(WING_SCALE)
      wing.pivot.add(createOutline(wing.mesh, 0.0038))
      const holder = new Object3D()
      holder.name = side === 1 ? 'bibi_wing_l' : 'bibi_wing_r'
      holder.matrixAutoUpdate = false
      holder.add(wing.pivot)
      return { ...wing, holder }
    })
    return { wings, tips: wings.map((wing) => wing.tip) }
  }, [source])

  useEffect(() => {
    const spine = scene.getObjectByName('spine2')
    if (!spine) throw new Error('獙獙骨骼缺失: spine2')
    const { spineRest, positions } = shoulderPositions(scene, spine)
    const inverseRest = spineRest.invert()
    rig.wings.forEach((wing, i) => {
      // 肩胛落在 spine2 段内：逆矩阵抵消静置变换，只保留脊柱动画增量。
      wing.holder.matrix.copy(inverseRest).multiply(new Matrix4().makeTranslation(positions[i]))
      spine.add(wing.holder)
    })
    return () => {
      for (const wing of rig.wings) spine.remove(wing.holder)
    }
  }, [scene, rig])

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.05)
    const pose = motion.current
    const target = POSES[action]
    for (const key of Object.keys(target) as (keyof typeof target)[]) {
      pose[key] = MathUtils.damp(pose[key], target[key], 3.8, dt)
    }
    dust.current = pose.dust
    pose.phase += pose.speed * dt
    const stroke = Math.floor((pose.phase + Math.PI / 2) / TAU)
    if (action === 'special' && stroke > pose.stroke) audio.wingFlutter(0, 0.42)
    pose.stroke = stroke

    rig.wings.forEach((wing) => {
      // 绕 Y 转向另一侧，避免负缩放翻转外轮廓。
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

  // 粒子按世界坐标发射，须渲染在行走根节点之外，否则位移会被叠加两次。
  return createPortal(<FoxFire emitters={rig.tips} intensity={dust} coreColor="#e9c488" edgeColor="#ad6632" />, world)
}

const call = (pan: number) => {
  audio.bibiCall(pan)
  audio.wingFlutter(pan, 0.42)
}

export function Bibi() {
  return <Quadruped id="bibi" appendages={BibiWings} specialEffect={null} onCall={call} />
}
