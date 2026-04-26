import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../api/client'
import type { EvolutionGraph, EvolutionNode, ToolPromptInfo } from '../types'
import './EvolutionPanel.css'

type DynamicMode = 'template' | 'checklist' | 'regex_extract'

const DEFAULT_AGENT_PROMPT = `你是一个可被主 Agent 调用的专业子 Agent。

职责：
1. 只处理自己擅长的明确任务。
2. 如果需要外部能力，优先调用可用工具。
3. 输出要结构化、简洁、可被其他 Agent 继续使用。`

function splitTerms(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function parsePatterns(value: string): Record<string, string> {
  const patterns: Record<string, string> = {}
  for (const line of value.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const eqIndex = trimmed.indexOf('=')
    const colonIndex = trimmed.indexOf(':')
    const splitIndex = eqIndex >= 0 ? eqIndex : colonIndex
    if (splitIndex <= 0) continue
    const key = trimmed.slice(0, splitIndex).trim()
    const pattern = trimmed.slice(splitIndex + 1).trim()
    if (key && pattern) patterns[key] = pattern
  }
  return patterns
}

function nodeTypeLabel(node: EvolutionNode): string {
  if (node.type === 'agent') return 'Agent'
  if (node.type === 'dynamic_tool') return `动态 Tool${node.mode ? ` / ${node.mode}` : ''}`
  return 'Tool'
}

export function EvolutionPanel() {
  const [graph, setGraph] = useState<EvolutionGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [savingTool, setSavingTool] = useState(false)
  const [savingAgent, setSavingAgent] = useState(false)
  const [toolPrompts, setToolPrompts] = useState<ToolPromptInfo[]>([])
  const [selectedPromptName, setSelectedPromptName] = useState('')
  const [promptDraft, setPromptDraft] = useState('')
  const [savingPrompt, setSavingPrompt] = useState(false)

  const [toolName, setToolName] = useState('')
  const [toolDescription, setToolDescription] = useState('')
  const [toolMode, setToolMode] = useState<DynamicMode>('checklist')
  const [templateText, setTemplateText] = useState('需求要点：{{text}}')
  const [requiredTerms, setRequiredTerms] = useState('目标，输入，输出，验收')
  const [forbiddenTerms, setForbiddenTerms] = useState('随便，都行，看着办')
  const [patternsText, setPatternsText] = useState('email=[\\w.-]+@[\\w.-]+')
  const [attachToAssistant, setAttachToAssistant] = useState(true)

  const [agentName, setAgentName] = useState('')
  const [agentDescription, setAgentDescription] = useState('')
  const [agentPrompt, setAgentPrompt] = useState(DEFAULT_AGENT_PROMPT)
  const [agentTools, setAgentTools] = useState<string[]>([])

  const fetchToolPrompts = useCallback(async () => {
    const res = await api.getToolPrompts()
    if (res.status === 'ok' && res.data) {
      setToolPrompts(res.data)
      setSelectedPromptName((current) => current || res.data?.[0]?.name || '')
      if (!selectedPromptName && res.data[0]) {
        setPromptDraft(res.data[0].prompt)
      }
    } else {
      setError(res.message || '无法加载 Tool 提示词')
    }
  }, [selectedPromptName])

  const fetchGraph = useCallback(async () => {
    setLoading(true)
    const res = await api.getEvolutionGraph()
    if (res.status === 'ok' && res.data) {
      setGraph(res.data)
      setError('')
    } else {
      setError(res.message || '无法加载能力网络')
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchGraph()
    fetchToolPrompts()
  }, [fetchGraph, fetchToolPrompts])

  const agents = useMemo(
    () => graph?.nodes.filter((node) => node.type === 'agent') || [],
    [graph]
  )

  const tools = useMemo(
    () => graph?.nodes.filter((node) => node.type !== 'agent') || [],
    [graph]
  )

  const assistantEdges = useMemo(
    () => graph?.edges.filter((edge) => edge.source === 'assistant') || [],
    [graph]
  )

  const availableToolOptions = useMemo(
    () => graph?.nodes.filter((node) => node.id !== agentName) || [],
    [agentName, graph]
  )

  const selectedPrompt = useMemo(
    () => toolPrompts.find((item) => item.name === selectedPromptName) || null,
    [selectedPromptName, toolPrompts]
  )

  const handleSelectPrompt = (name: string) => {
    const selected = toolPrompts.find((item) => item.name === name)
    setSelectedPromptName(name)
    setPromptDraft(selected?.prompt || '')
  }

  const toggleAgentTool = (toolId: string) => {
    setAgentTools((prev) =>
      prev.includes(toolId)
        ? prev.filter((item) => item !== toolId)
        : [...prev, toolId]
    )
  }

  const handleCreateTool = async () => {
    if (!toolName.trim()) {
      setError('动态工具名称不能为空')
      return
    }

    let config: Record<string, unknown>
    if (toolMode === 'template') {
      config = { template: templateText }
    } else if (toolMode === 'checklist') {
      config = {
        required_terms: splitTerms(requiredTerms),
        forbidden_terms: splitTerms(forbiddenTerms),
        case_sensitive: false,
      }
    } else {
      config = { patterns: parsePatterns(patternsText) }
    }

    setSavingTool(true)
    const res = await api.createDynamicTool({
      name: toolName.trim(),
      description: toolDescription || `${toolName.trim()} 动态工具`,
      mode: toolMode,
      config,
      attach_to_agents: attachToAssistant ? ['assistant'] : [],
      overwrite: false,
    })
    setSavingTool(false)

    if (res.status === 'ok') {
      setToolName('')
      setToolDescription('')
      await fetchGraph()
      await fetchToolPrompts()
    } else {
      setError(res.message || '创建动态工具失败')
    }
  }

  const handleCreateAgent = async () => {
    if (!agentName.trim()) {
      setError('子 Agent 名称不能为空')
      return
    }

    setSavingAgent(true)
    const res = await api.createAgent({
      name: agentName.trim(),
      description: agentDescription || `${agentName.trim()} 子 Agent`,
      system_prompt: agentPrompt || DEFAULT_AGENT_PROMPT,
      tools: agentTools,
      output_format: 'text',
      max_iterations: 12,
    })
    setSavingAgent(false)

    if (res.status === 'ok') {
      setAgentName('')
      setAgentDescription('')
      setAgentPrompt(DEFAULT_AGENT_PROMPT)
      setAgentTools([])
      await fetchGraph()
      await fetchToolPrompts()
    } else {
      setError(res.message || '创建子 Agent 失败')
    }
  }

  const handleSavePrompt = async () => {
    if (!selectedPrompt || !promptDraft.trim()) {
      setError('请选择 Tool，并填写提示词')
      return
    }

    setSavingPrompt(true)
    const res = await api.updateToolPrompt(selectedPrompt.name, promptDraft.trim())
    setSavingPrompt(false)

    if (res.status === 'ok') {
      await fetchToolPrompts()
      await fetchGraph()
    } else {
      setError(res.message || '保存 Tool 提示词失败')
    }
  }

  const handleReload = async () => {
    const res = await api.reloadEvolutionExtensions()
    if (res.status === 'ok') {
      await fetchGraph()
      await fetchToolPrompts()
    } else {
      setError(res.message || '重新装载失败')
    }
  }

  return (
    <div className="evolution-panel">
      <div className="evolution-hero">
        <div>
          <p className="evolution-kicker">Agent Evolution Runtime</p>
          <h2>进化中心</h2>
          <p>
            主 Agent 不固定写死能力，而是把子 Agent 和 Tool 都当作可装载能力。
            新工具可以运行时创建并挂载到 assistant，形成可扩展的私人助理系统。
          </p>
        </div>
        <button className="refresh-btn" onClick={handleReload}>
          重新装载
        </button>
      </div>

      {error && <div className="evolution-error">{error}</div>}

      <div className="evolution-stats">
        <div className="evolution-stat-card">
          <span>主 Agent</span>
          <strong>{graph?.summary.master_agent || '未设置'}</strong>
        </div>
        <div className="evolution-stat-card">
          <span>子 Agent</span>
          <strong>{graph?.summary.agents ?? 0}</strong>
        </div>
        <div className="evolution-stat-card">
          <span>Tool 总数</span>
          <strong>{graph?.summary.tools ?? 0}</strong>
        </div>
        <div className="evolution-stat-card highlight">
          <span>动态 Tool</span>
          <strong>{graph?.summary.dynamic_tools ?? 0}</strong>
        </div>
      </div>

      <div className="evolution-grid">
        <section className="evolution-card evolution-card--wide">
          <div className="card-title-row">
            <h3>能力网络</h3>
            <span>{graph?.summary.edges ?? 0} 条调用边</span>
          </div>

          {loading ? (
            <div className="evolution-placeholder">加载能力网络...</div>
          ) : (
            <div className="capability-map">
              <div className="master-node">
                <span className="node-label">Master</span>
                <strong>assistant</strong>
              </div>
              <div className="edge-list">
                {assistantEdges.length === 0 ? (
                  <div className="evolution-placeholder">assistant 暂无已挂载能力</div>
                ) : (
                  assistantEdges.map((edge) => (
                    <div key={`${edge.source}-${edge.target}`} className="edge-item">
                      <span className={`edge-kind ${edge.kind}`}>{edge.kind}</span>
                      <span className="edge-arrow">{'->'}</span>
                      <strong>{edge.target}</strong>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </section>

        <section className="evolution-card evolution-card--wide">
          <div className="card-title-row">
            <h3>Tool 提示词管理</h3>
            <span>JSON Schema 只读，提示词可编辑并热重载</span>
          </div>
          <div className="tool-prompt-editor">
            <div className="tool-prompt-list">
              {toolPrompts.map((item) => (
                <button
                  key={item.name}
                  className={selectedPromptName === item.name ? 'active' : ''}
                  type="button"
                  onClick={() => handleSelectPrompt(item.name)}
                >
                  <strong>{item.name}</strong>
                  <span>{item.type === 'dynamic_tool' ? '动态 Tool' : 'Tool'}</span>
                </button>
              ))}
            </div>

            <div className="tool-prompt-detail">
              {selectedPrompt ? (
                <>
                  <div className="tool-prompt-meta">
                    <span>{selectedPrompt.type === 'dynamic_tool' ? '动态 Tool' : '原生 Tool'}</span>
                    <span>{selectedPrompt.prompt_source === 'custom' ? '自定义提示词' : '默认提示词'}</span>
                    {selectedPrompt.mode && <span>{selectedPrompt.mode}</span>}
                  </div>
                  <label className="prompt-label">暴露给 LLM 的 Tool 提示词</label>
                  <textarea
                    className="tool-prompt-textarea"
                    value={promptDraft}
                    onChange={(event) => setPromptDraft(event.target.value)}
                    rows={6}
                  />
                  <div className="tool-prompt-actions">
                    <button
                      className="btn-primary-sm"
                      onClick={handleSavePrompt}
                      disabled={savingPrompt || promptDraft.trim() === selectedPrompt.prompt.trim()}
                    >
                      {savingPrompt ? '保存中...' : '保存提示词'}
                    </button>
                  </div>
                  <label className="prompt-label">JSON Schema（只读）</label>
                  <pre className="readonly-schema">
                    {JSON.stringify(selectedPrompt.schema, null, 2)}
                  </pre>
                </>
              ) : (
                <div className="evolution-placeholder">暂无可编辑 Tool</div>
              )}
            </div>
          </div>
        </section>

        <section className="evolution-card">
          <h3>运行时创建 Tool</h3>
          <div className="evolution-form">
            <input
              value={toolName}
              onChange={(event) => setToolName(event.target.value)}
              placeholder="tool_name，如 requirement_guard"
            />
            <input
              value={toolDescription}
              onChange={(event) => setToolDescription(event.target.value)}
              placeholder="工具描述，会展示给 Agent"
            />
            <select
              value={toolMode}
              onChange={(event) => setToolMode(event.target.value as DynamicMode)}
            >
              <option value="checklist">checklist 需求检查</option>
              <option value="template">template 模板加工</option>
              <option value="regex_extract">regex_extract 正则抽取</option>
            </select>

            {toolMode === 'template' && (
              <textarea
                value={templateText}
                onChange={(event) => setTemplateText(event.target.value)}
                rows={4}
                placeholder="可使用 {{text}}、{{style}} 这类占位符"
              />
            )}
            {toolMode === 'checklist' && (
              <>
                <textarea
                  value={requiredTerms}
                  onChange={(event) => setRequiredTerms(event.target.value)}
                  rows={3}
                  placeholder="必需关键词，逗号或换行分隔"
                />
                <textarea
                  value={forbiddenTerms}
                  onChange={(event) => setForbiddenTerms(event.target.value)}
                  rows={3}
                  placeholder="禁止关键词，逗号或换行分隔"
                />
              </>
            )}
            {toolMode === 'regex_extract' && (
              <textarea
                value={patternsText}
                onChange={(event) => setPatternsText(event.target.value)}
                rows={4}
                placeholder="每行一个规则，如 email=[\\w.-]+@[\\w.-]+"
              />
            )}

            <label className="evolution-check">
              <input
                type="checkbox"
                checked={attachToAssistant}
                onChange={(event) => setAttachToAssistant(event.target.checked)}
              />
              创建后立即挂载到 assistant
            </label>
            <button className="btn-primary-sm" onClick={handleCreateTool} disabled={savingTool}>
              {savingTool ? '装载中...' : '创建并装载 Tool'}
            </button>
          </div>
        </section>

        <section className="evolution-card">
          <h3>创建可调用子 Agent</h3>
          <div className="evolution-form">
            <input
              value={agentName}
              onChange={(event) => setAgentName(event.target.value)}
              placeholder="agent_name，如 researcher"
            />
            <input
              value={agentDescription}
              onChange={(event) => setAgentDescription(event.target.value)}
              placeholder="子 Agent 描述"
            />
            <textarea
              value={agentPrompt}
              onChange={(event) => setAgentPrompt(event.target.value)}
              rows={7}
              placeholder="System Prompt"
            />
            <div className="tool-chip-picker">
              {availableToolOptions.map((node) => (
                <button
                  key={node.id}
                  className={agentTools.includes(node.id) ? 'selected' : ''}
                  onClick={() => toggleAgentTool(node.id)}
                  type="button"
                >
                  {node.id}
                </button>
              ))}
            </div>
            <button className="btn-primary-sm" onClick={handleCreateAgent} disabled={savingAgent}>
              {savingAgent ? '创建中...' : '创建子 Agent'}
            </button>
          </div>
        </section>
      </div>

      <div className="inventory-grid">
        <section className="evolution-card">
          <h3>Agent 库</h3>
          <div className="inventory-list">
            {agents.map((node) => (
              <div key={node.id} className="inventory-item">
                <div>
                  <strong>{node.id}</strong>
                  <span>{node.description || '无描述'}</span>
                </div>
                <em>{node.capabilities?.length || 0} tools</em>
              </div>
            ))}
          </div>
        </section>

        <section className="evolution-card">
          <h3>Tool 库</h3>
          <div className="inventory-list">
            {tools.map((node) => (
              <div key={node.id} className="inventory-item">
                <div>
                  <strong>{node.id}</strong>
                  <span>{node.description || '无描述'}</span>
                </div>
                <em>{nodeTypeLabel(node)}</em>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
