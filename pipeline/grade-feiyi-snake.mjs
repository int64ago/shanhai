// Offline pigment correction only. The existing BIN prefix, including every
// meshopt geometry/skin/animation byte and all other images, stays byte-identical.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { dirname } from 'node:path'
import { chromium } from 'playwright-core'

const [input, output, evidence] = process.argv.slice(2)
assert(input && output && evidence, 'Usage: node pipeline/grade-feiyi-snake.mjs <original.glb> <graded.glb> <evidence-prefix>')
const sha = data => createHash('sha256').update(data).digest('hex')
const original = await readFile(input)
assert.equal(sha(original), '59f2e6d041a1199c181ec048d4f56d9eafc3c2a0c87991d63b0bb6a4857da70a', 'Use the original runtime model; do not grade twice')
const jsonLength = original.readUInt32LE(12)
const document = JSON.parse(original.subarray(20, 20 + jsonLength).toString())
const bin = original.subarray(28 + jsonLength)
const node = document.nodes.find(n => n.name === 'feiyi_snake_body')
const material = document.materials[document.meshes[node.mesh].primitives[0].material]
const texture = document.textures[material.pbrMetallicRoughness.baseColorTexture.index]
const image = document.images[texture.extensions.EXT_texture_webp.source]
const view = document.bufferViews[image.bufferView]
const sourceImage = bin.subarray(view.byteOffset, view.byteOffset + view.byteLength)

const browser = await chromium.launch({ channel: 'chrome' })
let graded
try {
  const page = await browser.newPage()
  graded = await page.evaluate(async source => {
    const im = new Image(); im.src = source; await im.decode()
    const canvas = document.createElement('canvas'); canvas.width = im.width; canvas.height = im.height
    const ctx = canvas.getContext('2d'); ctx.drawImage(im, 0, 0)
    const data = ctx.getImageData(0, 0, im.width, im.height)
    const knots = [[0,.28],[.03,.31],[.08,.35],[.16,.395],[.25,.45],[.4,.55],[.65,.65],[.85,.85],[1,1]]
    const curve = y => {
      const i = knots.findIndex(p => p[0] >= y)
      if (i <= 0) return knots[0][1]
      const [x0,y0] = knots[i-1], [x1,y1] = knots[i]
      return y0 + (y1-y0) * (y-x0)/(x1-x0)
    }
    // Two eye islands identified by inspecting the original 2048px UV atlas.
    // Feather the mask into the eyelids; do not turn pupils into pale scales.
    const eyes = [[760,531,88,40],[588,65,45,28]]
    let protectedPixels = 0
    for (let i=0; i<data.data.length; i+=4) {
      const x=(i/4)%im.width, y=Math.floor(i/4/im.width)
      const rgb=[data.data[i],data.data[i+1],data.data[i+2]].map(v=>v/255)
      const lum=rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722
      const radius=Math.min(...eyes.map(([cx,cy,rx,ry])=>Math.hypot((x-cx)/rx,(y-cy)/ry)))
      const mask=Math.max(0,Math.min(1,(radius-.65)/.55))
      if (mask===0) protectedPixels++
      const lift=curve(lum)-lum, warmth=Math.max(0,1-lum/.65)
      for(let c=0;c<3;c++) {
        const pigment=rgb[c]+lift+[.022,.006,-.012][c]*warmth
        data.data[i+c]=Math.round(255*Math.max(0,Math.min(1,rgb[c]+(pigment-rgb[c])*mask)))
      }
    }
    ctx.putImageData(data,0,0)
    return {webp:canvas.toDataURL('image/webp',.97),png:canvas.toDataURL('image/png'),width:im.width,height:im.height,knots,eyes,protectedPixels}
  }, `data:${image.mimeType};base64,${sourceImage.toString('base64')}`)
} finally { await browser.close() }
const webp = Buffer.from(graded.webp.split(',')[1], 'base64')
// Append instead of rewriting packed meshopt ranges. This leaves all validated
// geometry, six-foot skinning and motion samples intact without re-exporting.
const padded = Buffer.concat([webp, Buffer.alloc((4-webp.length%4)%4)])
view.byteOffset = bin.length; view.byteLength = webp.length
image.name = 'feiyi_body_grey_umber_graded'; image.mimeType = 'image/webp'
document.buffers[0].byteLength = bin.length + padded.length
let json = Buffer.from(JSON.stringify(document))
json = Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)])
const header = Buffer.alloc(20); header.writeUInt32LE(0x46546c67); header.writeUInt32LE(2,4)
header.writeUInt32LE(28+json.length+bin.length+padded.length,8)
header.writeUInt32LE(json.length,12); header.writeUInt32LE(0x4e4f534a,16)
const binHeader = Buffer.alloc(8); binHeader.writeUInt32LE(bin.length+padded.length); binHeader.writeUInt32LE(0x004e4942,4)
const result = Buffer.concat([header,json,binHeader,bin,padded])
assert.equal(sha(result.subarray(28+json.length,28+json.length+bin.length)),sha(bin))
await mkdir(dirname(output),{recursive:true}); await mkdir(dirname(evidence),{recursive:true})
await writeFile(output,result)
await writeFile(`${evidence}-albedo.png`,Buffer.from(graded.png.split(',')[1],'base64'))
const report={inputSha256:sha(original),outputSha256:sha(result),outputBytes:result.length,sourceImageSha256:sha(sourceImage),gradedImageSha256:sha(webp),preservedBinPrefixSha256:sha(bin),preservedBinPrefixBytes:bin.length,unchangedGeometrySkinAnimations:true,width:graded.width,height:graded.height,srgbLuminanceKnots:graded.knots,eyeMasks:graded.eyes,protectedPixels:graded.protectedPixels,additionalCredits:0}
await writeFile(`${evidence}.json`,JSON.stringify(report,null,2)+'\n')
console.log(JSON.stringify(report,null,2))
