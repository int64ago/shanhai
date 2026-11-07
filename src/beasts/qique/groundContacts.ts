import { Bone, Object3D, Quaternion, Vector3 } from 'three'

/** Qique-only two-bone solve. Anchors the complete rigid mouse foot in world space. */
export function createQiqueContacts(scene: Object3D) {
  const bone = (name: string) => {
    const node = scene.getObjectByName(name)
    if (!(node instanceof Bone)) throw new Error(`qique: missing ${name}`)
    return node
  }
  scene.updateWorldMatrix(true, true)
  const legs = ['l', 'r'].map((side) => {
    const foot = bone(`foot_${side}`)
    return { upper: bone(`leg_${side}_upper`), lower: bone(`leg_${side}_lower`), foot,
      groundY: foot.getWorldPosition(new Vector3()).y, planted: false,
      target: new Vector3(), release: new Vector3(), correction: new Vector3(), landingCorrection: new Vector3(),
      landing: 0, wanted: true, raw: new Vector3(), flat: new Quaternion() }
  })
  const a = new Vector3(), b = new Vector3(), c = new Vector3(), target = new Vector3()
  const axis = new Vector3(), pole = new Vector3(), knee = new Vector3(), from = new Vector3(), to = new Vector3()
  const parent = new Quaternion(), world = new Quaternion(), turn = new Quaternion(), flat = new Quaternion()
  const rotate = (node: Bone, direction: Vector3, desired: Vector3) => {
    turn.setFromUnitVectors(direction.normalize(), desired.normalize())
    node.getWorldQuaternion(world)
    node.parent!.getWorldQuaternion(parent).invert()
    node.quaternion.copy(parent).multiply(turn).multiply(world)
    node.updateWorldMatrix(false, true)
  }
  const solve = (leg: typeof legs[number], goal: Vector3, sole: Quaternion) => {
    leg.upper.getWorldPosition(a); leg.lower.getWorldPosition(b); leg.foot.getWorldPosition(c)
    const upperLength = a.distanceTo(b), lowerLength = b.distanceTo(c)
    axis.subVectors(goal, a)
    const distance = Math.max(Math.abs(upperLength - lowerLength) + 1e-8, Math.min(axis.length(), upperLength + lowerLength - 1e-8))
    axis.normalize()
    pole.subVectors(b, a).addScaledVector(axis, -pole.dot(axis))
    if (pole.lengthSq() < 1e-14) {
      pole.set(0, 0, 1); scene.getWorldQuaternion(world); pole.applyQuaternion(world).addScaledVector(axis, -pole.dot(axis))
    }
    pole.normalize()
    const along = (upperLength * upperLength - lowerLength * lowerLength + distance * distance) / (2 * distance)
    knee.copy(a).addScaledVector(axis, along).addScaledVector(pole, Math.sqrt(Math.max(0, upperLength * upperLength - along * along)))
    from.subVectors(b, a); to.subVectors(knee, a); rotate(leg.upper, from, to)
    leg.lower.getWorldPosition(b); leg.foot.getWorldPosition(c)
    from.subVectors(c, b); to.subVectors(goal, b); rotate(leg.lower, from, to)
    leg.foot.parent!.getWorldQuaternion(parent).invert()
    leg.foot.quaternion.copy(parent).multiply(sole)
    leg.foot.updateWorldMatrix(false, true)
  }
  return {
    planted: () => legs.map((leg) => leg.planted),
    debug: () => legs.map((leg) => ({ raw: leg.raw.toArray(), correction: leg.correction.toArray(), release: leg.release.toArray(), landing: leg.landing, wanted: leg.wanted })),
    beginWalk(phase: number) {
      for (const [i, leg] of legs.entries()) {
        const p = (phase + i * 0.5) % 1
        if (leg.planted || p <= 0.65) continue
        const u = (p - 0.65) / 0.35, fade = 1 - u * u * (3 - 2 * u)
        if (fade > 1e-6) leg.release.copy(leg.correction).divideScalar(fade)
      }
    },
    capture(root: Object3D) {
      root.updateWorldMatrix(true, true)
      for (const leg of legs) {
        if (leg.planted) continue
        leg.foot.getWorldPosition(c)
        if (Math.abs(c.y - leg.groundY) > 0.0005) continue
        leg.target.copy(c); leg.target.y = leg.groundY; leg.foot.getWorldQuaternion(leg.flat)
        leg.planted = true
      }
    },
    update(root: Object3D, support: readonly boolean[], swing: readonly number[], dt: number) {
      root.updateWorldMatrix(true, true)
      for (const [i, leg] of legs.entries()) {
        leg.foot.getWorldPosition(c); leg.foot.getWorldQuaternion(flat); leg.raw.copy(c)
        if (!support[i]) {
          if (leg.planted) { leg.release.copy(leg.target).sub(c); leg.planted = false }
          const u = Math.max(0, Math.min(1, swing[i])), fade = 1 - u * u * (3 - 2 * u)
          leg.correction.copy(leg.release).multiplyScalar(fade); leg.wanted = false
          target.copy(c).add(leg.correction); solve(leg, target, flat)
          continue
        }
        if (!leg.planted) {
          // Retain the rendered swing correction on the zero-delta switch
          // frame, then release it over the same fixed blend as the mixer.
          if (!leg.wanted) { leg.landing = 0; leg.landingCorrection.copy(leg.correction) }
          leg.wanted = true; leg.landing += dt
          const u = Math.min(1, leg.landing / 0.18), fade = 1 - u * u * (3 - 2 * u)
          leg.correction.copy(leg.landingCorrection).multiplyScalar(fade)
          target.copy(c).add(leg.correction)
          if (target.y - leg.groundY > 0.0005) { solve(leg, target, flat); continue }
          leg.target.copy(target); leg.target.y = leg.groundY; leg.flat.copy(flat)
          leg.planted = true; leg.release.set(0, 0, 0); leg.correction.set(0, 0, 0)
        }
        leg.wanted = true
        solve(leg, leg.target, leg.flat)
      }
      return legs.map((leg) => leg.planted)
    },
  }
}
