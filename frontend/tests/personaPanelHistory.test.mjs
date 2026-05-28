// Task 12 — A10 后 PersonaPanel pending 数据改为历史/归档语义
//
// Plan §P1 / R7：PersonaStore.list_proposals 存量 pending 数据保留不删，
// UI 改"历史/归档"语义，不再展示成"待审核建议"。
//
// 这是文本级断言：直接读 PersonaPanel.tsx 的源文件，验证关键文案已替换。
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = resolve(repoRoot, 'src/components/PersonaPanel.tsx')
const source = await readFile(sourcePath, 'utf8')

// 1. PROPOSAL_STATUS_LABEL.pending 不再叫"待审核"
assert.match(
  source,
  /pending:\s*'历史归档'/,
  'PROPOSAL_STATUS_LABEL.pending should be "历史归档"'
)
assert.doesNotMatch(
  source,
  /pending:\s*'待审核'/,
  'PROPOSAL_STATUS_LABEL.pending must not be "待审核" anymore'
)

// 2. console-card 标题不再是"待审核建议"，改成"历史归档"
assert.match(
  source,
  /人格补丁建议（历史归档）/,
  'panel title should reflect 历史归档 wording'
)
assert.doesNotMatch(
  source,
  /<span className="console-card__title">待审核建议<\/span>/,
  'old "待审核建议" title must be gone'
)

// 3. 顶部出现 A10 说明文字
assert.match(
  source,
  /A10.*update_persona.*调用即生效.*历史归档/s,
  'should explain A10 update_persona + history archive semantics'
)

console.log('personaPanelHistory.test.mjs OK')
