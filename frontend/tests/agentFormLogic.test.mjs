import assert from 'node:assert/strict'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = resolve(repoRoot, 'src/components/agentFormLogic.ts')
const outPath = resolve(tmpdir(), `agentFormLogic-${process.pid}.mjs`)
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

try {
  const {
    agentToDraft,
    buildAgentUpdatePayload,
  } = await import(pathToFileURL(outPath).href + `?cache=${Date.now()}`)

  const globalAgent = {
    name: 'assistant',
    status: 'idle',
    capabilities: ['code_parser'],
    description: '通用助手',
    system_prompt: '保持正式、准确。',
    output_format: 'text',
    max_iterations: 8,
    default_workspace_id: null,
    llm: {
      source: 'global_default',
      provider: 'openai',
      model: 'gpt-global',
    },
  }

  const inheritedDraft = agentToDraft(globalAgent)
  assert.equal(inheritedDraft.llm_provider, '')
  assert.equal(inheritedDraft.llm_model, '')
  assert.deepEqual(buildAgentUpdatePayload(inheritedDraft), {
    description: '通用助手',
    system_prompt: '保持正式、准确。',
    output_format: 'text',
    max_iterations: 8,
    tools: ['code_parser'],
    default_workspace_id: null,
  })

  const agentScopedDraft = agentToDraft({
    ...globalAgent,
    llm: {
      source: 'agent_config',
      provider: 'openai',
      model: 'gpt-agent',
      base_url: 'https://api.example.test/v1',
      temperature: 0.4,
      max_tokens: 4096,
    },
  })
  assert.equal(agentScopedDraft.llm_model, 'gpt-agent')
  assert.deepEqual(
    buildAgentUpdatePayload({
      ...agentScopedDraft,
      llm_provider: '',
      llm_model: '',
      llm_base_url: '',
      llm_api_key: '',
      llm_temperature: '',
      llm_max_tokens: '',
    }).llm,
    null
  )

  const payload = buildAgentUpdatePayload({
    ...agentScopedDraft,
    default_workspace_id: 'workspace_1',
    llm_api_key: 'sk-test',
    llm_temperature: '0.7',
    llm_max_tokens: '2048',
  })
  assert.deepEqual(payload.llm, {
    provider: 'openai',
    model: 'gpt-agent',
    base_url: 'https://api.example.test/v1',
    api_key: 'sk-test',
    temperature: 0.7,
    max_tokens: 2048,
  })
  assert.equal(payload.default_workspace_id, 'workspace_1')

  assert.throws(
    () => buildAgentUpdatePayload({ ...agentScopedDraft, llm_temperature: 'hot' }),
    /模型温度 必须是有效数字/
  )

  console.log('agent form logic tests passed')
} finally {
  await rm(outPath, { force: true })
}
