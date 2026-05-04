import { useState, useEffect, useCallback, DragEvent } from 'react'
import * as api from '../api/client'
import './PipelinePanel.css'

interface PipelineStep {
  name: string
  agent: string
  input?: Record<string, string>
  output_key?: string
  condition?: string
  max_iterations?: number
  timeout?: number
}

interface PipelineTemplate {
  name: string
  description: string
  mode: string
  steps: PipelineStep[]
}

interface PipelineExecution {
  id: string
  pipeline_id: string
  status: 'running' | 'completed' | 'failed'
  current_step?: number
  results?: Record<string, unknown>
  step_results?: Array<{
    step_name: string
    status: string
    output?: unknown
    error?: string | null
    duration_ms?: number | null
  }>
  duration_ms?: number
  started_at: string
  finished_at?: string
}

interface StepFormData {
  name: string
  agent: string
  input: { key: string; value: string }[]
  output_key: string
  condition: string
  max_iterations: number
  timeout: string
}

interface PipelineFormData {
  name: string
  description: string
  mode: string
  steps: StepFormData[]
}

const EMPTY_STEP: StepFormData = {
  name: '',
  agent: '',
  input: [],
  output_key: '',
  condition: '',
  max_iterations: 1,
  timeout: '',
}

export function PipelinePanel() {
  const [templates, setTemplates] = useState<PipelineTemplate[]>([])
  const [executions, setExecutions] = useState<PipelineExecution[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null)
  const [inputText, setInputText] = useState('')
  const [executing, setExecuting] = useState(false)
  const [apiAvailable, setApiAvailable] = useState(true)

  // CRUD 状态
  const [editingPipeline, setEditingPipeline] = useState<string | null>(null)
  const [form, setForm] = useState<PipelineFormData>({ name: '', description: '', mode: 'sequential', steps: [] })
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [availableAgents, setAvailableAgents] = useState<string[]>([])

  // 拖拽状态
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)

  const fetchTemplates = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.getPipelineTemplates()
      if (res.status === 'ok' && res.data) {
        const data = res.data as unknown
        let parsed: PipelineTemplate[] = []
        if (Array.isArray(data)) {
          parsed = (data as Record<string, unknown>[]).map((item) => ({
            name: (item.name as string) || (item.id as string) || '',
            description: (item.description as string) || '',
            mode: (item.mode as string) || 'sequential',
            steps: ((item.steps as unknown[]) || []).map((s: unknown) =>
              typeof s === 'string' ? { name: s, agent: s } : (s as PipelineStep)
            ),
          }))
        }
        setTemplates(parsed)
        setApiAvailable(true)
      } else {
        setApiAvailable(false)
        setTemplates([])
      }
    } catch {
      setApiAvailable(false)
      setTemplates([])
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchAgents = useCallback(async () => {
    // 从 capabilities 列表获取所有可用能力（Agent + 工具）
    const res = await api.listCapabilities()
    if (res.status === 'ok' && res.data) {
      setAvailableAgents((res.data as { name: string }[]).map((a) => a.name))
    } else {
      // fallback: 只获取 agent 列表
      const agentRes = await api.listAgents()
      if (agentRes.status === 'ok' && agentRes.data) {
        setAvailableAgents((agentRes.data as { name: string }[]).map((a) => a.name))
      }
    }
  }, [])

  useEffect(() => {
    fetchTemplates()
    fetchAgents()
  }, [fetchTemplates, fetchAgents])

  // ─── CRUD ──────────────────────────────────────────

  const startCreate = () => {
    setEditingPipeline('__new__')
    setForm({ name: '', description: '', mode: 'sequential', steps: [{ ...EMPTY_STEP }] })
    setSelectedPipeline(null)
    setConfirmDelete(null)
  }

  const startEdit = (tpl: PipelineTemplate) => {
    setEditingPipeline(tpl.name)
    setForm({
      name: tpl.name,
      description: tpl.description,
      mode: tpl.mode,
      steps: tpl.steps.map((s) => ({
        name: s.name,
        agent: s.agent,
        input: s.input ? Object.entries(s.input).map(([key, value]) => ({ key, value })) : [],
        output_key: s.output_key || '',
        condition: s.condition || '',
        max_iterations: s.max_iterations || 1,
        timeout: s.timeout != null ? String(s.timeout) : '',
      })),
    })
    setSelectedPipeline(null)
    setConfirmDelete(null)
  }

  const cancelEdit = () => {
    setEditingPipeline(null)
    setError('')
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')

    for (const [index, step] of form.steps.entries()) {
      if (step.timeout.trim()) {
        const timeout = Number(step.timeout)
        if (!Number.isFinite(timeout) || timeout <= 0) {
          setError(`第 ${index + 1} 步 timeout 必须是大于 0 的数字`)
          setSaving(false)
          return
        }
      }
    }

    const steps = form.steps.map((s) => {
      const input: Record<string, string> = {}
      for (const kv of s.input) {
        if (kv.key.trim()) input[kv.key.trim()] = kv.value
      }
      return {
        name: s.name,
        agent: s.agent,
        ...(Object.keys(input).length > 0 ? { input } : {}),
        ...(s.output_key ? { output_key: s.output_key } : {}),
        ...(s.condition ? { condition: s.condition } : {}),
        ...(s.max_iterations > 1 ? { max_iterations: s.max_iterations } : {}),
        ...(s.timeout.trim() ? { timeout: Number(s.timeout) } : {}),
      }
    })

    let res
    if (editingPipeline === '__new__') {
      if (!form.name.trim()) {
        setError('名称不能为空')
        setSaving(false)
        return
      }
      res = await api.createPipeline({ name: form.name.trim(), description: form.description, mode: form.mode, steps })
    } else {
      res = await api.updatePipeline(editingPipeline!, { description: form.description, mode: form.mode, steps })
    }

    if (res.status === 'ok') {
      cancelEdit()
      await fetchTemplates()
    } else {
      setError(res.message || '保存失败')
    }
    setSaving(false)
  }

  const handleDelete = async (name: string) => {
    const res = await api.deletePipeline(name)
    if (res.status === 'ok') {
      setConfirmDelete(null)
      await fetchTemplates()
    } else {
      setError(res.message || '删除失败')
    }
  }

  // ─── 步骤编辑 ──────────────────────────────────────

  const addStep = () => setForm({ ...form, steps: [...form.steps, { ...EMPTY_STEP }] })
  const removeStep = (idx: number) => setForm({ ...form, steps: form.steps.filter((_, i) => i !== idx) })
  const updateStep = (idx: number, field: keyof StepFormData, value: unknown) => {
    const next = [...form.steps]
    next[idx] = { ...next[idx], [field]: value }
    setForm({ ...form, steps: next })
  }

  // 步骤 input KV
  const addStepInput = (idx: number) => {
    const next = [...form.steps]
    next[idx] = { ...next[idx], input: [...next[idx].input, { key: '', value: '' }] }
    setForm({ ...form, steps: next })
  }
  const removeStepInput = (stepIdx: number, kvIdx: number) => {
    const next = [...form.steps]
    next[stepIdx] = { ...next[stepIdx], input: next[stepIdx].input.filter((_, i) => i !== kvIdx) }
    setForm({ ...form, steps: next })
  }
  const updateStepInput = (stepIdx: number, kvIdx: number, field: 'key' | 'value', val: string) => {
    const next = [...form.steps]
    const inputs = [...next[stepIdx].input]
    inputs[kvIdx] = { ...inputs[kvIdx], [field]: val }
    next[stepIdx] = { ...next[stepIdx], input: inputs }
    setForm({ ...form, steps: next })
  }

  // ─── 拖拽 ──────────────────────────────────────────

  const handleDragStart = (e: DragEvent, idx: number) => {
    setDragIndex(idx)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e: DragEvent, idx: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverIndex(idx)
  }

  const handleDragEnd = () => {
    if (dragIndex !== null && dragOverIndex !== null && dragIndex !== dragOverIndex) {
      const next = [...form.steps]
      const [moved] = next.splice(dragIndex, 1)
      next.splice(dragOverIndex, 0, moved)
      setForm({ ...form, steps: next })
    }
    setDragIndex(null)
    setDragOverIndex(null)
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
  }

  // ─── 执行 ──────────────────────────────────────────

  const handleExecute = async () => {
    if (!selectedPipeline || !inputText.trim()) return
    setExecuting(true)
    setError('')
    try {
      const res = await api.executePipeline(selectedPipeline, { user_requirement: inputText.trim() })
      if (res.status === 'ok' && res.data) {
        const raw = res.data as unknown as Record<string, unknown>
        const now = new Date().toISOString()
        const execution: PipelineExecution = {
          id: String(raw.id || `${selectedPipeline}-${Date.now()}`),
          pipeline_id: String(raw.pipeline_id || raw.template_id || selectedPipeline),
          status: raw.status === 'failed' ? 'failed' : raw.status === 'running' ? 'running' : 'completed',
          results: (raw.results || raw.context || raw.output || raw) as Record<string, unknown>,
          step_results: Array.isArray(raw.step_results)
            ? raw.step_results as PipelineExecution['step_results']
            : undefined,
          duration_ms: typeof raw.duration_ms === 'number' ? raw.duration_ms : undefined,
          started_at: String(raw.started_at || now),
          finished_at: String(raw.finished_at || raw.completed_at || now),
        }
        setExecutions((prev) => [execution, ...prev])
        setInputText('')
      } else {
        setError(res.message || '执行失败')
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '执行管线失败')
    } finally {
      setExecuting(false)
    }
  }

  // ─── 渲染编辑表单 ──────────────────────────────────

  const renderEditForm = () => {
    const isNew = editingPipeline === '__new__'

    return (
      <div className="pipeline-form">
        <h3 className="pipeline-form__title">{isNew ? '新建管线' : `编辑: ${editingPipeline}`}</h3>

        <div className="pipeline-form__fields">
          <div className="form-group">
            <label>名称</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              disabled={!isNew}
              placeholder="英文下划线格式，如 my_pipeline"
            />
          </div>

          <div className="form-group">
            <label>描述</label>
            <input
              type="text"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="管线功能描述"
            />
          </div>

          <div className="form-group">
            <label>执行模式</label>
            <div className="mode-selector">
              <label className={`mode-option ${form.mode === 'sequential' ? 'mode-option--active' : ''}`}>
                <input type="radio" name="mode" value="sequential" checked={form.mode === 'sequential'} onChange={(e) => setForm({ ...form, mode: e.target.value })} />
                顺序执行
              </label>
              <label className={`mode-option ${form.mode === 'parallel' ? 'mode-option--active' : ''}`}>
                <input type="radio" name="mode" value="parallel" checked={form.mode === 'parallel'} onChange={(e) => setForm({ ...form, mode: e.target.value })} />
                并行执行
              </label>
            </div>
          </div>
        </div>

        {/* 步骤编辑器 */}
        <div className="step-editor">
          <label className="step-editor__label">步骤列表（可拖拽排序）</label>
          {form.steps.map((step, idx) => (
            <div
              key={idx}
              className={`step-editor__item ${dragIndex === idx ? 'step-editor__item--dragging' : ''} ${dragOverIndex === idx ? 'step-editor__item--drag-over' : ''}`}
              draggable
              onDragStart={(e) => handleDragStart(e, idx)}
              onDragOver={(e) => handleDragOver(e, idx)}
              onDragEnd={handleDragEnd}
              onDrop={handleDrop}
            >
              <div className="step-editor__handle" title="拖拽排序">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="9" cy="5" r="2" /><circle cx="15" cy="5" r="2" />
                  <circle cx="9" cy="12" r="2" /><circle cx="15" cy="12" r="2" />
                  <circle cx="9" cy="19" r="2" /><circle cx="15" cy="19" r="2" />
                </svg>
              </div>
              <div className="step-editor__num">{idx + 1}</div>
              <div className="step-editor__fields">
                <div className="step-editor__row">
                  <input
                    className="step-editor__input"
                    value={step.name}
                    onChange={(e) => updateStep(idx, 'name', e.target.value)}
                    placeholder="步骤名称"
                  />
                  <select
                    className="step-editor__select"
                    value={step.agent}
                    onChange={(e) => updateStep(idx, 'agent', e.target.value)}
                  >
                    <option value="">-- 选择能力 --</option>
                    {availableAgents.map((a) => (
                      <option key={a} value={a}>{a}</option>
                    ))}
                  </select>
                  <input
                    className="step-editor__input step-editor__input--sm"
                    value={step.output_key}
                    onChange={(e) => updateStep(idx, 'output_key', e.target.value)}
                    placeholder="output_key"
                  />
                </div>
                <div className="step-editor__row">
                  <input
                    className="step-editor__input"
                    value={step.condition}
                    onChange={(e) => updateStep(idx, 'condition', e.target.value)}
                    placeholder="条件表达式（可选）"
                  />
                  <input
                    className="step-editor__input step-editor__input--xs"
                    type="number"
                    min={1}
                    value={step.max_iterations}
                    onChange={(e) => updateStep(idx, 'max_iterations', parseInt(e.target.value) || 1)}
                    title="最大迭代次数"
                  />
                  <input
                    className="step-editor__input step-editor__input--xs"
                    type="number"
                    min={0.1}
                    step={0.1}
                    value={step.timeout}
                    onChange={(e) => updateStep(idx, 'timeout', e.target.value)}
                    placeholder="timeout(s)"
                    title="步骤超时秒数，留空为不限制"
                  />
                </div>
                {/* Input 映射 */}
                <div className="step-editor__inputs">
                  {step.input.map((kv, kvIdx) => (
                    <div key={kvIdx} className="kv-editor__row">
                      <input className="kv-editor__key" value={kv.key} onChange={(e) => updateStepInput(idx, kvIdx, 'key', e.target.value)} placeholder="参数名" />
                      <input className="kv-editor__value" value={kv.value} onChange={(e) => updateStepInput(idx, kvIdx, 'value', e.target.value)} placeholder="值（如 ${plan}）" />
                      <button className="btn-icon btn-icon--danger" onClick={() => removeStepInput(idx, kvIdx)}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
                      </button>
                    </div>
                  ))}
                  <button className="kv-editor__add" onClick={() => addStepInput(idx)}>+ 添加输入映射</button>
                </div>
              </div>
              <button className="btn-icon btn-icon--danger step-editor__delete" onClick={() => removeStep(idx)} title="删除步骤">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          ))}
          <button className="step-editor__add" onClick={addStep}>+ 添加步骤</button>
        </div>

        {error && <div className="pipeline-error">{error}</div>}

        <div className="button-group">
          <button className="btn-primary" onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</button>
          <button className="btn-secondary" onClick={cancelEdit}>取消</button>
        </div>
      </div>
    )
  }

  // ─── 主渲染 ────────────────────────────────────────

  return (
    <div className="pipeline-panel">
      <div className="panel-header">
        <h2>管线</h2>
        <div className="panel-header__actions">
          <button className="btn-primary-sm" onClick={startCreate} disabled={editingPipeline !== null}>+ 新建管线</button>
          <button className="refresh-btn" onClick={fetchTemplates}>刷新</button>
        </div>
      </div>

      {!apiAvailable && (
        <div className="pipeline-error" style={{ borderColor: 'rgba(217, 119, 6, 0.2)', background: 'rgba(217, 119, 6, 0.06)', color: 'var(--color-warning)' }}>
          未连接到后端，无法加载管线模板
        </div>
      )}

      {error && !editingPipeline && <div className="pipeline-error">{error}</div>}

      {/* 编辑表单 */}
      {editingPipeline && renderEditForm()}

      {/* 管线模板 */}
      {!editingPipeline && (
        <>
          {loading ? (
            <div className="pipeline-loading">
              <div className="loading-spinner" />
              <span>加载中...</span>
            </div>
          ) : templates.length === 0 ? (
            <div className="pipeline-empty">
              <div className="placeholder-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="16 3 21 3 21 8" />
                  <line x1="4" y1="20" x2="21" y2="3" />
                  <polyline points="21 16 21 21 16 21" />
                  <line x1="15" y1="15" x2="21" y2="21" />
                  <line x1="4" y1="4" x2="9" y2="9" />
                </svg>
              </div>
              <h3>暂无管线模板</h3>
              <p>点击上方「新建管线」按钮创建</p>
            </div>
          ) : (
            <div className="pipeline-templates">
              <h3 className="section-title">模板列表</h3>
              <div className="template-grid">
                {templates.map((tpl) => (
                  <div
                    key={tpl.name}
                    className={`template-card ${selectedPipeline === tpl.name ? 'selected' : ''}`}
                  >
                    <div className="template-header">
                      <span
                        className="template-name"
                        onClick={() => setSelectedPipeline(selectedPipeline === tpl.name ? null : tpl.name)}
                        style={{ cursor: 'pointer' }}
                      >
                        {tpl.name.replace(/_/g, ' ')}
                      </span>
                      <div className="template-header__actions">
                        <span className={`template-mode mode-${tpl.mode}`}>
                          {tpl.mode === 'sequential' ? '顺序' : tpl.mode === 'parallel' ? '并行' : tpl.mode}
                        </span>
                        <button className="btn-icon" onClick={() => startEdit(tpl)} title="编辑">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                          </svg>
                        </button>
                        <button className="btn-icon btn-icon--danger" onClick={() => setConfirmDelete(tpl.name)} title="删除">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          </svg>
                        </button>
                      </div>
                    </div>

                    {confirmDelete === tpl.name && (
                      <div className="confirm-strip">
                        <span>确认删除 "{tpl.name}"？</span>
                        <button className="btn-danger-sm" onClick={() => handleDelete(tpl.name)}>确定</button>
                        <button className="btn-secondary-sm" onClick={() => setConfirmDelete(null)}>取消</button>
                      </div>
                    )}

                    <p className="template-desc">{tpl.description}</p>

                    <div className="step-pipeline">
                      {(tpl.steps || []).map((step, idx) => (
                        <div key={idx} className="step-item">
                          <div className="step-number">{idx + 1}</div>
                          <div className="step-info">
                            <span className="step-name">{step.name}</span>
                            <span className="step-agent">{step.agent}</span>
                          </div>
                          {idx < (tpl.steps || []).length - 1 && (
                            <div className="step-arrow">{'\u2192'}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 执行区域 */}
          {selectedPipeline && (
            <div className="pipeline-execute-area">
              <h3 className="section-title">执行管线: {selectedPipeline.replace(/_/g, ' ')}</h3>
              <textarea
                className="pipeline-input"
                placeholder="输入需求描述..."
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                rows={3}
              />
              <button
                className="pipeline-execute-btn"
                onClick={handleExecute}
                disabled={executing || !inputText.trim()}
              >
                {executing ? '执行中...' : '开始执行'}
              </button>
            </div>
          )}

          {/* 执行历史 */}
          {executions.length > 0 && (
            <div className="pipeline-history">
              <h3 className="section-title">执行历史</h3>
              {executions.map((exec, idx) => (
                <div key={idx} className={`execution-card status-${exec.status}`}>
                  <div className="execution-header">
                    <span className="execution-id">#{exec.id?.slice(0, 8) || idx}</span>
                    <span className="execution-status">{exec.status}</span>
                  </div>
                  {exec.results && (
                    <pre className="execution-results">
                      {JSON.stringify(exec.results, null, 2)}
                    </pre>
                  )}
                  {exec.step_results && exec.step_results.length > 0 && (
                    <div className="execution-steps">
                      {exec.step_results.map((step) => (
                        <div key={step.step_name} className={`execution-step status-${step.status}`}>
                          <span>{step.step_name}</span>
                          <strong>{step.status}</strong>
                          {step.duration_ms != null && <em>{Math.round(step.duration_ms)}ms</em>}
                          {step.error && <small>{step.error}</small>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
