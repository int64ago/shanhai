import {
  Bone,
  Box3,
  BufferGeometry,
  Float32BufferAttribute,
  Material,
  Mesh,
  Object3D,
  Skeleton,
  SkinnedMesh,
  Uint16BufferAttribute,
  Vector3,
} from 'three'

export const WING_BONES = 6
export const LEG_BONES = 3

export interface Wing {
  pivot: Object3D
  bones: Bone[]
  mesh: SkinnedMesh
  tip: Object3D
  side: 1 | -1
  isFront: boolean
}

export interface Leg {
  pivot: Object3D
  bones: Bone[]
  mesh: SkinnedMesh
  side: 1 | -1
  row: 0 | 1 | 2
}

/**
 * 准备单翼几何体：翼根移至原点 (0,0,0)，沿 +X 展开，供左右四翼复用。
 * 右翼通过绕 Y 轴旋转约 180° 实现镜像展开，不使用负缩放以免反转法线与外轮廓背面剔除。
 */
export function prepareWingGeometry(source: Mesh): { geometry: BufferGeometry; length: number } {
  const geometry = source.geometry.clone()
  geometry.applyMatrix4(source.matrixWorld)
  const box = new Box3().setFromBufferAttribute(geometry.getAttribute('position') as never)
  const center = box.getCenter(new Vector3())
  // 翼根在 -X 端，移到原点；上下取中偏下一点让翎羽向后下方舒展
  geometry.translate(-box.min.x, -box.min.y - (box.max.y - box.min.y) * 0.65, -center.z)
  const length = box.max.x - box.min.x

  const pos = geometry.getAttribute('position')
  const indices = new Uint16Array(pos.count * 4)
  const weights = new Float32Array(pos.count * 4)
  const seg = length / WING_BONES
  for (let i = 0; i < pos.count; i++) {
    const s = Math.min(Math.max(pos.getX(i) / seg, 0), WING_BONES - 1)
    const i0 = Math.floor(s)
    const i1 = Math.min(i0 + 1, WING_BONES - 1)
    const f = s - i0
    indices.set([i0, i1, 0, 0], i * 4)
    weights.set([1 - f, f, 0, 0], i * 4)
  }
  geometry.setAttribute('skinIndex', new Uint16BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new Float32BufferAttribute(weights, 4))
  return { geometry, length }
}

export function createWing(
  geometry: BufferGeometry,
  material: Material,
  length: number,
  side: 1 | -1,
  isFront: boolean,
): Wing {
  const seg = length / WING_BONES
  const bones: Bone[] = []
  for (let i = 0; i < WING_BONES; i++) {
    const b = new Bone()
    if (i > 0) {
      b.position.x = seg
      bones[i - 1].add(b)
    }
    bones.push(b)
  }
  const tip = new Object3D()
  tip.position.x = seg
  bones[WING_BONES - 1].add(tip)

  const mesh = new SkinnedMesh(geometry, material)
  mesh.frustumCulled = false
  mesh.add(bones[0])
  mesh.bind(new Skeleton(bones))

  const pivot = new Object3D()
  const scale = isFront ? 1.32 : 1.06
  pivot.scale.setScalar(scale)
  pivot.add(mesh)
  return { pivot, bones, mesh, tip, side, isFront }
}

/**
 * 准备单足几何体：足根（大腿顶）移到 (0, 0.05, 0)，脚掌底落在 y = -reach，
 * 顶部收细成锥头埋入囊底，沿 -Y 建立 3 节骨骼（髋 → 膝 → 踝爪），使六足正好踩在地面 y = 0 上。
 */
export function prepareLegGeometry(source: Mesh, reach = 0.335): { geometry: BufferGeometry; reach: number } {
  const geometry = source.geometry.clone()
  geometry.applyMatrix4(source.matrixWorld)
  const box = new Box3().setFromBufferAttribute(geometry.getAttribute('position') as never)
  const center = box.getCenter(new Vector3())
  const rawH = box.max.y - box.min.y
  const topOverlap = 0.055
  const sy = (reach + topOverlap) / rawH
  const sxz = sy * 0.88
  geometry.translate(-center.x, -box.max.y, -center.z)
  geometry.scale(sxz, sy, sxz)
  geometry.translate(0, topOverlap, 0)

  // 大腿上端收细成圆锥，彻底藏进浑圆囊腹内，不露平切顶面
  const pos = geometry.getAttribute('position')
  const totalH = reach + topOverlap
  for (let i = 0; i < pos.count; i++) {
    const u = (topOverlap - pos.getY(i)) / totalH // 0 = 最顶端，1 = 脚底
    if (u < 0.38) {
      const k = 0.22 + 0.78 * (u / 0.38) ** 0.75
      pos.setX(i, pos.getX(i) * k)
      pos.setZ(i, pos.getZ(i) * k)
    }
  }
  pos.needsUpdate = true

  // 修正非等比缩放后的法线（避免 computeVertexNormals 在退化面上产生 NaN）
  const normal = geometry.getAttribute('normal')
  const n = new Vector3()
  for (let i = 0; i < normal.count; i++) {
    n.set(normal.getX(i) / sxz, normal.getY(i) / sy, normal.getZ(i) / sxz)
    const len = n.length()
    if (len > 1e-8) n.divideScalar(len)
    else n.set(0, 1, 0)
    normal.setXYZ(i, n.x, n.y, n.z)
  }
  normal.needsUpdate = true

  const indices = new Uint16Array(pos.count * 4)
  const weights = new Float32Array(pos.count * 4)
  const seg = reach / LEG_BONES
  for (let i = 0; i < pos.count; i++) {
    const depth = Math.max(0, -pos.getY(i))
    const s = Math.min(depth / seg, LEG_BONES - 1)
    const i0 = Math.floor(s)
    const i1 = Math.min(i0 + 1, LEG_BONES - 1)
    const f = s - i0
    indices.set([i0, i1, 0, 0], i * 4)
    weights.set([1 - f, f, 0, 0], i * 4)
  }
  geometry.setAttribute('skinIndex', new Uint16BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new Float32BufferAttribute(weights, 4))
  return { geometry, reach }
}

export function createLeg(
  geometry: BufferGeometry,
  material: Material,
  reach: number,
  side: 1 | -1,
  row: 0 | 1 | 2,
): Leg {
  const seg = reach / LEG_BONES
  const bones: Bone[] = []
  for (let i = 0; i < LEG_BONES; i++) {
    const b = new Bone()
    if (i > 0) {
      b.position.y = -seg
      bones[i - 1].add(b)
    }
    bones.push(b)
  }
  const mesh = new SkinnedMesh(geometry, material)
  mesh.frustumCulled = false
  mesh.add(bones[0])
  mesh.bind(new Skeleton(bones))

  const pivot = new Object3D()
  pivot.add(mesh)
  return { pivot, bones, mesh, side, row }
}
