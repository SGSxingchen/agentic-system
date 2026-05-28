// Plan 3 P3 Task 23 — 前端附件上传 UI 静态契约。
//
// 这是一个静态契约测试：不跑 React，仅按 plan 要求的关键代码片段在源码中存在性
// 校验。覆盖：
//   - api/client.ts 暴露 uploadAttachment / postChatroomMessage 携带 attachments
//     / addChatSessionMessage 携带 attachments
//   - api/client.ts 引入 Attachment 类型
//   - types/index.ts 暴露 Attachment 接口（id/filename/mime_type/...）以及
//     ChatMessage / ChatroomMessage 增加可选 attachments 字段
//   - ChatPanel.tsx / ChatroomPanel.tsx 接入 paste / drop / file 三种上传入口
//     并把上传结果带进 send 请求
//
// 频道：保持与 apiClientContract.test.mjs 同风格（regex 静态匹配）。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const clientPath = resolve(repoRoot, 'src/api/client.ts')
const typesPath = resolve(repoRoot, 'src/types/index.ts')
const chatPanelPath = resolve(repoRoot, 'src/components/ChatPanel.tsx')
const chatroomPanelPath = resolve(repoRoot, 'src/components/ChatroomPanel.tsx')

const clientSource = await readFile(clientPath, 'utf8')
const typesSource = await readFile(typesPath, 'utf8')
const chatPanelSource = await readFile(chatPanelPath, 'utf8')
const chatroomPanelSource = await readFile(chatroomPanelPath, 'utf8')

// ─── types/index.ts ───────────────────────────────────────────────
assert.match(
  typesSource,
  /export interface Attachment[\s\S]*id: string[\s\S]*filename: string[\s\S]*mime_type: string[\s\S]*size_bytes: number/,
  'types/index.ts 应导出 Attachment 接口（id/filename/mime_type/size_bytes）'
)
assert.match(
  typesSource,
  /interface ChatMessage[\s\S]*attachments\?: string\[\]/,
  'ChatMessage 应支持可选 attachments: string[]'
)
assert.match(
  typesSource,
  /interface ChatroomMessage[\s\S]*attachments\?: string\[\]/,
  'ChatroomMessage 应支持可选 attachments: string[]'
)

// ─── api/client.ts ────────────────────────────────────────────────
assert.match(
  clientSource,
  /export async function uploadAttachment\(/,
  'client.ts 应暴露 uploadAttachment(file, scope, ...)'
)
assert.match(
  clientSource,
  /\/api\/attachments\?scope=/,
  'uploadAttachment 应 POST /api/attachments?scope=...'
)
assert.match(
  clientSource,
  /addChatSessionMessage[\s\S]*attachments\?: string\[\]/,
  'addChatSessionMessage 应支持 attachments?: string[]'
)
assert.match(
  clientSource,
  /postChatroomMessage[\s\S]*attachments\?: string\[\]/,
  'postChatroomMessage 应支持 attachments?: string[]'
)

// ─── ChatPanel.tsx / ChatroomPanel.tsx ────────────────────────────
for (const [label, src] of [
  ['ChatPanel.tsx', chatPanelSource],
  ['ChatroomPanel.tsx', chatroomPanelSource],
]) {
  assert.match(
    src,
    /uploadAttachment/,
    `${label} 应调用 uploadAttachment 上传附件`
  )
  assert.match(
    src,
    /onPaste/,
    `${label} 应监听 paste 事件以支持复制粘贴`
  )
  assert.match(
    src,
    /onDrop/,
    `${label} 应监听 drop 事件以支持拖拽上传`
  )
  assert.match(
    src,
    /type="file"/,
    `${label} 应包含隐藏的 input[type=file] 选择器`
  )
  assert.match(
    src,
    /pendingAttachments|pending_attachments|attachmentDrafts/,
    `${label} 应维护"待发送附件"列表 state`
  )
}

console.log('attachment input contract tests passed')
