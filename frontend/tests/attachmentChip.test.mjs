// Plan 3 P3 Task 27 — 消息卡片附件展示静态契约。
//
// 校验 ChatPanel.tsx / ChatroomPanel.tsx 在消息渲染时引用了
// AttachmentChip（或等价的 message.attachments 渲染逻辑），并指向
// /api/attachments/<id>/content 作为图片缩略图来源。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chipPath = resolve(repoRoot, 'src/components/AttachmentChip.tsx')
const chatPanelPath = resolve(repoRoot, 'src/components/ChatPanel.tsx')
const chatroomPanelPath = resolve(repoRoot, 'src/components/ChatroomPanel.tsx')

const chipSource = await readFile(chipPath, 'utf8')
const chatPanelSource = await readFile(chatPanelPath, 'utf8')
const chatroomPanelSource = await readFile(chatroomPanelPath, 'utf8')

// ─── AttachmentChip 组件本体 ──────────────────────────────────────
assert.match(
  chipSource,
  /export\s+function\s+AttachmentChip/,
  'AttachmentChip.tsx 应导出 AttachmentChip 函数组件'
)
assert.match(
  chipSource,
  /attachmentContentUrl/,
  'AttachmentChip 应使用 api.attachmentContentUrl 拼接 /api/attachments/<id>/content'
)
assert.match(
  chipSource,
  /getAttachmentMetadata/,
  'AttachmentChip 应使用 getAttachmentMetadata 获取文件名 / mime'
)
assert.match(
  chipSource,
  /image\//,
  'AttachmentChip 应区分 image/* 与其他 mime 的渲染'
)

// ─── ChatPanel.tsx ────────────────────────────────────────────────
assert.match(
  chatPanelSource,
  /AttachmentChip/,
  'ChatPanel.tsx 消息卡片应渲染 AttachmentChip'
)
assert.match(
  chatPanelSource,
  /message\.attachments/,
  'ChatPanel.tsx 消息卡片应读取 message.attachments'
)

// ─── ChatroomPanel.tsx ────────────────────────────────────────────
assert.match(
  chatroomPanelSource,
  /AttachmentChip/,
  'ChatroomPanel.tsx 消息卡片应渲染 AttachmentChip'
)
assert.match(
  chatroomPanelSource,
  /message\.attachments/,
  'ChatroomPanel.tsx 消息卡片应读取 message.attachments'
)

console.log('attachment chip contract tests passed')
