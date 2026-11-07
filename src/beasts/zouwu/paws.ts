import { Bone, Object3D, Quaternion, Vector3 } from 'three'

const UP = new Vector3(0, 1, 0)

/** Keep the complete sole transform through clip blends and turn transitions.
 * Baked clips supply swing/flight targets; a landed foot retains its world
 * anchor until it lifts again. Two-link correction keeps the limb attached.
 */
export function createPawPlants(scene: Object3D) {
  scene.updateMatrixWorld(true)
  const p = new Vector3()
  const paws = ['front_l', 'front_r', 'back_l', 'back_r'].map(name => {
    const upper = scene.getObjectByName(`${name}_upper`) as Bone
    const lower = scene.getObjectByName(`${name}_lower`) as Bone
    const foot = scene.getObjectByName(`${name}_foot`) as Bone
    if (!upper || !lower || !foot) throw new Error(`zouwu: missing ${name} chain`)
    const hip = upper.getWorldPosition(new Vector3())
    const knee = lower.getWorldPosition(new Vector3())
    const ankle = foot.getWorldPosition(new Vector3())
    return { upper, lower, foot, length1: hip.distanceTo(knee), length2: knee.distanceTo(ankle),
      height: ankle.y, planted: false, anchor: new Vector3(), orientation: new Quaternion(),
      pole: new Vector3(0, 0, name.startsWith('front') ? 1 : -1) }
  })
  return { paws, hip: new Vector3(), knee: new Vector3(), ankle: new Vector3(),
    target: new Vector3(), direction: new Vector3(), normal: new Vector3(), joint: new Vector3(),
    oldUpper: new Vector3(), oldLower: new Vector3(), newAxis: new Vector3(), point: p,
    upperQ: new Quaternion(), lowerQ: new Quaternion(), footQ: new Quaternion(), parentQ: new Quaternion(),
    deltaQ: new Quaternion(), rootQ: new Quaternion() }
}

export function stabilizePaws(rig: ReturnType<typeof createPawPlants>, root: Object3D) {
  root.updateMatrixWorld(true)
  root.getWorldQuaternion(rig.rootQ)
  for (const paw of rig.paws) {
    const { upper, lower, foot } = paw
    upper.getWorldPosition(rig.hip)
    lower.getWorldPosition(rig.knee)
    foot.getWorldPosition(rig.ankle)
    foot.getWorldQuaternion(rig.footQ)
    const height = rig.ankle.y - paw.height
    if (height > 0.004) paw.planted = false
    if (!paw.planted && height < 0.002) {
      paw.planted = true
      paw.anchor.copy(rig.ankle).setY(paw.height)
      paw.orientation.copy(rig.footQ)
    }
    foot.userData.planted = paw.planted
    if (!paw.planted) continue
    rig.target.copy(paw.anchor)
    rig.oldUpper.subVectors(rig.knee, rig.hip).normalize()
    rig.oldLower.subVectors(rig.ankle, rig.knee).normalize()
    upper.getWorldQuaternion(rig.upperQ)
    lower.getWorldQuaternion(rig.lowerQ)
    rig.direction.subVectors(rig.target, rig.hip)
    const distance = Math.max(1e-6, Math.min(rig.direction.length(), (paw.length1 + paw.length2) * 0.99999))
    rig.direction.normalize()
    const along = (paw.length1 ** 2 - paw.length2 ** 2 + distance ** 2) / (2 * distance)
    rig.normal.copy(paw.pole).applyQuaternion(rig.rootQ)
    rig.normal.addScaledVector(rig.direction, -rig.normal.dot(rig.direction))
    if (rig.normal.lengthSq() < 1e-8) rig.normal.copy(UP)
    rig.normal.normalize()
    rig.joint.copy(rig.hip).addScaledVector(rig.direction, along)
      .addScaledVector(rig.normal, Math.sqrt(Math.max(0, paw.length1 ** 2 - along ** 2)))
    rig.newAxis.subVectors(rig.joint, rig.hip).normalize()
    rig.deltaQ.setFromUnitVectors(rig.oldUpper, rig.newAxis)
    upper.parent!.getWorldQuaternion(rig.parentQ).invert()
    upper.quaternion.copy(rig.parentQ).multiply(rig.deltaQ).multiply(rig.upperQ)
    upper.updateMatrixWorld(true)
    lower.position.copy(upper.worldToLocal(rig.point.copy(rig.joint)))
    rig.newAxis.subVectors(rig.target, rig.joint).normalize()
    rig.deltaQ.setFromUnitVectors(rig.oldLower, rig.newAxis)
    upper.getWorldQuaternion(rig.parentQ).invert()
    lower.quaternion.copy(rig.parentQ).multiply(rig.deltaQ).multiply(rig.lowerQ)
    lower.updateMatrixWorld(true)
    foot.position.copy(lower.worldToLocal(rig.point.copy(rig.target)))
    lower.getWorldQuaternion(rig.parentQ).invert()
    foot.quaternion.copy(rig.parentQ).multiply(paw.orientation)
    foot.updateMatrixWorld(true)
  }
}
