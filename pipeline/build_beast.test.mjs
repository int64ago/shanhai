import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, readFile, copyFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { resolveCompressionArgs } from './compression.ts'

const runner = fileURLToPath(new URL('./build_beast.sh', import.meta.url))

async function fixture(t, changes = {}) {
  const root = await mkdtemp(join(tmpdir(), 'shanhai recipe '))
  t.after(() => rm(root, { recursive: true, force: true }))
  for (const folder of ['pipeline/blender', 'bin', 'raw/body-source', 'raw/wing-source', 'public/models/fixture']) {
    await mkdir(join(root, folder), { recursive: true })
  }
  await copyFile(runner, join(root, 'pipeline/build_beast.sh'))
  const plan = {
    id: 'fixture', archetype: 'avian', bodyLength: 1.45, trimTail: false,
    rigScript: 'pipeline/blender/rig.py', bodyJobId: 'body-source',
    prepareScript: 'pipeline/blender/prepare.py',
    prepareArgs: ['--body-in', '{body.raw}', '--wing-in', '{wing.raw}', '--out-dir', '{outDir}',
      '--label', 'a literal $(touch SHOULD_NOT_EXIST) with spaces', '--empty', ''],
    parts: [{ name: 'wing', jobId: 'wing-source', length: 0.58, texSize: 1024 }],
    ...changes,
  }
  await writeFile(join(root, 'plan.json'), JSON.stringify(plan))
  // The fixture exercises orchestration and atomic output publication, not GLB geometry.
  const glb = Buffer.from('676c5446020000000c000000', 'hex')
  for (const job of ['body-source', 'wing-source']) await writeFile(join(root, `raw/${job}/base_high_pbr.glb`), glb)
  await writeFile(join(root, 'public/models/fixture/body.glb'), 'previous accepted body')
  for (const name of ['rig.py', 'prepare.py', 'normalize.py']) await writeFile(join(root, `pipeline/blender/${name}`), '# CLI fixture\n')
  const pnpm = `#!/usr/bin/env node
const fs = require('node:fs'), path = require('node:path')
const root = path.dirname(__dirname), args = process.argv.slice(2)
fs.appendFileSync(path.join(root, 'calls.jsonl'), JSON.stringify({tool:'pnpm', args})+'\\n')
if (args.includes('tsx')) process.stdout.write(fs.readFileSync(path.join(root,'plan.json')))
else if (args.includes('gltf-transform')) {
  const index=args.indexOf('optimize'); fs.copyFileSync(args[index+1],args[index+2])
} else process.exit(2)
`
  const blender = `#!/usr/bin/env node
const fs = require('node:fs'), path = require('node:path')
const root = path.dirname(__dirname), args=process.argv.slice(2)
const script=path.basename(args[args.indexOf('--python')+1]), cli=args.slice(args.indexOf('--')+1)
fs.appendFileSync(path.join(root,'calls.jsonl'),JSON.stringify({tool:'blender',script,args:cli})+'\\n')
if (script==='prepare.py' && cli[0]==='--body-in') {
  const value=key=>cli[cli.indexOf(key)+1], out=value('--out-dir')
  fs.copyFileSync(value('--body-in'),path.join(out,'body_norm.glb'))
  if (!process.env.FIXTURE_MISSING_PART) fs.copyFileSync(value('--wing-in'),path.join(out,'wing_norm.glb'))
} else fs.copyFileSync(cli[0],cli[1])
`
  for (const [name, text] of [['pnpm', pnpm], ['blender', blender]]) {
    await writeFile(join(root, 'bin', name), text, { mode: 0o755 })
  }
  function run(extraEnv = {}) {
    return spawnSync('/bin/bash', [join(root, 'pipeline/build_beast.sh'), 'fixture'], {
      cwd: root, encoding: 'utf8', env: { ...process.env, PATH: `${join(root, 'bin')}:${process.env.PATH}`,
        BLENDER: join(root, 'bin/blender'), ...extraEnv },
    })
  }
  async function calls() {
    return (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse)
  }
  return { root, run, calls, glb }
}

test('custom preparation receives literal argv and prepares every part before rigging', async t => {
  const f = await fixture(t)
  const result = f.run()
  assert.equal(result.status, 0, result.stdout + result.stderr)
  const calls = await f.calls()
  assert.deepEqual(calls.filter(c => c.tool === 'blender').map(c => c.script), ['prepare.py', 'rig.py'])
  const prepare = calls.find(c => c.script === 'prepare.py').args
  assert.equal(prepare[1], join(f.root, 'raw/body-source/base_high_pbr.glb'))
  assert.equal(prepare[3], join(f.root, 'raw/wing-source/base_high_pbr.glb'))
  assert.equal(prepare[7], 'a literal $(touch SHOULD_NOT_EXIST) with spaces')
  assert.equal(prepare[9], '')
  await assert.rejects(readFile(join(f.root, 'SHOULD_NOT_EXIST')), { code: 'ENOENT' })
  assert.deepEqual(await readFile(join(f.root, 'public/models/fixture/body.glb')), f.glb)
  assert.deepEqual(await readFile(join(f.root, 'public/models/fixture/wing.glb')), f.glb)
})

test('archetype preparation retains normalization of both body and extra parts', async t => {
  const f = await fixture(t, { prepareScript: null, prepareArgs: null })
  const result = f.run()
  assert.equal(result.status, 0, result.stdout + result.stderr)
  assert.deepEqual((await f.calls()).filter(c => c.tool === 'blender').map(c => c.script),
    ['normalize.py', 'rig.py', 'normalize.py'])
})

test('custom preparation supports a body with no extra parts', async t => {
  const f = await fixture(t, { parts: [], prepareArgs: ['{body.raw}', '{body.out}'] })
  const result = f.run()
  assert.equal(result.status, 0, result.stdout + result.stderr)
  assert.deepEqual((await f.calls()).filter(c => c.tool === 'blender').map(c => c.script), ['prepare.py', 'rig.py'])
  assert.deepEqual(await readFile(join(f.root, 'public/models/fixture/body.glb')), f.glb)
})

test('compression config retains defaults and rejects unsupported or malformed options', () => {
  assert.deepEqual(resolveCompressionArgs(undefined), [])
  assert.deepEqual(resolveCompressionArgs({}), [])
  assert.deepEqual(resolveCompressionArgs({ weld: false, resample: false, meshoptLevel: 'medium' }),
    ['--weld', 'false', '--resample', 'false', '--meshopt-level', 'medium'])
  for (const invalid of [null, [], false, { weld: 'false' }, { resample: 0 }, { meshoptLevel: 'low' }, { simplify: true }]) {
    assert.throws(() => resolveCompressionArgs(invalid), /recipe\.compression/)
  }
})

test('compression overrides reach the body and every extra part without changing defaults', async t => {
  const args = ['--weld', 'false', '--resample', 'false', '--meshopt-level', 'medium']
  const f = await fixture(t, { compressionArgs: args })
  const result = f.run()
  assert.equal(result.status, 0, result.stdout + result.stderr)
  const optimizers = (await f.calls()).filter(c => c.tool === 'pnpm' && c.args.includes('gltf-transform'))
  assert.equal(optimizers.length, 2)
  for (const call of optimizers) assert.deepEqual(call.args.slice(-args.length), args)
})

test('missing custom part fails before overwriting the accepted model', async t => {
  const f = await fixture(t)
  const result = f.run({ FIXTURE_MISSING_PART: '1' })
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /wing_norm\.glb/)
  assert.equal(await readFile(join(f.root, 'public/models/fixture/body.glb'), 'utf8'), 'previous accepted body')
  assert.deepEqual((await f.calls()).filter(c => c.tool === 'blender').map(c => c.script), ['prepare.py'])
})

test('unknown argument placeholder fails before Blender', async t => {
  const f = await fixture(t, { prepareArgs: ['{missing.raw}'] })
  const result = f.run()
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /Unknown preparation placeholder/)
  assert.equal((await f.calls()).filter(c => c.tool === 'blender').length, 0)
})

test('missing part job does not disappear through process substitution', async t => {
  const f = await fixture(t, { parts: [{ name: 'wing', jobId: null, length: 0.58 }] })
  const result = f.run()
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /缺少 jobId/)
  assert.equal((await f.calls()).filter(c => c.tool === 'blender').length, 0)
})
