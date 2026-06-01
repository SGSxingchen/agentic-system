// A27.B — ChatroomPanel 渲染消息时按 created_at 排序静态契约。
//
// 校验 ChatroomPanel.tsx：
// 1. 渲染 activeRoom.messages 时使用 useMemo 排序（不直接 .map）
// 2. 排序键是 created_at，比较使用 new Date(...).getTime()
// 3. 用排序后的 sortedMessages 变量传给 .map

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const panelPath = resolve(repoRoot, 'src/components/ChatroomPanel.tsx')
const panelSource = await readFile(panelPath, 'utf8')

// ─── 1. 必须出现 sortedMessages（排序后变量名） ───────────
assert.match(
  panelSource,
  /sortedMessages/,
  'ChatroomPanel.tsx 应定义 sortedMessages 变量（排序后的消息列表）'
)

// ─── 2. 用 useMemo 缓存排序结果 ───────────────────────────
assert.match(
  panelSource,
  /sortedMessages\s*=\s*useMemo\s*\(/,
  'sortedMessages 应通过 useMemo 缓存（避免每次渲染重排）'
)

// ─── 3. 排序逻辑必须用 created_at + getTime ───────────────
assert.match(
  panelSource,
  /new\s+Date\s*\(\s*[ab]\.created_at\s*\)\.getTime\s*\(\s*\)\s*-\s*new\s+Date\s*\(\s*[ab]\.created_at\s*\)\.getTime\s*\(\s*\)/,
  '排序比较器应为 new Date(a.created_at).getTime() - new Date(b.created_at).getTime()'
)

// ─── 4. 渲染处用 sortedMessages.map 而不是直接 messages.map ─
// activeRoom.messages.length === 0 这个空态判断保留是允许的，
// 但 .map 渲染必须走 sortedMessages。
assert.match(
  panelSource,
  /sortedMessages\.map\s*\(/,
  '消息渲染应使用 sortedMessages.map（不能直接用 activeRoom.messages.map）'
)

// ─── 5. useMemo 依赖项含 messages（确保新消息进来重排） ────
assert.match(
  panelSource,
  /sortedMessages[\s\S]{0,400}useMemo[\s\S]{0,400}\[[\s\S]{0,200}messages[\s\S]{0,200}\]/,
  'sortedMessages 的 useMemo 依赖项应包含 messages（新消息变化时重排）'
)

console.log('chatroom message order contract tests passed')
