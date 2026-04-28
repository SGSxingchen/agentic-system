import { useState, useEffect } from 'react'
import * as api from '../api/client'
import './Settings.css'

interface SettingsProps {
  onClose: () => void
}

interface CustomToolConfigForm {
  id: string
  name: string
  enabled: boolean
  baseUrl: string
  apiKey: string
  apiKeySet: boolean
  extraJson: string
}

const makeCustomToolId = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`

const optionalNumber = (value: string) => {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

export function Settings({ onClose }: SettingsProps) {
  const [provider, setProvider] = useState('openai')
  const [model, setModel] = useState('gpt-3.5-turbo')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKeySet, setApiKeySet] = useState(false)
  const [temperature, setTemperature] = useState(0.7)
  const [topP, setTopP] = useState('')
  const [maxTokens, setMaxTokens] = useState(4096)
  const [stopSequences, setStopSequences] = useState('')
  const [openaiMaxCompletionTokens, setOpenaiMaxCompletionTokens] = useState('')
  const [openaiUseLegacyMaxTokens, setOpenaiUseLegacyMaxTokens] = useState(false)
  const [openaiPresencePenalty, setOpenaiPresencePenalty] = useState('')
  const [openaiFrequencyPenalty, setOpenaiFrequencyPenalty] = useState('')
  const [openaiReasoningEffort, setOpenaiReasoningEffort] = useState('')
  const [openaiSeed, setOpenaiSeed] = useState('')
  const [anthropicTopK, setAnthropicTopK] = useState('')
  const [webSearchProvider, setWebSearchProvider] = useState('duckduckgo')
  const [webSearchBaseUrl, setWebSearchBaseUrl] = useState('')
  const [webSearchApiKey, setWebSearchApiKey] = useState('')
  const [webSearchApiKeySet, setWebSearchApiKeySet] = useState(false)
  const [webSearchMaxResults, setWebSearchMaxResults] = useState(5)
  const [webSearchTimeout, setWebSearchTimeout] = useState(10)
  const [webFetchTimeout, setWebFetchTimeout] = useState(10)
  const [webFetchMaxChars, setWebFetchMaxChars] = useState(4000)
  const [workspaceRoot, setWorkspaceRoot] = useState('')
  const [shellEnabled, setShellEnabled] = useState(false)
  const [shellTimeout, setShellTimeout] = useState(30)
  const [customTools, setCustomTools] = useState<CustomToolConfigForm[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsSource, setModelsSource] = useState<'remote' | 'fallback' | 'idle'>('idle')
  const [modelsError, setModelsError] = useState<string | null>(null)

  useEffect(() => {
    const loadConfig = async () => {
      const res = await api.getConfig()
      if (res.status === 'ok' && res.data) {
        setProvider(res.data.llm.provider)
        setModel(res.data.llm.model)
        setBaseUrl(res.data.llm.base_url || '')
        setApiKeySet(res.data.llm.api_key_set)
        setTemperature(res.data.llm.temperature ?? 0.7)
        setTopP(res.data.llm.top_p != null ? String(res.data.llm.top_p) : '')
        setMaxTokens(res.data.llm.max_tokens ?? 4096)
        setStopSequences((res.data.llm.stop_sequences || []).join('\n'))
        setOpenaiMaxCompletionTokens(
          res.data.llm.openai?.max_completion_tokens != null
            ? String(res.data.llm.openai.max_completion_tokens)
            : ''
        )
        setOpenaiUseLegacyMaxTokens(Boolean(res.data.llm.openai?.use_legacy_max_tokens))
        setOpenaiPresencePenalty(
          res.data.llm.openai?.presence_penalty != null
            ? String(res.data.llm.openai.presence_penalty)
            : ''
        )
        setOpenaiFrequencyPenalty(
          res.data.llm.openai?.frequency_penalty != null
            ? String(res.data.llm.openai.frequency_penalty)
            : ''
        )
        setOpenaiReasoningEffort(res.data.llm.openai?.reasoning_effort || '')
        setOpenaiSeed(res.data.llm.openai?.seed != null ? String(res.data.llm.openai.seed) : '')
        setAnthropicTopK(
          res.data.llm.anthropic?.top_k != null
            ? String(res.data.llm.anthropic.top_k)
            : ''
        )
        if (res.data.tools) {
          setWebSearchProvider(res.data.tools.web_search.provider)
          setWebSearchBaseUrl(res.data.tools.web_search.base_url || '')
          setWebSearchApiKeySet(res.data.tools.web_search.api_key_set)
          setWebSearchMaxResults(res.data.tools.web_search.max_results)
          setWebSearchTimeout(res.data.tools.web_search.timeout)
          setWebFetchTimeout(res.data.tools.web_fetch.timeout)
          setWebFetchMaxChars(res.data.tools.web_fetch.max_chars)
          setWorkspaceRoot(res.data.tools.file.workspace_root || '')
          setShellEnabled(res.data.tools.shell.enabled)
          setShellTimeout(res.data.tools.shell.timeout)
          setCustomTools(
            Object.entries(res.data.tools.custom || {}).map(([name, config]) => ({
              id: makeCustomToolId(),
              name,
              enabled: config.enabled,
              baseUrl: config.base_url || '',
              apiKey: '',
              apiKeySet: config.api_key_set,
              extraJson: JSON.stringify(config.extra || {}, null, 2),
            }))
          )
        }
      } else {
        setError(res.message || '加载配置失败')
      }
      setLoading(false)
    }
    loadConfig()
  }, [])

  const updateCustomTool = (
    id: string,
    patch: Partial<CustomToolConfigForm>
  ) => {
    setCustomTools((items) =>
      items.map((item) => (item.id === id ? { ...item, ...patch } : item))
    )
  }

  const parseCustomTools = () => {
    const payload: Record<string, unknown> = {}
    const seen = new Set<string>()

    for (const item of customTools) {
      const name = item.name.trim()
      if (!name) continue
      if (seen.has(name)) {
        throw new Error(`自定义工具配置重复：${name}`)
      }
      seen.add(name)

      let extra: Record<string, unknown> = {}
      const rawExtra = item.extraJson.trim()
      if (rawExtra) {
        const parsed = JSON.parse(rawExtra)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error(`${name} 的 Extra JSON 必须是对象`)
        }
        extra = parsed as Record<string, unknown>
      }

      payload[name] = {
        enabled: item.enabled,
        base_url: item.baseUrl || '',
        api_key: item.apiKey || '',
        extra,
      }
    }

    return payload
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)

    let customPayload: Record<string, unknown>
    try {
      customPayload = parseCustomTools()
    } catch (err) {
      setError(err instanceof Error ? err.message : '自定义工具配置解析失败')
      setSaving(false)
      return
    }

    const res = await api.updateConfig({
      llm: {
        provider,
        model,
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
        temperature,
        top_p: optionalNumber(topP),
        max_tokens: maxTokens,
        stop_sequences: stopSequences
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean),
        openai: {
          max_completion_tokens: optionalNumber(openaiMaxCompletionTokens),
          use_legacy_max_tokens: openaiUseLegacyMaxTokens,
          presence_penalty: optionalNumber(openaiPresencePenalty),
          frequency_penalty: optionalNumber(openaiFrequencyPenalty),
          reasoning_effort: openaiReasoningEffort || '',
          seed: optionalNumber(openaiSeed),
        },
        anthropic: {
          top_k: optionalNumber(anthropicTopK),
        },
      },
      tools: {
        web_search: {
          provider: webSearchProvider,
          base_url: webSearchBaseUrl || '',
          api_key: webSearchApiKey || '',
          max_results: webSearchMaxResults,
          timeout: webSearchTimeout,
        },
        web_fetch: {
          timeout: webFetchTimeout,
          max_chars: webFetchMaxChars,
        },
        file: {
          workspace_root: workspaceRoot || '',
        },
        shell: {
          enabled: shellEnabled,
          timeout: shellTimeout,
        },
        custom: customPayload,
      },
    } as Record<string, unknown>)

    if (res.status === 'ok') {
      onClose()
    } else {
      setError(res.message || '保存失败')
    }
    setSaving(false)
  }

  // 远端拉取失败时的兜底短表（保持最常用的几个最新模型）
  const fallbackModels: Record<string, string[]> = {
    openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
    anthropic: [
      'claude-opus-4-5',
      'claude-sonnet-4-5',
      'claude-haiku-4-5',
      'claude-3-5-sonnet-20241022',
    ],
  }

  const fetchModels = async () => {
    setModelsLoading(true)
    setModelsError(null)
    const res = await api.listProviderModels({
      provider,
      base_url: baseUrl,
      api_key: apiKey || undefined, // 留空 → 后端用已保存的 key
    })
    if (res.status === 'ok' && res.data && res.data.models.length > 0) {
      setAvailableModels(res.data.models.map((m) => m.id))
      setModelsSource('remote')
    } else {
      setAvailableModels(fallbackModels[provider] || [])
      setModelsSource('fallback')
      setModelsError(res.message || null)
    }
    setModelsLoading(false)
  }

  // 初次加载完毕、或 provider/base_url 变化时自动拉一次
  // apiKey 不放入依赖：用户每敲一个字符不应触发请求
  useEffect(() => {
    if (loading) return
    fetchModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, baseUrl, loading])

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
            <section className="settings-section">
              <div className="settings-section-title">
                <h3>模型配置</h3>
                <p>控制主 Agent 和子 Agent 调用的 LLM。</p>
              </div>

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
              <label>
                模型
                <button
                  type="button"
                  className="form-inline-btn"
                  onClick={fetchModels}
                  disabled={modelsLoading}
                  style={{
                    marginLeft: 8,
                    fontSize: 12,
                    padding: '2px 8px',
                    cursor: modelsLoading ? 'wait' : 'pointer',
                  }}
                >
                  {modelsLoading ? '获取中...' : '刷新列表'}
                </button>
              </label>
              <input
                type="text"
                list="model-list"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="输入或选择模型"
              />
              <datalist id="model-list">
                {availableModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              <small className="form-hint">
                {modelsSource === 'remote' && (
                  <>已从远端拉取 {availableModels.length} 个模型；可手动输入自定义名称</>
                )}
                {modelsSource === 'fallback' && (
                  <>
                    {modelsError
                      ? `远端获取失败（${modelsError}），使用兜底列表`
                      : '使用兜底列表；配置完 API Key 后点击「刷新列表」'}
                  </>
                )}
                {modelsSource === 'idle' && <>可手动输入自定义模型名称</>}
              </small>
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

            <div className="settings-grid">
              <div className="form-group">
                <label>Temperature</label>
                <input
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={temperature}
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
                <small className="form-hint">越低越稳定，越高越发散</small>
              </div>

              <div className="form-group">
                <label>Max Tokens</label>
                <input
                  type="number"
                  min={1}
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(Number(e.target.value))}
                />
                <small className="form-hint">单次回复最大输出长度</small>
              </div>
            </div>

            <div className="settings-grid">
              <div className="form-group">
                <label>Top P（可选）</label>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={topP}
                  onChange={(e) => setTopP(e.target.value)}
                  placeholder="留空不传"
                />
                <small className="form-hint">OpenAI / Anthropic 都支持；通常不要和 Temperature 同时大幅调整</small>
              </div>

              <div className="form-group">
                <label>Stop Sequences</label>
                <textarea
                  value={stopSequences}
                  onChange={(e) => setStopSequences(e.target.value)}
                  rows={3}
                  placeholder={'每行一个停止序列'}
                />
                <small className="form-hint">OpenAI 会映射为 stop，Anthropic 会映射为 stop_sequences</small>
              </div>
            </div>

            {provider === 'openai' && (
              <div className="provider-params">
                <div className="settings-section-title settings-section-title--compact">
                  <h3>OpenAI 对话参数</h3>
                  <p>仅 provider=openai 时发送，不会传给 Anthropic。</p>
                </div>

                <div className="settings-grid">
                  <div className="form-group">
                    <label>Max Completion Tokens（可选）</label>
                    <input
                      type="number"
                      min={1}
                      value={openaiMaxCompletionTokens}
                      onChange={(e) => setOpenaiMaxCompletionTokens(e.target.value)}
                      placeholder="留空使用 Max Tokens"
                    />
                  </div>

                  <div className="form-group settings-check-row">
                    <label>
                      <input
                        type="checkbox"
                        checked={openaiUseLegacyMaxTokens}
                        onChange={(e) => setOpenaiUseLegacyMaxTokens(e.target.checked)}
                      />
                      使用 legacy max_tokens
                    </label>
                    <small className="form-hint">部分 OpenAI 兼容代理不支持 max_completion_tokens 时开启</small>
                  </div>
                </div>

                <div className="settings-grid">
                  <div className="form-group">
                    <label>Presence Penalty（可选）</label>
                    <input
                      type="number"
                      min={-2}
                      max={2}
                      step={0.1}
                      value={openaiPresencePenalty}
                      onChange={(e) => setOpenaiPresencePenalty(e.target.value)}
                      placeholder="留空不传"
                    />
                  </div>

                  <div className="form-group">
                    <label>Frequency Penalty（可选）</label>
                    <input
                      type="number"
                      min={-2}
                      max={2}
                      step={0.1}
                      value={openaiFrequencyPenalty}
                      onChange={(e) => setOpenaiFrequencyPenalty(e.target.value)}
                      placeholder="留空不传"
                    />
                  </div>
                </div>

                <div className="settings-grid">
                  <div className="form-group">
                    <label>Reasoning Effort（可选）</label>
                    <select
                      value={openaiReasoningEffort}
                      onChange={(e) => setOpenaiReasoningEffort(e.target.value)}
                    >
                      <option value="">留空不传</option>
                      <option value="minimal">minimal</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label>Seed（可选）</label>
                    <input
                      type="number"
                      value={openaiSeed}
                      onChange={(e) => setOpenaiSeed(e.target.value)}
                      placeholder="留空不传"
                    />
                  </div>
                </div>
              </div>
            )}

            {provider === 'anthropic' && (
              <div className="provider-params">
                <div className="settings-section-title settings-section-title--compact">
                  <h3>Anthropic 对话参数</h3>
                  <p>仅 provider=anthropic 时发送，不会传给 OpenAI。</p>
                </div>

                <div className="form-group">
                  <label>Top K（可选）</label>
                  <input
                    type="number"
                    min={1}
                    value={anthropicTopK}
                    onChange={(e) => setAnthropicTopK(e.target.value)}
                    placeholder="留空不传"
                  />
                  <small className="form-hint">Anthropic Messages API 专属采样参数</small>
                </div>
              </div>
            )}
            </section>

            <section className="settings-section">
              <div className="settings-section-title">
                <h3>工具配置</h3>
                <p>工具的 URL、Key 和默认运行参数；Key 只显示是否已设置。</p>
              </div>

              <div className="settings-grid">
                <div className="form-group">
                  <label>Web Search Provider</label>
                  <select
                    value={webSearchProvider}
                    onChange={(e) => setWebSearchProvider(e.target.value)}
                  >
                    <option value="duckduckgo">DuckDuckGo（无需 Key）</option>
                    <option value="brave">Brave Search API</option>
                    <option value="serper">Serper Google Search API</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Web Search API Key</label>
                  <input
                    type="password"
                    value={webSearchApiKey}
                    onChange={(e) => setWebSearchApiKey(e.target.value)}
                    placeholder={webSearchApiKeySet ? '已设置 (留空保持不变)' : '无需 Key 可留空'}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Web Search Base URL（可选）</label>
                <input
                  type="text"
                  value={webSearchBaseUrl}
                  onChange={(e) => setWebSearchBaseUrl(e.target.value)}
                  placeholder="留空使用 provider 默认地址"
                />
                <small className="form-hint">
                  DuckDuckGo 默认 https://duckduckgo.com/html/；Brave/Serper 可填代理地址
                </small>
              </div>

              <div className="settings-grid">
                <div className="form-group">
                  <label>搜索结果数</label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={webSearchMaxResults}
                    onChange={(e) => setWebSearchMaxResults(Number(e.target.value))}
                  />
                </div>

                <div className="form-group">
                  <label>搜索超时（秒）</label>
                  <input
                    type="number"
                    min={1}
                    value={webSearchTimeout}
                    onChange={(e) => setWebSearchTimeout(Number(e.target.value))}
                  />
                </div>
              </div>

              <div className="settings-grid">
                <div className="form-group">
                  <label>网页读取超时（秒）</label>
                  <input
                    type="number"
                    min={1}
                    value={webFetchTimeout}
                    onChange={(e) => setWebFetchTimeout(Number(e.target.value))}
                  />
                </div>

                <div className="form-group">
                  <label>网页读取最大字符数</label>
                  <input
                    type="number"
                    min={200}
                    max={20000}
                    value={webFetchMaxChars}
                    onChange={(e) => setWebFetchMaxChars(Number(e.target.value))}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>文件工具工作区根目录（可选）</label>
                <input
                  type="text"
                  value={workspaceRoot}
                  onChange={(e) => setWorkspaceRoot(e.target.value)}
                  placeholder="留空使用项目根目录"
                />
                <small className="form-hint">read_file/write_file/file_search 只能访问该目录内文件</small>
              </div>

              <div className="settings-grid">
                <div className="form-group settings-check-row">
                  <label>
                    <input
                      type="checkbox"
                      checked={shellEnabled}
                      onChange={(e) => setShellEnabled(e.target.checked)}
                    />
                    启用 Bash 工具
                  </label>
                  <small className="form-hint">高风险工具，默认关闭</small>
                </div>

                <div className="form-group">
                  <label>Shell 超时（秒）</label>
                  <input
                    type="number"
                    min={1}
                    value={shellTimeout}
                    onChange={(e) => setShellTimeout(Number(e.target.value))}
                  />
                </div>
              </div>

              <div className="custom-tool-configs">
                <div className="custom-tool-configs-header">
                  <div>
                    <h4>自定义工具凭据</h4>
                    <p>给未来新增工具预留 URL、Key 和扩展参数；Key 留空会保持旧值。</p>
                  </div>
                  <button
                    type="button"
                    className="btn-secondary btn-compact"
                    onClick={() =>
                      setCustomTools((items) => [
                        ...items,
                        {
                          id: makeCustomToolId(),
                          name: '',
                          enabled: true,
                          baseUrl: '',
                          apiKey: '',
                          apiKeySet: false,
                          extraJson: '{}',
                        },
                      ])
                    }
                  >
                    添加工具配置
                  </button>
                </div>

                {customTools.length === 0 ? (
                  <div className="custom-tool-empty">暂无自定义工具凭据。</div>
                ) : (
                  customTools.map((tool) => (
                    <div className="custom-tool-card" key={tool.id}>
                      <div className="custom-tool-card-header">
                        <div className="form-group">
                          <label>工具名称</label>
                          <input
                            type="text"
                            value={tool.name}
                            onChange={(e) =>
                              updateCustomTool(tool.id, { name: e.target.value })
                            }
                            placeholder="例如 notion_search"
                          />
                        </div>

                        <button
                          type="button"
                          className="btn-secondary btn-compact"
                          onClick={() =>
                            setCustomTools((items) =>
                              items.filter((item) => item.id !== tool.id)
                            )
                          }
                        >
                          移除
                        </button>
                      </div>

                      <div className="settings-grid">
                        <div className="form-group">
                          <label>Base URL</label>
                          <input
                            type="text"
                            value={tool.baseUrl}
                            onChange={(e) =>
                              updateCustomTool(tool.id, { baseUrl: e.target.value })
                            }
                            placeholder="工具服务地址，可选"
                          />
                        </div>

                        <div className="form-group">
                          <label>API Key</label>
                          <input
                            type="password"
                            value={tool.apiKey}
                            onChange={(e) =>
                              updateCustomTool(tool.id, { apiKey: e.target.value })
                            }
                            placeholder={tool.apiKeySet ? '已设置 (留空保持不变)' : '可选'}
                          />
                        </div>
                      </div>

                      <div className="settings-grid">
                        <div className="form-group settings-check-row">
                          <label>
                            <input
                              type="checkbox"
                              checked={tool.enabled}
                              onChange={(e) =>
                                updateCustomTool(tool.id, { enabled: e.target.checked })
                              }
                            />
                            启用该工具配置
                          </label>
                        </div>

                        <div className="form-group">
                          <label>Extra JSON</label>
                          <textarea
                            value={tool.extraJson}
                            onChange={(e) =>
                              updateCustomTool(tool.id, { extraJson: e.target.value })
                            }
                            rows={4}
                            spellCheck={false}
                            placeholder='{"region":"us"}'
                          />
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </section>

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
