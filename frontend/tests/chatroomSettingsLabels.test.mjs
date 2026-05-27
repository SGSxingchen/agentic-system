import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = resolve(repoRoot, 'src/components/chatroomSettingsLabels.ts')
const outPath = resolve(tmpdir(), `chatroomSettingsLabels-${process.pid}.mjs`)
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

const { SETTING_LABELS, getSettingLabel } = await import(
  pathToFileURL(outPath).href + `?cache=${Date.now()}`
)

// B5: localized labels for chatroom settings
assert.equal(SETTING_LABELS.auto_host.label, '自动主持人', 'auto_host label localized')
assert.match(
  SETTING_LABELS.auto_host.hint,
  /没被.*@.*主持/,
  'auto_host hint mentions @ + 主持'
)

assert.equal(SETTING_LABELS.host_agent.label, '主持 Agent', 'host_agent label localized')
assert.ok(SETTING_LABELS.host_agent.hint.length > 0, 'host_agent hint non-empty')

assert.equal(SETTING_LABELS.recent_n.label, '上下文条数', 'recent_n label localized')
assert.ok(SETTING_LABELS.recent_n.hint.length > 0, 'recent_n hint non-empty')

assert.equal(
  SETTING_LABELS.summary_threshold_m.label,
  '摘要触发阈值',
  'summary_threshold_m label localized'
)
assert.ok(
  SETTING_LABELS.summary_threshold_m.hint.length > 0,
  'summary_threshold_m hint non-empty'
)

assert.equal(
  SETTING_LABELS.max_relay_depth.label,
  '最大接力层数',
  'max_relay_depth label localized'
)
assert.ok(
  SETTING_LABELS.max_relay_depth.hint.length > 0,
  'max_relay_depth hint non-empty'
)

assert.equal(SETTING_LABELS.max_members.label, '房间成员上限', 'max_members label localized')

assert.equal(
  SETTING_LABELS.allow_agent_invite.label,
  '允许 Agent 互相拉人',
  'allow_agent_invite label localized'
)
assert.ok(
  SETTING_LABELS.allow_agent_invite.hint.length > 0,
  'allow_agent_invite hint non-empty'
)

// helper: getSettingLabel returns label & hint by key, gracefully degrades for unknown keys
const known = getSettingLabel('auto_host')
assert.equal(known.label, '自动主持人')
assert.match(known.hint, /主持/)

const unknown = getSettingLabel('nonexistent_key')
assert.equal(unknown.label, 'nonexistent_key', 'unknown key falls back to raw key')
assert.equal(unknown.hint, '', 'unknown key has empty hint')

console.log('chatroomSettingsLabels.test.mjs OK')
