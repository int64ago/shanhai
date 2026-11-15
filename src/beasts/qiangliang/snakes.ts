import { Bone, Box3, Float32BufferAttribute, Group, Mesh, Skeleton, SkinnedMesh, Uint16BufferAttribute, Vector3 } from 'three'
import type { Material, Object3D } from 'three'

/** Two branches leave a fixed mid-body support; the bite/hoof never drifts. */
export function createSupportedSnake(source: Object3D, length: number) {
  source.updateMatrixWorld(true)
  const original = source.getObjectByProperty('isMesh', true) as Mesh | undefined
  if (!original) throw new Error('强良单蛇母件缺少网格')
  const geometry = original.geometry.clone()
  // meshopt positions may be normalized Int16 with a dequantization transform.
  // Bake into Float32 first: writing world coordinates into Int16 wraps at 1.
  for (const name of ['position', 'normal']) {
    const attribute = geometry.getAttribute(name)
    const values = new Float32Array(attribute.count * 3)
    for (let i = 0; i < attribute.count; i++) values.set([attribute.getX(i), attribute.getY(i), attribute.getZ(i)], i * 3)
    geometry.setAttribute(name, new Float32BufferAttribute(values, 3))
  }
  geometry.applyMatrix4(original.matrixWorld)
  // Mother is an upright S in the YZ plane; turn it toward the viewer uniformly.
  geometry.rotateY(Math.PI / 2)
  let box = new Box3().setFromBufferAttribute(geometry.getAttribute('position') as never)
  geometry.scale(length / (box.max.y - box.min.y), length / (box.max.y - box.min.y), length / (box.max.y - box.min.y))
  box = new Box3().setFromBufferAttribute(geometry.getAttribute('position') as never)
  const supportY = box.min.y + length * 0.6
  const pos = geometry.getAttribute('position')
  const support = new Vector3()
  let count = 0
  for (let i = 0; i < pos.count; i++) {
    if (Math.abs(pos.getY(i) - supportY) < length * 0.012) {
      support.x += pos.getX(i); support.z += pos.getZ(i); count++
    }
  }
  if (!count) throw new Error('强良单蛇母件支承截面为空')
  geometry.translate(-support.x / count, -supportY, -support.z / count)
  const bones = Array.from({ length: 11 }, (_, i) => { const b = new Bone(); b.name = `serpent_${i}`; return b })
  const segment = length / 10
  for (let i = 5; i >= 0; i--) { bones[i].position.y = -segment; bones[i + 1].add(bones[i]) }
  for (let i = 7; i <= 10; i++) { bones[i].position.y = segment; bones[i - 1].add(bones[i]) }
  const indices = new Uint16Array(pos.count * 4)
  const weights = new Float32Array(pos.count * 4)
  for (let i = 0; i < pos.count; i++) {
    const t = Math.max(0, Math.min(10, pos.getY(i) / segment + 6))
    const lower = Math.floor(t), upper = Math.min(10, lower + 1), f = t - lower
    indices.set([lower, upper, 0, 0], i * 4)
    weights.set([1 - f, f, 0, 0], i * 4)
  }
  geometry.setAttribute('skinIndex', new Uint16BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new Float32BufferAttribute(weights, 4))
  const mesh = new SkinnedMesh(geometry, original.material as Material)
  mesh.name = 'qiangliang_supported_serpent'
  mesh.frustumCulled = false
  mesh.add(bones[6])
  mesh.bind(new Skeleton(bones))
  const holder = new Group()
  holder.add(mesh)
  return { holder, bones, mesh }
}

export function animateSupportedSnake(bones: Bone[], time: number, phase: number, energy: number, hoofClearance = 0) {
  // The hanging half leaves the fixed wrist contact toward the front of the
  // wider hoof. Its first joint provides clearance without moving the support.
  bones[5].position.z = hoofClearance
  for (let i = 0; i < bones.length; i++) {
    if (i === 6) continue
    const distance = Math.abs(i - 6)
    const amplitude = (0.012 + energy * 0.025) * Math.min(1, distance / 2)
    bones[i].rotation.z = amplitude * Math.sin(time * 1.7 - distance * 0.6 + phase)
    bones[i].rotation.x = amplitude * 0.45 * Math.sin(time * 1.25 - distance * 0.55 + phase)
  }
}
