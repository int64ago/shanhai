import {
  Bone,
  Box3,
  BufferGeometry,
  Float32BufferAttribute,
  Material,
  Mesh,
  Object3D,
  Quaternion,
  Skeleton,
  SkinnedMesh,
  Uint16BufferAttribute,
  Vector3,
} from 'three'

export const TAIL_BONES = 8

export interface Tail {
  pivot: Object3D
  bones: Bone[]
  mesh: SkinnedMesh
  /** 尾尖的辅助节点，用来发狐火 */
  tip: Object3D
}

/**
 * 把一条静态尾巴网格（沿 +X，根部在 -X 端）变成带骨骼链的蒙皮网格。
 * 权重按顶点在长度方向上的位置线性分配到相邻两节骨骼，几何形状简单时比自动权重更稳。
 */
export function prepareTailGeometry(
  source: Mesh,
  /** 目标截面直径与长度之比；AI 尾巴截面偏扁偏细，按这个比例把高、厚分别撑开 */
  girth = 0.24,
): { geometry: BufferGeometry; length: number } {
  const geometry = source.geometry.clone()
  geometry.applyMatrix4(source.matrixWorld)
  const box = new Box3().setFromBufferAttribute(geometry.getAttribute('position') as never)
  const center = box.getCenter(new Vector3())
  // 根部移到原点
  geometry.translate(-box.min.x, -center.y, -center.z)
  const length = box.max.x - box.min.x
  const size = box.getSize(new Vector3())
  const sy = (length * girth) / size.y
  const sz = (length * girth * 0.85) / size.z
  geometry.scale(1, sy, sz)
  // 非等比缩放后法线按逆转置修正；不用 computeVertexNormals，AI 网格的退化三角形会算出 NaN，经辉光扩散成全屏黑
  const normal = geometry.getAttribute('normal')
  const n = new Vector3()
  for (let i = 0; i < normal.count; i++) {
    n.set(normal.getX(i), normal.getY(i) / sy, normal.getZ(i) / sz)
    const len = n.length()
    if (len > 1e-8) n.divideScalar(len)
    else n.set(0, 1, 0)
    normal.setXYZ(i, n.x, n.y, n.z)
  }
  normal.needsUpdate = true

  // 根部收细：九条尾巴从同一处长出，根部粗了会在臀部挤成一团、穿出身体
  const pos = geometry.getAttribute('position')
  for (let i = 0; i < pos.count; i++) {
    const u = pos.getX(i) / length
    const k = 0.3 + 0.7 * Math.min(1, u / 0.3) ** 0.7
    pos.setY(i, pos.getY(i) * k)
    pos.setZ(i, pos.getZ(i) * k)
  }
  pos.needsUpdate = true

  const indices = new Uint16Array(pos.count * 4)
  const weights = new Float32Array(pos.count * 4)
  const seg = length / TAIL_BONES
  for (let i = 0; i < pos.count; i++) {
    const s = Math.min(Math.max(pos.getX(i) / seg, 0), TAIL_BONES - 1)
    const i0 = Math.floor(s)
    const i1 = Math.min(i0 + 1, TAIL_BONES - 1)
    const f = s - i0
    indices.set([i0, i1, 0, 0], i * 4)
    weights.set([1 - f, f, 0, 0], i * 4)
  }
  geometry.setAttribute('skinIndex', new Uint16BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new Float32BufferAttribute(weights, 4))
  return { geometry, length }
}

export function createTail(geometry: BufferGeometry, material: Material, length: number): Tail {
  const seg = length / TAIL_BONES
  const bones: Bone[] = []
  for (let i = 0; i < TAIL_BONES; i++) {
    const b = new Bone()
    if (i > 0) {
      b.position.x = seg
      bones[i - 1].add(b)
    }
    bones.push(b)
  }
  const tip = new Object3D()
  tip.position.x = seg
  bones[TAIL_BONES - 1].add(tip)

  const mesh = new SkinnedMesh(geometry, material)
  mesh.frustumCulled = false
  mesh.add(bones[0])
  mesh.bind(new Skeleton(bones))

  const pivot = new Object3D()
  pivot.add(mesh)
  return { pivot, bones, mesh, tip }
}

const X = new Vector3(1, 0, 0)
const _dir = new Vector3()

/**
 * 尾巴的基础朝向：elevation 为从“正后方水平”抬起的角度，roll 为绕身体纵轴的展开角。
 * 模型朝 +Z，所以正后方是 -Z。
 */
export function aimTail(pivot: Object3D, elevation: number, roll: number, q = new Quaternion()) {
  _dir.set(Math.sin(roll) * Math.sin(elevation), Math.cos(roll) * Math.sin(elevation), -Math.cos(elevation))
  q.setFromUnitVectors(X, _dir.normalize())
  pivot.quaternion.copy(q)
}
