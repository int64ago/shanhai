import { Bone, Object3D, Quaternion, Vector3 } from 'three'

/** Exact two-bone stance solve, scoped to Screen Peng's feline leg geometry. */
export function createScreenPengContacts(scene: Object3D) {
  const bone = (name: string) => {
    const node = scene.getObjectByName(name)
    if (!(node instanceof Bone)) throw new Error(`Screen Peng missing ${name}`)
    return node
  }
  const legs = ['back_l', 'front_l', 'back_r', 'front_r'].map((name, index) => ({
    upper: bone(`${name}_upper`), lower: bone(`${name}_lower`), foot: bone(`${name}_foot`),
    phase: index / 4, planted: false, release: new Vector3(), target: new Vector3(), flat: new Quaternion(),
  }))
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
    leg.upper.getWorldPosition(a)
    leg.lower.getWorldPosition(b)
    leg.foot.getWorldPosition(c)
    const upperLength = a.distanceTo(b), lowerLength = b.distanceTo(c)
    axis.subVectors(goal, a)
    const distance = Math.max(Math.abs(upperLength - lowerLength) + 1e-8, Math.min(axis.length(), upperLength + lowerLength - 1e-8))
    axis.normalize()
    // Preserve the baked knee's bend plane. The fallback only handles an
    // exactly straight bind pose; ordinary animation has a nonzero bend.
    pole.subVectors(b, a).addScaledVector(axis, -pole.dot(axis))
    if (pole.lengthSq() < 1e-14) {
      pole.set(0, 0, leg.upper.name.startsWith('front') ? -1 : 1)
      scene.getWorldQuaternion(world)
      pole.applyQuaternion(world).addScaledVector(axis, -pole.dot(axis))
    }
    pole.normalize()
    const along = (upperLength * upperLength - lowerLength * lowerLength + distance * distance) / (2 * distance)
    const height = Math.sqrt(Math.max(0, upperLength * upperLength - along * along))
    knee.copy(a).addScaledVector(axis, along).addScaledVector(pole, height)
    from.subVectors(b, a); to.subVectors(knee, a)
    rotate(leg.upper, from, to)
    leg.lower.getWorldPosition(b); leg.foot.getWorldPosition(c)
    from.subVectors(c, b); to.subVectors(goal, b)
    rotate(leg.lower, from, to)
    leg.foot.parent!.getWorldQuaternion(parent).invert()
    leg.foot.quaternion.copy(parent).multiply(sole)
    leg.foot.updateWorldMatrix(false, true)
  }

  return {
    update(root: Object3D, phase: number, duty: number) {
      root.updateWorldMatrix(true, true)
      for (const leg of legs) {
        const p = (phase + leg.phase) % 1
        if (p >= duty) {
          leg.foot.getWorldPosition(c)
          leg.foot.getWorldQuaternion(flat)
          if (leg.planted) {
            leg.release.copy(leg.target).sub(c)
            leg.planted = false
          }
          // At lift-off, fade the previous stance correction through the
          // swing. Releasing it in one frame would produce a visible snap.
          const u = (p - duty) / (1 - duty), fade = 1 - u * u * (3 - 2 * u)
          target.copy(c).addScaledVector(leg.release, fade)
          solve(leg, target, flat)
          continue
        }
        if (!leg.planted) {
          leg.foot.getWorldPosition(leg.target)
          leg.foot.getWorldQuaternion(leg.flat)
          leg.planted = true
          leg.release.set(0, 0, 0)
        }
        solve(leg, leg.target, leg.flat)
      }
    },
  }
}
