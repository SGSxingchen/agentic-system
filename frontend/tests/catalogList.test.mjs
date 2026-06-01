// 能力库 CatalogList 契约测试（沿用源码文本契约风格，仓库无运行时 DOM 测试栈）。
//
// 校验 CatalogList.tsx：
// 1. 渲染 used_by chips（含 pill 类）
// 2. 每项渲染 kind 徽标
// 3. 「装配」按钮点击调用 onAssemble，且传名称 + 目标 agent（MCP 额外传 env）
// 4. 目标 agent 用 select 选择
// 5. 加载 / 错误 / 空态分别处理
// 6. MCP 行可展开 env 占位输入

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = await readFile(
  resolve(repoRoot, 'src/components/CatalogList.tsx'),
  'utf8'
)

// ─── 1. used_by chips ─────────────────────────────────────
assert.match(
  source,
  /usedBy\.map\(/,
  'CatalogList 应遍历 used_by 渲染 chips'
)
assert.match(
  source,
  /pill[^"]*catalog-row__chip/,
  'used_by chip 应使用 pill + catalog-row__chip 类'
)

// ─── 2. kind 徽标 ─────────────────────────────────────────
assert.match(
  source,
  /catalog-row__kind--\$\{item\.kind\}/,
  'CatalogList 应按 item.kind 渲染徽标类'
)
assert.match(
  source,
  /KIND_LABEL\s*\[\s*item\.kind\s*\]|KIND_LABEL/,
  'CatalogList 应有 kind → 文案映射'
)

// ─── 3. 装配按钮 → onAssemble(name, agent, env) ───────────
assert.match(
  source,
  /onAssemble\(\s*item\.name\s*,\s*effectiveAgent\s*,\s*env\s*\)/,
  '装配应调用 onAssemble(item.name, effectiveAgent, env)'
)
assert.match(
  source,
  /onClick=\{\s*handleAssemble\s*\}/,
  '「装配」按钮 onClick 应绑定 handleAssemble'
)
assert.match(
  source,
  /装配中\.\.\.|装配/,
  '装配按钮应有「装配」/「装配中...」文案'
)

// ─── 3b. 卸下：used_by chip 点击调用 onUnassemble(name, agent) ───
assert.match(
  source,
  /onUnassemble\(\s*item\.name\s*,\s*agent\s*\)/,
  '可卸下 chip 应调用 onUnassemble(item.name, agent)'
)
assert.match(
  source,
  /catalog-row__chip--removable/,
  'used_by chip 应为可卸下按钮形态'
)

// ─── 4. 目标 agent select ─────────────────────────────────
assert.match(
  source,
  /<select[\s\S]*?onChange=\{\(event\)\s*=>\s*setAgentName\(event\.target\.value\)\}/,
  '应用 select + setAgentName 选择目标智能体'
)

// ─── 5. 加载 / 错误 / 空态 ────────────────────────────────
assert.match(source, /if\s*\(\s*loading\s*\)/, 'CatalogList 应处理 loading 态')
assert.match(source, /if\s*\(\s*error\s*\)/, 'CatalogList 应处理 error 态')
assert.match(
  source,
  /items\.length\s*===\s*0/,
  'CatalogList 应处理空态'
)

// ─── 6. MCP env 占位输入 ──────────────────────────────────
assert.match(
  source,
  /item\.kind\s*===\s*'mcp'/,
  'CatalogList 应针对 MCP 行有专门分支'
)
assert.match(
  source,
  /envKeys\.map\(/,
  'MCP 行应遍历 envKeys 渲染占位输入'
)
assert.match(
  source,
  /setEnvDraft/,
  'MCP env 输入应写入 envDraft 草稿'
)

console.log('catalogList contract tests passed')
