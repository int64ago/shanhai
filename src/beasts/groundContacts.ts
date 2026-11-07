import { Bone, Object3D, Quaternion, Vector3 } from 'three'

/** Hold stance ankles and entire soles in world space while a baked gait turns. */
export function createGroundContacts(scene: Object3D, legs: readonly string[]) {
  const bone = (name: string) => {
    const node = scene.getObjectByName(name)
    if (!(node instanceof Bone)) throw new Error(`Missing contact bone: ${name}`)
    return node
  }
  const contacts = legs.map((name, index) => ({
    foot: bone(`${name}_foot`),
    chain: [bone(`${name}_lower`), bone(`${name}_upper`)],
    phase: index / legs.length,
    planted: false,
    target: new Vector3(),
    flat: new Quaternion(),
  }))
  const joint = new Vector3(), end = new Vector3(), from = new Vector3(), to = new Vector3()
  const parent = new Quaternion(), world = new Quaternion(), turn = new Quaternion()

  return {
    reset() {
      for (const contact of contacts) contact.planted = false
    },
    update(root: Object3D, phase: number, duty: number) {
      root.updateWorldMatrix(true, true)
      for (const contact of contacts) {
        if ((phase + contact.phase) % 1 >= duty) {
          contact.planted = false
          continue
        }
        if (!contact.planted) {
          contact.foot.getWorldPosition(contact.target)
          contact.foot.getWorldQuaternion(contact.flat)
          contact.planted = true
        }
        // Two-joint CCD corrects the ankle, then restore the planted sole's yaw.
        for (let iteration = 0; iteration < 24; iteration++) {
          contact.foot.getWorldPosition(end)
          if (end.distanceToSquared(contact.target) < 1e-10) break
          for (const node of contact.chain) {
            node.getWorldPosition(joint)
            contact.foot.getWorldPosition(end)
            from.subVectors(end, joint).normalize()
            to.subVectors(contact.target, joint).normalize()
            turn.setFromUnitVectors(from, to)
            node.getWorldQuaternion(world)
            node.parent!.getWorldQuaternion(parent).invert()
            node.quaternion.copy(parent).multiply(turn).multiply(world)
            node.updateWorldMatrix(false, true)
          }
        }
        contact.foot.parent!.getWorldQuaternion(parent).invert()
        contact.foot.quaternion.copy(parent).multiply(contact.flat)
        contact.foot.updateWorldMatrix(false, true)
      }
    },
  }
}
