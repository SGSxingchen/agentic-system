// 能力库 — API client + 三面板端点契约测试。
//
// 校验：
// 1. client.ts 暴露 listCatalog(kind) → GET /api/catalog/{kind}
// 2. client.ts 暴露 assembleCapability(kind,name,agent,env) → POST /api/catalog/{kind}/{name}/assemble
// 3. ToolsPanel 调 listCatalog('tools') + assembleCapability('tools', …)
// 4. SkillsPanel 调 listCatalog('skills') + assembleCapability('skills', …)
// 5. McpPanel 调 listCatalog('mcp') + assembleCapability('mcp', …)
// 6. 三面板都渲染 <CatalogList/>
// 7. nav 接线：Sidebar 有 tools 项（在 skills 之上），App.renderPanel 映射 tools，PanelType 含 'tools'

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFile(resolve(repoRoot, rel), 'utf8')

const clientSource = await read('src/api/client.ts')
const toolsSource = await read('src/components/ToolsPanel.tsx')
const skillsSource = await read('src/components/SkillsPanel.tsx')
const mcpSource = await read('src/components/McpPanel.tsx')
const sidebarSource = await read('src/components/Sidebar.tsx')
const appSource = await read('src/App.tsx')
const typesSource = await read('src/types/index.ts')

// ─── 1. listCatalog → GET /api/catalog/{kind} ────────────
assert.match(
  clientSource,
  /export async function listCatalog\b/,
  'client.ts 应暴露 listCatalog'
)
assert.match(
  clientSource,
  /`\/api\/catalog\/\$\{kind\}`/,
  'listCatalog 应请求 /api/catalog/{kind}'
)

// ─── 2. assembleCapability → POST /api/catalog/{kind}/{name}/assemble
assert.match(
  clientSource,
  /export async function assembleCapability\b/,
  'client.ts 应暴露 assembleCapability'
)
assert.match(
  clientSource,
  /\/api\/catalog\/\$\{kind\}\/\$\{encodeURIComponent\(name\)\}\/assemble/,
  'assembleCapability 应 POST /api/catalog/{kind}/{name}/assemble'
)
assert.match(
  clientSource,
  /invalidateGetCache\('\/api\/agents',\s*'\/api\/catalog'\)/,
  '装配成功后应失效 agents / catalog 缓存'
)

// ─── 3. ToolsPanel ───────────────────────────────────────
assert.match(toolsSource, /listCatalog\(\s*'tools'\s*\)/, "ToolsPanel 应调 listCatalog('tools')")
assert.match(
  toolsSource,
  /assembleCapability\(\s*'tools'/,
  "ToolsPanel 应调 assembleCapability('tools', …)"
)
assert.match(toolsSource, /<CatalogList/, 'ToolsPanel 应渲染 CatalogList')

// ─── 4. SkillsPanel ──────────────────────────────────────
assert.match(skillsSource, /listCatalog\(\s*'skills'\s*\)/, "SkillsPanel 应调 listCatalog('skills')")
assert.match(
  skillsSource,
  /assembleCapability\(\s*'skills'/,
  "SkillsPanel 应调 assembleCapability('skills', …)"
)
assert.match(skillsSource, /<CatalogList/, 'SkillsPanel 应渲染 CatalogList')
assert.match(skillsSource, /能力库/, 'SkillsPanel 应有「能力库」段标题')
// 既有 per-agent 功能保留
assert.match(skillsSource, /已挂载 Skill 列表/, 'SkillsPanel 应保留既有「已挂载 Skill 列表」')

// ─── 5. McpPanel ─────────────────────────────────────────
assert.match(mcpSource, /listCatalog\(\s*'mcp'\s*\)/, "McpPanel 应调 listCatalog('mcp')")
assert.match(
  mcpSource,
  /assembleCapability\(\s*'mcp'/,
  "McpPanel 应调 assembleCapability('mcp', …)"
)
assert.match(mcpSource, /<CatalogList/, 'McpPanel 应渲染 CatalogList')
assert.match(mcpSource, /能力库/, 'McpPanel 应有「能力库」段标题')
// 既有 import / per-agent 功能保留
assert.match(mcpSource, /按 Agent 编辑/, 'McpPanel 应保留既有「按 Agent 编辑」')

// ─── 6. 导航接线 ─────────────────────────────────────────
// Sidebar: tools 项存在且在 skills 之上
assert.match(
  sidebarSource,
  /key:\s*'tools'/,
  "Sidebar 应有 tools nav 项"
)
const toolsIdx = sidebarSource.indexOf("key: 'tools'")
const skillsIdx = sidebarSource.indexOf("key: 'skills'")
assert.ok(
  toolsIdx > 0 && skillsIdx > 0 && toolsIdx < skillsIdx,
  'Sidebar 中 tools 项应排在 skills 之上'
)

// App.renderPanel 映射 tools → ToolsPanel
assert.match(appSource, /case\s*'tools':/, "App.renderPanel 应有 case 'tools'")
assert.match(appSource, /<ToolsPanel\s*\/>/, 'App 应渲染 ToolsPanel')

// PanelType 含 'tools'
assert.match(typesSource, /\|\s*'tools'/, "PanelType 联合类型应包含 'tools'")

console.log('catalogPanels contract tests passed')
