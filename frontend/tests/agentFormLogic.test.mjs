import assert from 'node:assert/strict'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import ts from 'typescript'

const repoRoot = resolve(dirname(new URL(import.meta.url).pathname), '..')
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

const { submitAgentForm, parseAgentRuntimeConfig } = await import(outPath + `?cache=${Date.now()}`)

const baseForm = {
  name: 'writer_agent',
  description: 'Writes concise summaries',
  system_prompt: 'You write concise summaries.',
  tools: ['code_parser'],
  output_format: 'text',
  max_iterations: 10,
  skills_json: JSON.stringify({ enabled: true, directories: [], items: [], disabled: [], strategy: 'metadata_and_instructions' }),
  mcp_servers_json: '[]',
}

function createMockApi() {
  const calls = []
  return {
    calls,
    api: {
      async createAgent(data) {
        calls.push({ method: 'createAgent', data })
        return { status: 'ok', data: { name: data.name } }
      },
      async updateAgent(name, data) {
        calls.push({ method: 'updateAgent', name, data })
        return { status: 'ok', data: { name, ...data } }
      },
    },
  }
}

{
  const { calls, api } = createMockApi()
  const response = await submitAgentForm({ editingAgent: '__new__', form: baseForm, api })
  assert.equal(response.status, 'ok')
  assert.equal(calls.length, 1, 'clicking save for a new Agent should call createAgent once')
  assert.equal(calls[0].method, 'createAgent')
  assert.equal(calls[0].data.name, 'writer_agent')
  assert.deepEqual(calls[0].data.tools, ['code_parser'])
}

{
  const { calls, api } = createMockApi()
  const response = await submitAgentForm({
    editingAgent: 'assistant',
    form: { ...baseForm, name: 'assistant', description: 'Updated assistant' },
    api,
  })
  assert.equal(response.status, 'ok')
  assert.equal(calls.length, 1, 'clicking save while editing should call updateAgent once')
  assert.equal(calls[0].method, 'updateAgent')
  assert.equal(calls[0].name, 'assistant')
  assert.equal(calls[0].data.description, 'Updated assistant')
}

{
  assert.deepEqual(parseAgentRuntimeConfig({ skills_json: '', mcp_servers_json: '' }), {
    skills: null,
    mcpServers: [],
  })
}

{
  await assert.rejects(
    () => submitAgentForm({ editingAgent: '__new__', form: { ...baseForm, skills_json: '[' }, api: createMockApi().api }),
    /Skills 配置 不是合法 JSON/
  )
}

console.log('agentFormLogic tests passed')
