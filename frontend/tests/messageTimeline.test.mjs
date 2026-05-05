import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const outDir = mkdtempSync(join(tmpdir(), 'message-timeline-'))
const localTsc = join(root, 'node_modules', 'typescript', 'bin', 'tsc')

try {
  const tscCommand = existsSync(localTsc) ? process.execPath : 'tsc'
  const tscArgs = existsSync(localTsc) ? [localTsc] : []
  execFileSync(tscCommand, [
    ...tscArgs,
    '--target', 'ES2020',
    '--module', 'ES2020',
    '--moduleResolution', 'node',
    '--outDir', outDir,
    'src/utils/messageTimeline.ts',
  ], { cwd: root, stdio: 'inherit' })

  const timeline = await import(`file://${join(outDir, 'utils', 'messageTimeline.js')}`)

  let items = []
  items = timeline.appendTextTimelineItem(items, '先说明。', 1)
  items = timeline.upsertToolCallTimelineItem(items, {
    id: 'call-read',
    tool: 'read_file',
    status: 'running',
    args: { path: 'README.md' },
  }, 2)
  items = timeline.appendTextTimelineItem(items, '读取后继续解释。', 3)
  items = timeline.updateToolResultTimelineItem(items, 'call-read', {
    status: 'success',
    result: { ok: true },
  }, 4)

  assert.deepEqual(items.map((item) => item.kind), ['text', 'tool_call', 'text'])
  assert.equal(items[0].content, '先说明。')
  assert.equal(items[1].toolCall.tool, 'read_file')
  assert.deepEqual(items[1].toolCall.result, { ok: true })
  assert.equal(items[2].content, '读取后继续解释。')

  const sorted = timeline.getMessageTimeline({
    id: 'assistant-1',
    type: 'assistant',
    content: 'unused when timeline exists',
    timestamp: '2026-05-03T00:00:00.000Z',
    timeline: [
      { id: 'late', kind: 'text', order: 20, content: '后到文本' },
      { id: 'early', kind: 'tool_call', order: 10, toolCall: { id: 'bash-1', tool: 'bash', status: 'success' } },
    ],
  })

  assert.deepEqual(sorted.map((item) => item.id), ['early', 'late'])
  console.log('messageTimeline ordered render tests passed')
} finally {
  rmSync(outDir, { recursive: true, force: true })
}
