import { Mesh, MeshStandardMaterial, Object3D, SkinnedMesh } from 'three'
import { createInkMaterial, createOutlineMaterial } from './inkMaterial'

export interface InkifyOptions {
  saturation?: number
  outline?: number
  outlineDepthBias?: number
}

/**
 * 把模型里的写实材质换成水墨材质，并给每个网格加一层外轮廓墨线。
 * 外轮廓与原网格共享几何体和骨骼，蒙皮时一起变形。
 * 可重复调用（React StrictMode 会把 useMemo 执行两遍），已处理过的模型直接跳过。
 */
export function inkify(root: Object3D, { saturation, outline = 0.006, outlineDepthBias }: InkifyOptions = {}) {
  if (root.userData.inked) return
  root.userData.inked = true
  const meshes: Mesh[] = []
  root.traverse((o) => {
    if (o instanceof Mesh && !o.userData.inkOutline) meshes.push(o)
  })
  for (const mesh of meshes) {
    const src = mesh.material as MeshStandardMaterial
    mesh.material = createInkMaterial({ map: src.map ?? null, saturation })
    mesh.castShadow = false
    mesh.receiveShadow = false
    if (outline > 0) mesh.parent!.add(createOutline(mesh, outline, outlineDepthBias))
  }
  return meshes
}

export function createOutline(mesh: Mesh, width: number, depthBias?: number) {
  const mat = createOutlineMaterial(width, depthBias)
  let outline: Mesh
  if (mesh instanceof SkinnedMesh) {
    const s = new SkinnedMesh(mesh.geometry, mat)
    s.bind(mesh.skeleton, mesh.bindMatrix)
    outline = s
  } else {
    outline = new Mesh(mesh.geometry, mat)
  }
  outline.position.copy(mesh.position)
  outline.quaternion.copy(mesh.quaternion)
  outline.scale.copy(mesh.scale)
  outline.frustumCulled = false
  outline.userData.inkOutline = true
  return outline
}
