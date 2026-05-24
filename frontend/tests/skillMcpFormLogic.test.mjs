import assert from 'node:assert/strict'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourcePath = resolve(repoRoot, 'src/components/skillMcpFormLogic.ts')
const outPath = resolve(tmpdir(), `skillMcpFormLogic-${process.pid}.mjs`)
const source = await readFile(sourcePath, 'utf8')
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
    verbatimModuleSyntax: true,
  },
  fileName: sourcePath,
})

await mkdir(dirname(outPath), { recursive: true })
await writeFile(outPath, transpiled.outputText, 'utf8')

try {
  const {
    buildSkillConfig,
    skillItemDraftToConfig,
    skillItemToDraft,
    skillConfigToDraft,
    mcpDraftToServer,
    mcpServerToDraft,
  } = await import(pathToFileURL(outPath).href + `?cache=${Date.now()}`)

  const skillDraft = skillConfigToDraft({
    enabled: true,
    directories: ['./skills', '../shared'],
    items: [{ name: 'repo_style', description: '项目约定' }],
    disabled: ['legacy_skill'],
    strategy: 'metadata_and_instructions',
  })

  assert.equal(skillDraft.enabled, true)
  assert.equal(skillDraft.directoriesText, './skills\n../shared')
  assert.deepEqual(buildSkillConfig(skillDraft), {
    enabled: true,
    directories: ['./skills', '../shared'],
    items: [{ name: 'repo_style', description: '项目约定' }],
    disabled: ['legacy_skill'],
    strategy: 'metadata_and_instructions',
  })

  assert.equal(
    buildSkillConfig({
      enabled: false,
      directoriesText: '',
      itemsText: '[]',
      disabledText: '',
      strategy: '',
    }),
    null
  )

  assert.deepEqual(
    skillItemToDraft({
      name: 'repo_style',
      description: '项目约定',
      instructions: '保持最小补丁',
      enabled: false,
    }),
    {
      kind: 'inline',
      name: 'repo_style',
      description: '项目约定',
      instructions: '保持最小补丁',
      path: '',
      original: {
        name: 'repo_style',
        description: '项目约定',
        instructions: '保持最小补丁',
        enabled: false,
      },
    }
  )

  assert.deepEqual(
    skillItemDraftToConfig({
      kind: 'inline',
      name: 'repo_style',
      description: '项目约定',
      instructions: '保持最小补丁',
      path: '',
      original: {
        name: 'repo_style',
        description: '旧说明',
        instructions: '旧指令',
        enabled: false,
      },
    }),
    {
      name: 'repo_style',
      description: '项目约定',
      instructions: '保持最小补丁',
      enabled: false,
    }
  )

  assert.deepEqual(
    skillItemDraftToConfig({
      kind: 'path',
      name: '',
      description: '',
      instructions: '',
      path: './skills/python/SKILL.md',
      original: {
        path: './skills/old/SKILL.md',
        enabled: false,
        source: 'team',
      },
    }),
    { path: './skills/python/SKILL.md', enabled: false, source: 'team' }
  )

  assert.equal(
    skillItemToDraft({ path: '', enabled: true }).kind,
    'path',
    '空路径草稿仍应保持路径 Skill 类型，便于新增后填写'
  )

  const mcpDraft = mcpServerToDraft({
    name: 'filesystem',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-filesystem', '.'],
    env: { TOKEN: '${MCP_TOKEN}' },
    cwd: '.',
    enabled: true,
    description: '项目文件 MCP server',
    transport: 'stdio',
  })

  assert.equal(mcpDraft.argsText, '-y\n@modelcontextprotocol/server-filesystem\n.')
  assert.deepEqual(mcpDraftToServer(mcpDraft), {
    name: 'filesystem',
    command: 'npx',
    args: ['-y', '@modelcontextprotocol/server-filesystem', '.'],
    env: { TOKEN: '${MCP_TOKEN}' },
    cwd: '.',
    enabled: true,
    description: '项目文件 MCP server',
    transport: 'stdio',
  })

  assert.throws(
    () => mcpDraftToServer({ ...mcpDraft, envText: '[]' }),
    /环境变量 JSON/
  )
} finally {
  await rm(outPath, { force: true })
}
