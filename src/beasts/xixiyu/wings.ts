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
} from 'three'

export const WING_BONES = 5

export interface XixiyuWing {
  pivot: Object3D
  bones: Bone[]
  mesh: SkinnedMesh
  tip: Object3D
  pair: number
  side: 1 | -1
}

/**
 * Prepare left (+X) or right (-X) scaled-feather wing geometry with 5 spanwise bones.
 * Both wing_l and wing_r come pre-mirrored with outward triangle winding from Blender,
 * avoiding negative runtime scale on outlined meshes.
 */
export function prepareXixiyuWingGeometry(
  source: Mesh,
  side: 1 | -1,
): { geometry: BufferGeometry; span: number } {
  const geometry = source.geometry.clone()
  source.updateWorldMatrix(true, false)
  geometry.applyMatrix4(source.matrixWorld)
  // The High single-wing source already has a 0.334 m chord at 0.58 m span.
  // Keep its native chord (1.0); the historical Medium donor needed 1.75.
  // applyMatrix4 transforms existing normals; never recompute this AI mesh.

  const box = new Box3().setFromBufferAttribute(geometry.getAttribute('position') as never)
  const span = side === 1 ? Math.max(box.max.x, 0.1) : Math.max(-box.min.x, 0.1)

  const pos = geometry.getAttribute('position')
  const indices = new Uint16Array(pos.count * 4)
  const weights = new Float32Array(pos.count * 4)
  const seg = span / WING_BONES

  for (let i = 0; i < pos.count; i++) {
    const along = Math.max(0, side * pos.getX(i))
    const s = Math.min(along / seg, WING_BONES - 1)
    const i0 = Math.floor(s)
    const i1 = Math.min(i0 + 1, WING_BONES - 1)
    const f = s - i0
    indices.set([i0, i1, 0, 0], i * 4)
    weights.set([1 - f, f, 0, 0], i * 4)
  }

  geometry.setAttribute('skinIndex', new Uint16BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new Float32BufferAttribute(weights, 4))
  return { geometry, span }
}

export function createXixiyuWing(
  geometry: BufferGeometry,
  material: Material,
  span: number,
  pair: number,
  side: 1 | -1,
  scale: number,
): XixiyuWing {
  const seg = span / WING_BONES
  const bones: Bone[] = []
  for (let i = 0; i < WING_BONES; i++) {
    const b = new Bone()
    if (i > 0) {
      b.position.x = side * seg
      bones[i - 1].add(b)
    }
    bones.push(b)
  }

  const tip = new Object3D()
  tip.position.x = side * seg
  bones[WING_BONES - 1].add(tip)

  const mesh = new SkinnedMesh(geometry, material)
  mesh.name = `xixiyu_wing_${pair}_${side === 1 ? 'l' : 'r'}`
  mesh.frustumCulled = false
  mesh.add(bones[0])
  mesh.bind(new Skeleton(bones))

  const pivot = new Object3D()
  pivot.name = `xixiyu_wing_pivot_${pair}_${side === 1 ? 'l' : 'r'}`
  pivot.scale.setScalar(scale)
  pivot.add(mesh)

  return { pivot, bones, mesh, tip, pair, side }
}
