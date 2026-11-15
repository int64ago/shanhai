import { Bone, Box3, Float32BufferAttribute, Group, Mesh, Skeleton, SkinnedMesh, Uint16BufferAttribute } from 'three'
import type { Material, Object3D } from 'three'

/** The whole upper hook rests on the ear; only the hanging branches move. */
export function createEarSnake(source: Object3D, length = 0.24) {
  source.updateMatrixWorld(true)
  const original = source.getObjectByProperty('isMesh', true) as Mesh | undefined
  if (!original) throw new Error('夸父耳蛇母件没有网格')
  const geometry = original.geometry.clone()
  for (const name of ['position', 'normal']) {
    const attribute = geometry.getAttribute(name)
    const values = new Float32Array(attribute.count * 3)
    for (let i = 0; i < attribute.count; i++) values.set([attribute.getX(i), attribute.getY(i), attribute.getZ(i)], i * 3)
    geometry.setAttribute(name, new Float32BufferAttribute(values, 3))
  }
  geometry.applyMatrix4(original.matrixWorld)
  const box = new Box3().setFromBufferAttribute(geometry.getAttribute('position') as never)
  const scale = length / (box.max.y - box.min.y)
  geometry.scale(scale, scale, scale)
  const pos = geometry.getAttribute('position')
  let x = 0, z = 0, count = 0
  const top = box.max.y * scale
  for (let i = 0; i < pos.count; i++) {
    if (pos.getY(i) > top - length * 0.045) { x += pos.getX(i); z += pos.getZ(i); count++ }
  }
  if (!count) throw new Error('夸父耳蛇没有完整顶部支承')
  geometry.translate(-x / count, -(top - length * 0.025), -z / count)
  const bones = Array.from({ length: 8 }, (_, i) => { const b = new Bone(); b.name = `ear_serpent_${i}`; return b })
  const fixed = length * 0.26, segment = (length - fixed) / 6
  for (let i = 1; i < bones.length; i++) {
    bones[i].position.y = i === 1 ? -fixed : -segment
    bones[i - 1].add(bones[i])
  }
  const indices = new Uint16Array(pos.count * 4), weights = new Float32Array(pos.count * 4)
  for (let i = 0; i < pos.count; i++) {
    const distance = Math.max(0, -pos.getY(i) - fixed)
    const t = Math.min(7, distance / segment)
    const lower = Math.floor(t), upper = Math.min(7, lower + 1), f = t - lower
    indices.set([lower, upper, 0, 0], i * 4)
    weights.set([1 - f, f, 0, 0], i * 4)
  }
  geometry.setAttribute('skinIndex', new Uint16BufferAttribute(indices, 4))
  geometry.setAttribute('skinWeight', new Float32BufferAttribute(weights, 4))
  const mesh = new SkinnedMesh(geometry, original.material as Material)
  mesh.name = 'kuafu_ear_snake'
  mesh.frustumCulled = false
  mesh.add(bones[0])
  mesh.bind(new Skeleton(bones))
  const holder = new Group()
  holder.add(mesh)
  return { holder, mesh, bones }
}

export function animateEarSnake(bones: Bone[], time: number, phase: number, special: boolean) {
  for (let i = 1; i < bones.length; i++) {
    const amplitude = (special ? 0.026 : 0.012) * i / bones.length
    bones[i].rotation.x = amplitude * Math.sin(time * 1.3 - i * 0.6 + phase)
    bones[i].rotation.z = amplitude * 0.4 * Math.sin(time * 1.5 - i * 0.7 + phase)
  }
}
