import assert from 'node:assert/strict'
import { readFile, stat } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const clientPath = resolve(repoRoot, 'src/api/client.ts')
const wsHookPath = resolve(repoRoot, 'src/hooks/useWebSocket.ts')
const appTsxPath = resolve(repoRoot, 'src/App.tsx')
const loginPath = resolve(repoRoot, 'src/components/LoginPage.tsx')

const clientSource = await readFile(clientPath, 'utf8')
const wsSource = await readFile(wsHookPath, 'utf8')
const appSource = await readFile(appTsxPath, 'utf8')

// LoginPage.tsx 必须存在
const loginExists = await stat(loginPath).then(() => true).catch(() => false)
assert.equal(loginExists, true, 'frontend/src/components/LoginPage.tsx 必须存在')
const loginSource = await readFile(loginPath, 'utf8')

// 1) client.ts 应导出 token 工具函数 + Authorization 注入 + 401 跳登录
assert.match(
  clientSource,
  /export\s+function\s+getAuthToken\s*\(/,
  'client.ts 应导出 getAuthToken()'
)
assert.match(
  clientSource,
  /export\s+function\s+setAuthToken\s*\(/,
  'client.ts 应导出 setAuthToken()'
)
assert.match(
  clientSource,
  /export\s+function\s+clearAuthToken\s*\(/,
  'client.ts 应导出 clearAuthToken()'
)
assert.match(
  clientSource,
  /Authorization[^]*Bearer\s*\$\{[^}]*\}/,
  'fetchAPI 应在 Authorization header 注入 Bearer ${token}'
)
// 401 时应清掉 token + 派分发 (不一定 reload，但至少要清 token + 通知)
assert.match(
  clientSource,
  /res\.status\s*===\s*401/,
  'fetchAPI 应识别 401 响应'
)
assert.match(
  clientSource,
  /clearAuthToken\(\)/,
  'fetchAPI 在 401 时应调用 clearAuthToken() 清掉 token'
)

// 2) useWebSocket 必须保持 url 参数透传（拼 token 的活儿在调用方做，hook 不动）
assert.match(
  wsSource,
  /new WebSocket\(url\)/,
  'useWebSocket 应直接用传入 url（让调用方拼 ?token=）'
)

// 3) App.tsx 应在拼 wsUrl 时附带 token query
assert.match(
  appSource,
  /getAuthToken\s*\(\s*\)/,
  'App.tsx 应读 getAuthToken() 拼 ws 协议'
)
assert.match(
  appSource,
  /token=\$\{[^}]*encodeURIComponent[^}]*\}/,
  'App.tsx 应在 wsUrl 上加 ?token=${encodeURIComponent(token)}'
)

// 4) App.tsx 应在 token 缺失时挂 LoginPage
assert.match(
  appSource,
  /LoginPage/,
  'App.tsx 应引用 LoginPage'
)

// 5) LoginPage 应：表单 + 调健康检查验证 + 持久化 token
assert.match(
  loginSource,
  /\/api\/health/,
  'LoginPage 应通过 /api/health 探测 token 是否生效'
)
assert.match(
  loginSource,
  /Authorization[^]*Bearer/,
  'LoginPage 探测请求需手动带 Bearer token（探测时还没 setAuthToken）'
)
assert.match(
  loginSource,
  /setAuthToken/,
  'LoginPage 验证通过后应 setAuthToken()'
)

console.log('A11 auth wiring contract tests passed')
