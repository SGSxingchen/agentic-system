import assert from 'node:assert/strict'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = resolve(repoRoot, 'src/components/agentFormLogic.ts')
const outPath = resolve(tmpdir(), `agentTokenBudget-${process.pid}.mjs`)
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

const typesPath = resolve(repoRoot, 'src/types/index.ts')
const agentPanelPath = resolve(repoRoot, 'src/components/AgentPanel.tsx')
const typesSource = await readFile(typesPath, 'utf8')
const agentPanelSource = await readFile(agentPanelPath, 'utf8')

try {
  const { agentToDraft, buildAgentUpdatePayload, hasAgentDraftChanges } =
    await import(pathToFileURL(outPath).href + `?cache=${Date.now()}`)

  // A23.3: AgentInfo 类型必须暴露 token_budget?: number
  assert.match(
    typesSource,
    /token_budget\?: number/,
    'AgentInfo 应声明可选 token_budget 字段',
  )

  // A23.3: AgentDraft 草稿应包含 token_budget（保存时上传）
  // 用空字符串表达"未指定，继承全局"，正数表达显式覆盖。
  const agentWithBudget = {
    name: 'planner',
    status: 'idle',
    capabilities: [],
    description: '聊天室主持人',
    output_format: 'text',
    max_iterations: 10,
    token_budget: 500000,
  }

  const draft = agentToDraft(agentWithBudget)
  assert.equal(
    draft.token_budget,
    '500000',
    'agentToDraft 应把 token_budget 转字符串以兼容空态（继承全局）',
  )

  const inheritedDraft = agentToDraft({
    name: 'reviewer',
    status: 'idle',
    capabilities: [],
    output_format: 'text',
    max_iterations: 8,
  })
  assert.equal(
    inheritedDraft.token_budget,
    '',
    'token_budget 缺失时草稿应为空字符串（占位"继承全局"）',
  )

  // 保存 payload：空字符串 → 不发送（继承全局）；有效数字 → 发送 number
  const inheritedPayload = buildAgentUpdatePayload(inheritedDraft)
  assert.equal(
    'token_budget' in inheritedPayload,
    false,
    '空 token_budget 不应进入保存 payload，让后端走继承逻辑',
  )

  const overridePayload = buildAgentUpdatePayload({ ...draft, token_budget: '800000' })
  assert.equal(overridePayload.token_budget, 800000, '有效 token_budget 应作为 number 发送')

  // 校验：非数字应抛错（与 max_tokens / temperature 同模式）
  assert.throws(
    () => buildAgentUpdatePayload({ ...draft, token_budget: 'abc' }),
    /token.*预算|token_budget|必须是有效数字/i,
    'token_budget 非数字应抛错',
  )

  // hasAgentDraftChanges：草稿改 token_budget 应被识别为变更
  assert.equal(
    hasAgentDraftChanges(agentWithBudget, { ...draft, token_budget: '900000' }),
    true,
    '修改 token_budget 应被检测为变更',
  )

  // AgentPanel.tsx 必须渲染 token_budget 输入框（min/max/step 校验 + 占位提示）
  assert.match(
    agentPanelSource,
    /token_budget/,
    'AgentPanel 表单应包含 token_budget 字段',
  )
  assert.match(
    agentPanelSource,
    /min=\{?10000\}?/,
    'token_budget 输入框应限制 min=10000',
  )
  assert.match(
    agentPanelSource,
    /max=\{?2000000\}?/,
    'token_budget 输入框应限制 max=2000000',
  )
  assert.match(
    agentPanelSource,
    /step=\{?10000\}?/,
    'token_budget 输入框 step=10000',
  )
  assert.match(
    agentPanelSource,
    /继承全局默认/,
    'token_budget placeholder 应提示"继承全局默认 (300000)"',
  )

  console.log('agent token_budget contract tests passed')
} finally {
  await rm(outPath, { force: true })
}
