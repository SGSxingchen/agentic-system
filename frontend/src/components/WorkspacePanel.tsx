import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from 'react'
import * as api from '../api/client'
import { useAppStore } from '../store/appStore'
import type {
  ManagedWorkspace,
  WorkspaceFileContent,
} from '../types'
import {
  normalizeWorkspaceFileContent,
  normalizeWorkspaceFileEntry,
} from '../utils/workspaceContract'
import './WorkspacePanel.css'

function formatBytes(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value) || value < 0) return '—'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = value / 1024
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unitIndex]}`
}

function formatDateTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

interface TreeNode {
  path: string
  name: string
  type: 'file' | 'directory'
  size?: number | null
  updated_at?: string | null
}

interface DirState {
  loaded: boolean
  loading: boolean
  expanded: boolean
  children: TreeNode[]
}

const ROOT_PATH = ''

export function WorkspacePanel() {
  const { state, dispatch } = useAppStore()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ManagedWorkspace | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // import form
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [pickedFile, setPickedFile] = useState<File | null>(null)
  const [importName, setImportName] = useState('')
  const [importing, setImporting] = useState(false)

  // tree expansion state, key=dir path
  const [tree, setTree] = useState<Record<string, DirState>>({})

  // file editor
  const [activeFile, setActiveFile] = useState<string | null>(null)
  const [fileContent, setFileContent] = useState<WorkspaceFileContent | null>(null)
  const [editing, setEditing] = useState('')
  const [originalContent, setOriginalContent] = useState('')
  const [fileLoading, setFileLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const dirty = activeFile != null && fileContent?.editable && editing !== originalContent

  const flashNotice = (message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(''), 2400)
  }

  // ───── load workspaces (initial + after import/delete) ─────
  const loadWorkspaces = useCallback(
    async (preferredId?: string) => {
      setError('')
      const res = await api.listWorkspaces()
      if (res.status !== 'ok' || !Array.isArray(res.data)) {
        setError(res.message || '加载工作区失败')
        return
      }
      const items = res.data
      dispatch({ type: 'SET_WORKSPACES', payload: items })
      setSelectedId((current) => {
        if (preferredId && items.some((item) => item.id === preferredId)) return preferredId
        if (current && items.some((item) => item.id === current)) return current
        return items[0]?.id || null
      })
      if (items.length === 0) {
        setDetail(null)
        setActiveFile(null)
        setFileContent(null)
      }
    },
    [dispatch]
  )

  useEffect(() => {
    loadWorkspaces()
  }, [loadWorkspaces])

  // ───── selected workspace detail ─────
  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      setTree({})
      setActiveFile(null)
      setFileContent(null)
      return
    }

    let cancelled = false
    setDetailLoading(true)
    setActiveFile(null)
    setFileContent(null)
    setTree({})
    api.getWorkspace(selectedId).then((res) => {
      if (cancelled) return
      if (res.status === 'ok' && res.data) {
        setDetail(res.data)
        const rootChildren = (res.data.files || []).map(normalizeWorkspaceFileEntry) as TreeNode[]
        setTree({
          [ROOT_PATH]: {
            loaded: true,
            loading: false,
            expanded: true,
            children: rootChildren,
          },
        })
      } else {
        setError(res.message || '工作区详情加载失败')
      }
      setDetailLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [selectedId])

  const ensureDirLoaded = useCallback(
    async (workspaceId: string, dirPath: string) => {
      const current = tree[dirPath]
      if (current?.loaded) return
      setTree((prev) => ({
        ...prev,
        [dirPath]: { loaded: false, loading: true, expanded: true, children: [] },
      }))
      const res = await api.listWorkspaceFiles(workspaceId, dirPath)
      if (res.status === 'ok' && res.data) {
        const children = (res.data.files || []).map(normalizeWorkspaceFileEntry) as TreeNode[]
        setTree((prev) => ({
          ...prev,
          [dirPath]: { loaded: true, loading: false, expanded: true, children },
        }))
      } else {
        setTree((prev) => ({
          ...prev,
          [dirPath]: { loaded: false, loading: false, expanded: false, children: [] },
        }))
        setError(res.message || '加载目录失败')
      }
    },
    [tree]
  )

  const handleToggleDir = (dirPath: string) => {
    if (!selectedId) return
    const current = tree[dirPath]
    if (!current || !current.loaded) {
      ensureDirLoaded(selectedId, dirPath)
      return
    }
    setTree((prev) => ({
      ...prev,
      [dirPath]: { ...current, expanded: !current.expanded },
    }))
  }

  // ───── file selection / loading ─────
  const handleSelectFile = async (filePath: string) => {
    if (!selectedId) return
    if (dirty) {
      const ok = window.confirm('当前文件有未保存的修改，是否放弃？')
      if (!ok) return
    }
    setActiveFile(filePath)
    setFileLoading(true)
    setFileContent(null)
    const res = await api.getWorkspaceFileContent(selectedId, filePath)
    setFileLoading(false)
    if (res.status === 'ok' && res.data) {
      const normalized = normalizeWorkspaceFileContent(res.data)
      setFileContent(normalized)
      setEditing(normalized.content || '')
      setOriginalContent(normalized.content || '')
    } else {
      setError(res.message || '读取文件失败')
    }
  }

  const handleSave = async () => {
    if (!selectedId || !activeFile || !fileContent?.editable) return
    setSaving(true)
    const res = await api.saveWorkspaceFileContent(selectedId, {
      path: activeFile,
      content: editing,
      encoding: fileContent.encoding || 'utf-8',
    })
    setSaving(false)
    if (res.status === 'ok') {
      setOriginalContent(editing)
      flashNotice('已保存')
    } else {
      setError(res.message || '保存失败')
    }
  }

  const handleResetFile = () => {
    if (!fileContent) return
    setEditing(originalContent)
  }

  // ───── import ─────
  const handlePickFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null
    setPickedFile(file)
    if (file && !importName.trim()) {
      setImportName(file.name.replace(/\.zip$/i, ''))
    }
  }

  const handleImport = async () => {
    if (!pickedFile) {
      setError('请先选择 ZIP 压缩包')
      return
    }
    if (!pickedFile.name.toLowerCase().endsWith('.zip')) {
      setError('当前仅支持 .zip 压缩包')
      return
    }
    setImporting(true)
    setError('')
    const res = await api.importWorkspace({
      file: pickedFile,
      name: importName,
    })
    setImporting(false)
    if (res.status === 'ok' && res.data) {
      setPickedFile(null)
      setImportName('')
      if (fileInputRef.current) fileInputRef.current.value = ''
      flashNotice('工作区已导入')
      await loadWorkspaces(res.data.id)
    } else {
      setError(res.message || '导入失败')
    }
  }

  const handleDelete = async () => {
    if (!selectedId || !detail) return
    const ok = window.confirm(`确认删除工作区「${detail.name}」？此操作不可撤销。`)
    if (!ok) return
    const res = await api.deleteWorkspace(selectedId)
    if (res.status === 'ok') {
      // if currently selected as global, clear selection
      if (state.selectedWorkspace?.id === selectedId) {
        dispatch({ type: 'SET_SELECTED_WORKSPACE', payload: null })
      }
      setSelectedId(null)
      setDetail(null)
      setActiveFile(null)
      setFileContent(null)
      flashNotice('工作区已删除')
      await loadWorkspaces()
    } else {
      setError(res.message || '删除失败')
    }
  }

  const handleSetGlobalWorkspace = () => {
    if (!detail) return
    dispatch({
      type: 'SET_SELECTED_WORKSPACE',
      payload: { id: detail.id, name: detail.name },
    })
    flashNotice('已设为当前工作区')
  }

  // ───── derived ─────
  const isGlobalSelected = state.selectedWorkspace?.id === detail?.id

  const visibleTree = useMemo(() => {
    if (!detail) return [] as Array<{ node: TreeNode; depth: number }>
    const rows: Array<{ node: TreeNode; depth: number }> = []

    const walk = (path: string, depth: number) => {
      const dir = tree[path]
      if (!dir) return
      const sorted = [...dir.children].sort((a, b) => {
        if (a.type === 'directory' && b.type !== 'directory') return -1
        if (a.type !== 'directory' && b.type === 'directory') return 1
        return a.name.localeCompare(b.name, 'zh-CN')
      })
      for (const child of sorted) {
        rows.push({ node: child, depth })
        if (child.type === 'directory') {
          const childDir = tree[child.path]
          if (childDir?.expanded) {
            walk(child.path, depth + 1)
          }
        }
      }
    }
    walk(ROOT_PATH, 0)
    return rows
  }, [tree, detail])

  // ───── render ─────
  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">工作区</h1>
          <div className="page__subtitle">
            导入项目压缩包后，工作区可作为对话与运行的默认上下文。
            项目文件是用户资料，不是系统指令。
          </div>
        </div>
        <div className="page__actions">
          <button type="button" onClick={() => loadWorkspaces()} disabled={detailLoading}>
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert--error">
          <span style={{ flex: 1 }}>{error}</span>
          <button className="btn-xs" onClick={() => setError('')}>
            关闭
          </button>
        </div>
      )}
      {notice && <div className="alert alert--success">{notice}</div>}

      <div className="workspace-shell">
        {/* ===== 左侧：工作区列表 + 导入 ===== */}
        <aside className="workspace-list-pane">
          <div className="workspace-list-pane__header">
            <span className="workspace-list-pane__title">已管理工作区</span>
            <span className="text-muted">{state.workspaces.length} 个</span>
          </div>
          <div className="workspace-list-pane__list">
            {state.workspaces.length === 0 ? (
              <div className="empty-state">
                <strong>暂无工作区</strong>
                <span>请导入项目压缩包。</span>
              </div>
            ) : (
              state.workspaces.map((workspace) => (
                <button
                  key={workspace.id}
                  type="button"
                  className={`workspace-row ${
                    selectedId === workspace.id ? 'workspace-row--active' : ''
                  }`}
                  onClick={() => setSelectedId(workspace.id)}
                >
                  <span className="workspace-row__name">{workspace.name}</span>
                  <span className="workspace-row__count">
                    {workspace.metadata?.file_count ?? '—'}
                  </span>
                  <span className="workspace-row__meta">
                    {workspace.kind === 'project' ? '受管理项目' : workspace.kind} ·
                    {' '}
                    {formatDateTime(workspace.updated_at)}
                  </span>
                </button>
              ))
            )}
          </div>

          <div className="workspace-import-area">
            <span className="workspace-import-area__title">导入压缩包</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip,application/zip,application/x-zip-compressed"
              onChange={handlePickFile}
            />
            {pickedFile && (
              <div style={{ fontSize: 11.5, color: 'var(--color-text-muted)' }}>
                {pickedFile.name} · {formatBytes(pickedFile.size)}
              </div>
            )}
            <input
              type="text"
              placeholder="工作区名称（可选）"
              value={importName}
              onChange={(event) => setImportName(event.target.value)}
            />
            <button
              type="button"
              className="btn-primary"
              onClick={handleImport}
              disabled={importing || !pickedFile}
            >
              {importing ? '导入中…' : '导入工作区'}
            </button>
          </div>
        </aside>

        {/* ===== 右侧：详情 ===== */}
        {detail ? (
          <section className="workspace-detail">
            <header className="workspace-detail__header">
              <div className="workspace-detail__title-row">
                <div>
                  <h2 className="workspace-detail__title">{detail.name}</h2>
                  <div className="workspace-detail__title-sub">
                    {detail.metadata?.description || '未提供说明'}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    className={isGlobalSelected ? '' : 'btn-primary'}
                    onClick={handleSetGlobalWorkspace}
                    disabled={isGlobalSelected}
                  >
                    {isGlobalSelected ? '当前工作区' : '设为当前工作区'}
                  </button>
                  <button type="button" className="btn-danger" onClick={handleDelete}>
                    删除
                  </button>
                </div>
              </div>
              <dl className="workspace-detail__meta">
                <div>
                  <dt>工作区 ID</dt>
                  <dd>{detail.id}</dd>
                </div>
                <div>
                  <dt>类型 / 来源</dt>
                  <dd>
                    {detail.kind || '—'} / {detail.source || '—'}
                  </dd>
                </div>
                <div>
                  <dt>文件数量</dt>
                  <dd>
                    {detail.metadata?.file_count ?? '—'} 文件 ·{' '}
                    {detail.metadata?.directory_count ?? '—'} 目录
                  </dd>
                </div>
                <div>
                  <dt>总大小</dt>
                  <dd>{formatBytes(detail.metadata?.total_bytes)}</dd>
                </div>
                <div>
                  <dt>根路径</dt>
                  <dd>{detail.root_path || '—'}</dd>
                </div>
                <div>
                  <dt>创建时间</dt>
                  <dd>{formatDateTime(detail.created_at)}</dd>
                </div>
                <div>
                  <dt>更新时间</dt>
                  <dd>{formatDateTime(detail.updated_at)}</dd>
                </div>
              </dl>
            </header>

            <div className="workspace-detail__body">
              <div className="workspace-tree">
                <div className="workspace-tree__header">
                  <span>文件树</span>
                  <span>{visibleTree.length} 项</span>
                </div>
                <div className="workspace-tree__list">
                  {visibleTree.length === 0 && (
                    <div className="empty-state">
                      <span>工作区为空</span>
                    </div>
                  )}
                  {visibleTree.map(({ node, depth }) => (
                    <button
                      key={node.path}
                      type="button"
                      className={`workspace-tree__node ${
                        activeFile === node.path ? 'workspace-tree__node--active' : ''
                      }`}
                      style={{ paddingLeft: 6 + depth * 14 }}
                      onClick={() => {
                        if (node.type === 'directory') {
                          handleToggleDir(node.path)
                        } else {
                          handleSelectFile(node.path)
                        }
                      }}
                    >
                      <span className="workspace-tree__chevron">
                        {node.type === 'directory'
                          ? tree[node.path]?.expanded
                            ? '▾'
                            : '▸'
                          : ''}
                      </span>
                      <span className="workspace-tree__icon">
                        {node.type === 'directory' ? (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                          </svg>
                        ) : (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                            <path d="M14 3v5h5" />
                            <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          </svg>
                        )}
                      </span>
                      <span className="workspace-tree__name">{node.name}</span>
                      {node.type === 'file' && (
                        <span className="text-muted" style={{ fontSize: 11 }}>
                          {formatBytes(node.size)}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              {/* ===== 编辑器 ===== */}
              <div className="workspace-editor">
                {!activeFile ? (
                  <div className="workspace-editor__placeholder">
                    <strong>请选择文件查看或编辑</strong>
                    <span style={{ fontSize: 12 }}>
                      点击左侧文件树。文本文件可在线编辑，二进制或超过 1 MB 的文件为只读。
                    </span>
                  </div>
                ) : (
                  <>
                    <div className="workspace-editor__header">
                      <span className="workspace-editor__path">{activeFile}</span>
                      <div className="workspace-editor__actions">
                        {fileContent?.editable && (
                          <>
                            <button
                              type="button"
                              className="btn-sm"
                              onClick={handleResetFile}
                              disabled={!dirty || saving}
                            >
                              撤回
                            </button>
                            <button
                              type="button"
                              className="btn-primary btn-sm"
                              onClick={handleSave}
                              disabled={!dirty || saving}
                            >
                              {saving ? '保存中…' : '保存'}
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    {fileLoading ? (
                      <div className="workspace-editor__placeholder">
                        <span>正在读取文件…</span>
                      </div>
                    ) : !fileContent ? (
                      <div className="workspace-editor__placeholder">
                        <span>文件内容不可用。</span>
                      </div>
                    ) : !fileContent.is_text || fileContent.binary ? (
                      <div className="workspace-readonly-note">
                        <strong>二进制文件，不可在线编辑</strong>
                        <span>大小：{formatBytes(fileContent.size)}</span>
                      </div>
                    ) : fileContent.too_large ? (
                      <div className="workspace-readonly-note">
                        <strong>文件超过 {formatBytes(fileContent.max_editable_bytes)}，仅显示前段内容</strong>
                        <span>大小：{formatBytes(fileContent.size)}</span>
                        <pre style={{ marginTop: 12, width: '100%', maxHeight: 320 }}>
                          {fileContent.content}
                        </pre>
                      </div>
                    ) : (
                      <textarea
                        className="workspace-editor__textarea"
                        value={editing}
                        onChange={(event) => setEditing(event.target.value)}
                        spellCheck={false}
                      />
                    )}

                    <div className="workspace-status-bar">
                      <span>
                        {fileContent
                          ? `${fileContent.encoding} · ${formatBytes(fileContent.size)}`
                          : ''}
                      </span>
                      <span>
                        {dirty ? (
                          <span className="workspace-status-bar__dirty">未保存</span>
                        ) : (
                          <span>已同步</span>
                        )}
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>
        ) : (
          <section className="workspace-detail">
            <header className="workspace-detail__header">
              <div className="empty-state">
                <strong>请选择一个工作区</strong>
                <span>导入压缩包后，工作区会出现在左侧列表。</span>
              </div>
            </header>
          </section>
        )}
      </div>
    </div>
  )
}
