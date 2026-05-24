import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const clientPath = resolve(repoRoot, 'src/api/client.ts')
const typesPath = resolve(repoRoot, 'src/types/index.ts')

const clientSource = await readFile(clientPath, 'utf8')
const typesSource = await readFile(typesPath, 'utf8')

assert.match(
  typesSource,
  /export interface AgentMcpImportPayload[\s\S]*content: string[\s\S]*mode\?: 'merge' \| 'replace'[\s\S]*apply\?: boolean/,
  'AgentMcpImportPayload 应明确描述导入内容和应用模式'
)

assert.match(
  clientSource,
  /importAgentMcpConfig\(\s*name: string,\s*payload: AgentMcpImportPayload/,
  'API client 应暴露 importAgentMcpConfig(name, payload)'
)

assert.match(
  clientSource,
  /\/api\/agents\/\$\{encodeURIComponent\(name\)\}\/mcp\/import/,
  'MCP 导入应调用 Agent 作用域端点'
)

console.log('api client contract tests passed')
