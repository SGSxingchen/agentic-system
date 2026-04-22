import { useState, useEffect } from 'react'
import * as api from '../api/client'
import './Settings.css'

interface SettingsProps {
  onClose: () => void
}

export function Settings({ onClose }: SettingsProps) {
  const [provider, setProvider] = useState('openai')
  const [model, setModel] = useState('gpt-3.5-turbo')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKeySet, setApiKeySet] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const loadConfig = async () => {
      const res = await api.getConfig()
      if (res.status === 'ok' && res.data) {
        setProvider(res.data.llm.provider)
        setModel(res.data.llm.model)
        setBaseUrl(res.data.llm.base_url || '')
        setApiKeySet(res.data.llm.api_key_set)
      } else {
        setError(res.message || '加载配置失败')
      }
      setLoading(false)
    }
    loadConfig()
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    const res = await api.updateConfig({
      llm: {
        provider,
        model,
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
      } as Record<string, unknown>,
    } as Record<string, unknown>)

    if (res.status === 'ok') {
      onClose()
    } else {
      setError(res.message || '保存失败')
    }
    setSaving(false)
  }

  const models: Record<string, string[]> = {
    openai: ['gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo'],
    anthropic: [
      'claude-3-5-sonnet-20241022',
      'claude-3-opus-20240229',
      'claude-3-haiku-20240307',
    ],
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>设置</h2>
          <button className="settings-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        {error && <div className="settings-error">{error}</div>}

        {loading ? (
          <div className="settings-loading">加载配置中...</div>
        ) : (
          <>
            <div className="form-group">
              <label>LLM 提供商</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic (Claude)</option>
              </select>
            </div>

            <div className="form-group">
              <label>模型</label>
              <input
                type="text"
                list="model-list"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="输入或选择模型"
              />
              <datalist id="model-list">
                {(models[provider] || []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              <small className="form-hint">可手动输入自定义模型名称</small>
            </div>

            <div className="form-group">
              <label>API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={apiKeySet ? '已设置 (留空保持不变)' : '请输入 API Key'}
              />
            </div>

            <div className="form-group">
              <label>Base URL（可选）</label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="留空使用默认地址"
              />
              <small className="form-hint">用于代理或自部署服务</small>
            </div>

            <div className="button-group">
              <button
                className="btn-primary"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? '保存中...' : '保存'}
              </button>
              <button className="btn-secondary" onClick={onClose}>
                取消
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
