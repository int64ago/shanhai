import { useEffect, useMemo } from 'react'
import { DoubleSide, LatheGeometry, Matrix4, Mesh, Object3D, Raycaster, SkinnedMesh, Vector2, Vector3 } from 'three'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'
import { Quadruped } from '../Quadruped'

/** 古经只记背上有角；一枚短弯角是本作选择，数量与形制均标为推断。 */
function BackHorn({ scene }: { scene: Object3D }) {
  const rig = useMemo(() => {
    const profile = Array.from({ length: 17 }, (_, i) => {
      const t = i / 16
      return new Vector2(0.032 * (1 - t) ** 0.8, t * 0.17)
    })
    const geometry = new LatheGeometry(profile, 16)
    const positions = geometry.getAttribute('position')
    const normals = geometry.getAttribute('normal')
    for (let i = 0; i < positions.count; i++) {
      const t = positions.getY(i) / 0.17
      positions.setZ(i, positions.getZ(i) - 0.045 * t * t)
      // Inverse transpose of the bend, preserving the analytic lathe normals.
      const n = new Vector3().fromBufferAttribute(normals, i)
      n.y += (0.09 * t / 0.17) * n.z
      n.normalize()
      normals.setXYZ(i, n.x, n.y, n.z)
    }
    geometry.computeBoundingSphere()
    const material = createInkMaterial({ map: null, tint: '#b7a17c', saturation: 0.45 })
    const horn = new Mesh(geometry, material)
    horn.name = 'chenghuang_back_horn'
    horn.frustumCulled = false
    const outline = createOutline(horn, 0.002)
    const holder = new Object3D()
    holder.name = 'chenghuang_horn_mount'
    holder.matrixAutoUpdate = false
    holder.add(horn, outline)
    return { holder }
  }, [])

  useEffect(() => {
    // Refresh SkinnedMesh bindMatrixInverse after the outer stage transform,
    // before sampling deformed positions or raycasting the torso surface.
    scene.updateWorldMatrix(true, false)
    scene.updateMatrixWorld(true)
    const spine = scene.getObjectByName('spine2')
    if (!spine) throw new Error('乘黄缺少 spine2 骨骼')
    const sceneInverse = scene.matrixWorld.clone().invert()
    const inverseRest = new Matrix4().multiplyMatrices(sceneInverse, spine.matrixWorld).invert()
    const surfaces: Mesh[] = []
    const vertex = new Vector3()
    let top = 0
    scene.traverse((node) => {
      if (!(node instanceof Mesh) || node.userData.inkOutline) return
      // The generated fur folds can turn inward at joints. Both sides must
      // occlude the outline shell to avoid black patches during deformation.
      if (node instanceof SkinnedMesh && node.skeleton.bones.some((bone) => bone.name === 'tail_attach')) {
        for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
          material.side = DoubleSide
          material.needsUpdate = true
        }
      }
      surfaces.push(node)
      const toScene = new Matrix4().multiplyMatrices(sceneInverse, node.matrixWorld)
      const positions = node.geometry.getAttribute('position')
      for (let i = 0; i < positions.count; i++) {
        node.getVertexPosition(i, vertex).applyMatrix4(toScene)
        top = Math.max(top, vertex.y)
      }
    })
    const origin = new Vector3(0, top + 0.5, 0).applyMatrix4(scene.matrixWorld)
    const direction = new Vector3(0, -1, 0).transformDirection(scene.matrixWorld)
    const hit = new Raycaster(origin, direction).intersectObjects(surfaces, false)[0]
    if (!hit) throw new Error('乘黄背角挂点未落在背脊表面')
    const mount = hit.point.applyMatrix4(sceneInverse)
    mount.y -= 0.014
    rig.holder.matrix.copy(inverseRest).multiply(new Matrix4().makeTranslation(mount))
    spine.add(rig.holder)
    return () => { spine.remove(rig.holder) }
  }, [scene, rig])

  return null
}

const call = (pan: number) => audio.chenghuangCall(pan)

export function Chenghuang() {
  return <Quadruped
    id="chenghuang"
    tailCount={1}
    tailUrl="/models/chenghuang/tail.glb"
    tailGirth={0.25}
    tailColor="#ffffff"
    tailSaturation={0.12}
    outline={0.003}
    outlineDepthBias={0.004}
    appendages={BackHorn}
    specialEffect={null}
    onCall={call}
  />
}
