import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const outDir = mkdtempSync(join(tmpdir(), 'workspace-contract-'))
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
    'src/utils/workspaceContract.ts',
  ], { cwd: root, stdio: 'inherit' })

  const contract = await import(`file://${join(outDir, 'utils', 'workspaceContract.js')}`)

  assert.deepEqual(contract.normalizeWorkspaceFileEntry({
    path: 'drafts/chapter-1.md',
    name: '',
    kind: 'file',
    size: 128,
    modified_at: '2026-05-22T09:00:00Z',
  }), {
    path: 'drafts/chapter-1.md',
    name: 'chapter-1.md',
    type: 'file',
    size: 128,
    updated_at: '2026-05-22T09:00:00Z',
  })

  assert.equal(contract.normalizeWorkspaceFileEntry({
    path: 'drafts',
    name: 'drafts',
    type: 'file',
    kind: 'directory',
  }).type, 'directory')

  assert.deepEqual(contract.normalizeWorkspaceFileContent({
    workspace_id: 'ws_1',
    path: 'drafts/chapter-1.md',
    size: 256,
    editable: true,
    encoding: 'utf-8',
    content: '正文',
  }).editable, true)

  const binary = contract.normalizeWorkspaceFileContent({
    workspace_id: 'ws_1',
    path: 'image.png',
    size: 1024,
    editable: true,
    encoding: 'binary',
    content: '',
    binary: true,
  })
  assert.equal(binary.is_text, false)
  assert.equal(binary.editable, false)

  console.log('workspace contract tests passed')
} finally {
  rmSync(outDir, { recursive: true, force: true })
}
