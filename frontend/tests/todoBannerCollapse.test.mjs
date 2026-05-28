// A25 — TodoBanner 默认折叠 + 空态隐藏静态契约。
//
// 校验 ChatroomPanel.tsx 中的 TodoBanner 组件：
// 1. todos 为空时 banner 完全不渲染（return null）
// 2. 有 todo 时折叠态显示 chip 形如 "📋 N 个待办 / M 进行中 / K 已完成"
// 3. 折叠/展开使用 useState (默认 false)
// 4. 展开态有关闭按钮（✕）
// 5. CSS 中含 chatroom-todo-banner__chip / chatroom-todo-banner__expanded

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const panelPath = resolve(repoRoot, 'src/components/ChatroomPanel.tsx')
const cssPath = resolve(repoRoot, 'src/components/ChatroomPanel.css')

const panelSource = await readFile(panelPath, 'utf8')
const cssSource = await readFile(cssPath, 'utf8')

// ─── 1. 空态完全隐藏 ──────────────────────────────────────
assert.match(
  panelSource,
  /function\s+TodoBanner[\s\S]*?todos\.length\s*===\s*0[\s\S]*?return\s+null/,
  'TodoBanner 在 todos.length === 0 时应直接 return null（空态隐藏）'
)

// ─── 2. useState 默认 false（折叠态） ─────────────────────
assert.match(
  panelSource,
  /function\s+TodoBanner[\s\S]*?useState\s*<\s*boolean\s*>\s*\(\s*false\s*\)|function\s+TodoBanner[\s\S]*?useState\s*\(\s*false\s*\)/,
  'TodoBanner 应使用 useState(false) 默认折叠'
)

// ─── 3. 折叠态 chip 文案 ──────────────────────────────────
assert.match(
  panelSource,
  /个待办/,
  'TodoBanner 折叠 chip 应包含 "个待办" 字样'
)
assert.match(
  panelSource,
  /进行中/,
  'TodoBanner 折叠 chip 应包含 "进行中" 字样'
)
assert.match(
  panelSource,
  /已完成|完成/,
  'TodoBanner 折叠 chip 应包含 "已完成" 或 "完成" 字样'
)

// ─── 4. 关闭按钮（✕） ────────────────────────────────────
assert.match(
  panelSource,
  /function\s+TodoBanner[\s\S]*?✕|function\s+TodoBanner[\s\S]*?&times;|function\s+TodoBanner[\s\S]*?×/,
  'TodoBanner 展开态应有关闭按钮（✕ 或 × 字符）'
)

// ─── 5. CSS 类名 ─────────────────────────────────────────
assert.match(
  cssSource,
  /\.chatroom-todo-banner__chip/,
  'CSS 应包含 .chatroom-todo-banner__chip 类（折叠态）'
)
assert.match(
  cssSource,
  /\.chatroom-todo-banner__expanded/,
  'CSS 应包含 .chatroom-todo-banner__expanded 类（展开态）'
)

// ─── 6. 折叠态 max-height 32px ───────────────────────────
assert.match(
  cssSource,
  /\.chatroom-todo-banner__chip[\s\S]*?max-height:\s*32px/,
  '.chatroom-todo-banner__chip 应限制 max-height: 32px'
)

// ─── 7. 展开态 max-height 200px + overflow-y: auto ───────
assert.match(
  cssSource,
  /\.chatroom-todo-banner__expanded[\s\S]*?max-height:\s*200px/,
  '.chatroom-todo-banner__expanded 应设 max-height: 200px'
)
assert.match(
  cssSource,
  /\.chatroom-todo-banner__expanded[\s\S]*?overflow-y:\s*auto/,
  '.chatroom-todo-banner__expanded 应设 overflow-y: auto（内部滚动）'
)

// ─── 8. transition 切换动画 ──────────────────────────────
assert.match(
  cssSource,
  /\.chatroom-todo-banner__chip[\s\S]*?transition|\.chatroom-todo-banner__expanded[\s\S]*?transition/,
  'TodoBanner CSS 应包含 transition（折叠/展开切换动画）'
)

console.log('todo banner collapse contract tests passed')
