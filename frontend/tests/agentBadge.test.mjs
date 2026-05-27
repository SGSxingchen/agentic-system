import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = resolve(repoRoot, 'src/components/agentBadge.ts')
const outPath = resolve(tmpdir(), `agentBadge-${process.pid}.mjs`)
const source = await readFile(sourcePath, 'utf8')
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    verbatimModuleSyntax: true,
  },
  fileName: sourcePath,
})
await mkdir(dirname(outPath), { recursive: true })
await writeFile(outPath, transpiled.outputText, 'utf8')

const { senderToDisplay, agentMetaFromList } = await import(
  pathToFileURL(outPath).href + `?cache=${Date.now()}`
)

// B4: senderToDisplay derives name + model badge from sender + agentMeta map
const meta = { reviewer: { model: 'gpt-4o' }, planner: { model: 'claude-opus-4-7' } }

let r = senderToDisplay('agent:reviewer', meta)
assert.equal(r.name, 'reviewer')
assert.equal(r.model, 'gpt-4o', 'model picked from agentMeta')

// Missing model gracefully degrades
r = senderToDisplay('agent:custom_unknown', meta)
assert.equal(r.name, 'custom_unknown')
assert.equal(r.model, undefined, 'unknown agent has no model')

// Empty agent name after prefix
r = senderToDisplay('agent:', meta)
assert.equal(r.name, 'agent', 'empty agent name falls back to "agent"')
assert.equal(r.model, undefined)

// Non-agent senders
r = senderToDisplay('user', meta)
assert.equal(r.name, '用户')
assert.equal(r.model, undefined, 'user has no model badge')

r = senderToDisplay('system', meta)
assert.equal(r.name, '系统')
assert.equal(r.model, undefined)

// Empty meta map should not throw
r = senderToDisplay('agent:reviewer', {})
assert.equal(r.name, 'reviewer')
assert.equal(r.model, undefined)

// agentMetaFromList builds a name → {model} map from AgentInfo[]-like
const agents = [
  { name: 'planner', model: 'gpt-4o-mini' },
  { name: 'coder', model: null },
  { name: 'reviewer' }, // no model field
]
const map = agentMetaFromList(agents)
assert.equal(map.planner.model, 'gpt-4o-mini')
assert.equal(map.coder.model, undefined, 'null model becomes undefined')
assert.equal(map.reviewer.model, undefined)

// Unknown name fallback in agentMetaFromList: keys are names
assert.deepEqual(Object.keys(map).sort(), ['coder', 'planner', 'reviewer'])

console.log('agentBadge.test.mjs OK')
