import { useEffect, useMemo } from 'react'
import { Box3, CatmullRomCurve3, Group, Matrix4, Mesh, Object3D, Quaternion, Raycaster, Shape, ShapeGeometry, SphereGeometry, TubeGeometry, Vector3 } from 'three'
import { Quadruped } from '../Quadruped'
import { audio } from '../../systems/audio/AudioEngine'
import { createInkMaterial } from '../../systems/ink/inkMaterial'
import { createOutline } from '../../systems/ink/inkify'

/** Explicit unbranched horns and almond human eyes follow the skull through all actions. */
function HeadDetails({ scene }: { scene: Object3D }) {
  const rig = useMemo(() => {
    const material = createInkMaterial({ map: null, tint: '#c2a47a', saturation: 0.75 })
    const horns = [0, 1].flatMap((row) => [1, -1].map((side) => {
      const curve = new CatmullRomCurve3([
        new Vector3(),
        new Vector3(side * (row ? 0.065 : 0.035), 0.055, row ? -0.025 : 0.025),
        new Vector3(side * (row ? 0.12 : 0.065), row ? 0.17 : 0.13, row ? -0.04 : 0.055),
        new Vector3(side * (row ? 0.10 : 0.045), row ? 0.29 : 0.21, row ? 0.005 : 0.095),
      ])
      const geometry = new TubeGeometry(curve, 32, 1, 12, false)
      const position = geometry.getAttribute('position')
      const normal = geometry.getAttribute('normal')
      const center = new Vector3()
      for (let ring = 0; ring <= 32; ring++) {
        const u = ring / 32
        curve.getPointAt(u, center)
        const radius = (row ? 0.028 : 0.023) * (1 - u) ** 0.8 + 0.0006
        for (let k = 0; k <= 12; k++) {
          const i = ring * 13 + k
          position.setXYZ(i, center.x + normal.getX(i) * radius, center.y + normal.getY(i) * radius, center.z + normal.getZ(i) * radius)
        }
      }
      position.needsUpdate = true
      geometry.computeBoundingSphere()
      const mesh = new Mesh(geometry, material)
      mesh.name = `zhuhuai_horn_${row}_${side}`
      const holder = new Group()
      holder.name = `${mesh.name}_mount`
      holder.matrixAutoUpdate = false
      holder.add(mesh, createOutline(mesh, 0.002))
      return { holder, row, side }
    }))
    const white = createInkMaterial({ map: null, tint: '#eee2c8', saturation: 0.7 })
    const iris = createInkMaterial({ map: null, tint: '#6a4229', saturation: 0.9 })
    const dark = createInkMaterial({ map: null, tint: '#17120e', saturation: 0.4 })
    const lid = createInkMaterial({ map: null, tint: '#684b39', saturation: 0.8 })
    const eyes = [1, -1].map((side) => {
      const holder = new Group()
      holder.name = `zhuhuai_human_eye_${side}`
      holder.matrixAutoUpdate = false
      const eye = new Group()
      const almond = new Shape()
      almond.moveTo(-0.025, 0)
      almond.quadraticCurveTo(0, 0.025, 0.025, 0)
      almond.quadraticCurveTo(0, -0.021, -0.025, 0)
      const sclera = new Mesh(new ShapeGeometry(almond, 20), white)
      const color = new Mesh(new SphereGeometry(0.0105, 24, 16), iris)
      color.scale.z = 0.22
      color.position.z = 0.002
      const pupil = new Mesh(new SphereGeometry(0.0052, 20, 12), dark)
      pupil.scale.z = 0.25
      pupil.position.z = 0.004
      eye.add(sclera, color, pupil)
      for (const upper of [true, false]) {
        const curve = new CatmullRomCurve3([
          new Vector3(-0.026, 0, 0),
          new Vector3(0, upper ? 0.013 : -0.011, 0),
          new Vector3(0.026, 0, 0),
        ])
        eye.add(new Mesh(new TubeGeometry(curve, 24, 0.002, 8, false), lid))
      }
      holder.add(eye)
      return { holder, side }
    })
    return { horns, eyes }
  }, [])

  useEffect(() => {
    // Updating SkinnedMesh here also refreshes its inverse bind matrix after
    // the outer beast group moves; raycasts then read actual quantized skin.
    scene.updateWorldMatrix(true, false)
    scene.updateMatrixWorld(true)
    const head = scene.getObjectByName('head')
    if (!head) throw new Error('诸怀缺少 head 骨骼')
    const sceneInverse = scene.matrixWorld.clone().invert()
    const inverseRest = new Matrix4().multiplyMatrices(sceneInverse, head.matrixWorld).invert()
    const bounds = new Box3()
    const surfaces: Mesh[] = []
    const vertex = new Vector3()
    scene.traverse((node) => {
      if (!(node instanceof Mesh) || node.userData.inkOutline) return
      surfaces.push(node)
      const matrix = new Matrix4().multiplyMatrices(sceneInverse, node.matrixWorld)
      const position = node.geometry.getAttribute('position')
      for (let i = 0; i < position.count; i++) bounds.expandByPoint(node.getVertexPosition(i, vertex).applyMatrix4(matrix))
    })
    const length = bounds.max.z - bounds.min.z
    for (const item of rig.horns) {
      const x = item.side * (item.row ? 0.045 : 0.052)
      const z = bounds.max.z - length * (item.row ? 0.245 : 0.155)
      const origin = new Vector3(x, bounds.max.y + 1, z).applyMatrix4(scene.matrixWorld)
      const direction = new Vector3(0, -1, 0).transformDirection(scene.matrixWorld)
      const hit = new Raycaster(origin, direction).intersectObjects(surfaces, false)[0]
      if (!hit) throw new Error('诸怀角根缺少头部表面')
      const point = hit.point.applyMatrix4(sceneInverse)
      point.y -= 0.008
      item.holder.matrix.copy(inverseRest).multiply(new Matrix4().makeTranslation(point))
      head.add(item.holder)
    }
    const height = bounds.max.y - bounds.min.y
    for (const item of rig.eyes) {
      const origin = new Vector3(item.side * 0.064, bounds.min.y + height * 0.82, bounds.max.z + 1).applyMatrix4(scene.matrixWorld)
      const direction = new Vector3(0, 0, -1).transformDirection(scene.matrixWorld)
      const hit = new Raycaster(origin, direction).intersectObjects(surfaces, false)[0]
      if (!hit) throw new Error('诸怀人目缺少面部表面')
      const point = hit.point.applyMatrix4(sceneInverse)
      point.z += 0.009
      const orientation = new Quaternion().setFromUnitVectors(new Vector3(0, 0, 1), new Vector3(item.side * 0.4, 0, 0.92).normalize())
      const placement = new Matrix4().compose(point, orientation, new Vector3(1, 1, 1))
      item.holder.matrix.copy(inverseRest).multiply(placement)
      head.add(item.holder)
    }
    if (import.meta.env.DEV) {
      let count = 0
      head.traverse((node) => { if (node instanceof Mesh && node.name.startsWith('zhuhuai_horn_')) count++ })
      if (count !== 4) throw new Error(`诸怀应为四角，实际挂接 ${count}`)
      console.info(`[zhuhuai] horns ${count}, human eyes ${rig.eyes.length}`)
    }
    return () => { for (const item of [...rig.horns, ...rig.eyes]) head.remove(item.holder) }
  }, [scene, rig])
  return null
}

const call = (pan: number) => audio.zhuhuaiCall(pan)

export function Zhuhuai() {
  return <Quadruped id="zhuhuai" appendages={HeadDetails} specialEffect={null} onCall={call} />
}
