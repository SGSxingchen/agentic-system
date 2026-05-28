// A8 — AgentPanel 顶部"重新装载"按钮契约测试
//
// 验证：
//   1. api/client.ts 暴露 reloadEvolutionExtensions() 调用 POST /api/evolution/reload
//   2. AgentPanel.tsx 在 page__actions 中渲染"重新装载"按钮，点击后调用该 API
//   3. AgentPanel.tsx 维护 reloading / lastReload 本地状态用于 UI 反馈
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const clientSource = await readFile(
  resolve(repoRoot, 'src/api/client.ts'),
  'utf8',
)
const panelSource = await readFile(
  resolve(repoRoot, 'src/components/AgentPanel.tsx'),
  'utf8',
)

// API client must expose reloadEvolutionExtensions()
assert.match(
  clientSource,
  /export async function reloadEvolutionExtensions\b/,
  'client.ts 应暴露 reloadEvolutionExtensions',
)
assert.match(
  clientSource,
  /\/api\/evolution\/reload/,
  'reload helper 应调用 /api/evolution/reload',
)

// AgentPanel must render the reload button + states
assert.match(
  panelSource,
  /reloadEvolutionExtensions/,
  'AgentPanel 应导入 reloadEvolutionExtensions',
)
assert.match(
  panelSource,
  /重新装载/,
  'AgentPanel 顶部应有"重新装载"按钮',
)
assert.match(
  panelSource,
  /装载中/,
  'AgentPanel 应在 reload 进行中显示"装载中…"',
)
assert.match(
  panelSource,
  /上次装载/,
  'AgentPanel 应显示"上次装载"时间戳',
)
assert.match(
  panelSource,
  /useState[<(]\s*boolean[>)]?\s*\(\s*false\s*\)/,
  'AgentPanel 应有 reloading: boolean 状态',
)

console.log('agentPanelReload.test.mjs OK')
