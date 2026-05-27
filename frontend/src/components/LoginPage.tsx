import { useEffect, useState, type FormEvent } from 'react'
import { setAuthToken } from '../api/client'
import './LoginPage.css'

interface LoginPageProps {
  onLogin: () => void
}

/**
 * A11 — 全局密码门禁登录页。
 *
 * 流程：
 * 1. 用户输入密码 → 提交时直接调用 GET /api/health（豁免鉴权但能回填 200）+ Authorization: Bearer <pwd>
 *    若密码错误，会被 AuthMiddleware 提前拦回 401（health 在豁免名单里所以一定回 200，
 *    所以我们额外探测 /api/agents 验证 token 是否有效）
 * 2. 探测通过 → setAuthToken + onLogin() → App 切到主面板
 * 3. 探测失败 → 显示错误，不写入 token
 *
 * 注意：探测时还没 setAuthToken，必须手动拼 Authorization header 调用 fetch。
 */
export function LoginPage({ onLogin }: LoginPageProps) {
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    document.title = '登录 — Multi-Agent Code System'
  }, [])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (submitting) return
    if (!password) {
      setError('请输入访问密码')
      return
    }

    setError(null)
    setSubmitting(true)
    try {
      // 探测一个**不在豁免名单**的端点，验证 token 是否被后端接受。
      // /api/agents 是稳定的轻量列表接口。
      const res = await fetch('/api/agents', {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${password}`,
        },
      })

      if (res.status === 401) {
        const body = await res.json().catch(() => ({}))
        const code = (body as { error?: string }).error
        if (code === 'auth_invalid') {
          setError('密码错误')
        } else {
          setError('鉴权失败，请稍后再试')
        }
        return
      }

      if (res.status === 429) {
        setError('失败次数过多，请等待一段时间后再试')
        return
      }

      if (!res.ok) {
        setError(`服务器返回 HTTP ${res.status}`)
        return
      }

      // 密码通过，持久化 token 并跳主面板
      setAuthToken(password)
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : '网络请求失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <header className="login-header">
          <h1>Multi-Agent Code System</h1>
          <p className="login-subtitle">访问受密码保护，请输入访问密码继续</p>
        </header>

        <label className="login-field">
          <span>访问密码</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            autoComplete="current-password"
            disabled={submitting}
          />
        </label>

        {error && <div className="login-error">{error}</div>}

        <button
          type="submit"
          className="login-submit"
          disabled={submitting || !password}
        >
          {submitting ? '验证中…' : '进入系统'}
        </button>

        <p className="login-hint">
          密码由部署方配置。若忘记密码，请联系系统管理员或修改 <code>config/system.yaml</code> 中的{' '}
          <code>server.access_password</code>。
        </p>
      </form>
    </div>
  )
}
