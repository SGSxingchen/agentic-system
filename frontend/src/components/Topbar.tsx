import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../store/appStore'

interface TopbarProps {
  pageTitle: string
}

export function Topbar({ pageTitle }: TopbarProps) {
  const { state, dispatch } = useAppStore()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', handleClick)
    return () => window.removeEventListener('mousedown', handleClick)
  }, [open])

  const selectedName = state.selectedWorkspace?.name
  const selectedId = state.selectedWorkspace?.id

  return (
    <header className="topbar" ref={ref}>
      <div className="topbar__left">
        <span className="topbar__title">{pageTitle}</span>
        <span className="topbar__divider" />
        <span className="topbar__crumb">多 Agent 协作工作台</span>
      </div>

      <div className="topbar__right">
        <button
          type="button"
          className="topbar__workspace"
          onClick={() => setOpen((value) => !value)}
        >
          <span className="topbar__workspace-label">工作区</span>
          <span className="topbar__workspace-name">
            {selectedName ?? '未选择'}
          </span>
          <svg
            width="11"
            height="11"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>

        <div
          className={`topbar__status ${
            state.connected
              ? 'topbar__status--connected'
              : 'topbar__status--disconnected'
          }`}
        >
          <span className="topbar__status-dot" />
          <span>{state.connected ? '实时通道在线' : '通道断开'}</span>
        </div>
      </div>

      {open && (
        <div className="topbar__workspace-popover">
          <div className="topbar__workspace-item" onClick={() => {
            dispatch({ type: 'SET_SELECTED_WORKSPACE', payload: null })
            setOpen(false)
          }}>
            <strong>清空选择</strong>
            <span>不绑定任何工作区</span>
          </div>
          {state.workspaces.length === 0 && (
            <div className="topbar__workspace-empty">
              暂无工作区。请在「工作区」页面导入项目压缩包。
            </div>
          )}
          {state.workspaces.map((workspace) => (
            <div
              key={workspace.id}
              className={`topbar__workspace-item ${
                selectedId === workspace.id ? 'topbar__workspace-item--active' : ''
              }`}
              onClick={() => {
                dispatch({
                  type: 'SET_SELECTED_WORKSPACE',
                  payload: { id: workspace.id, name: workspace.name },
                })
                setOpen(false)
              }}
            >
              <strong>{workspace.name}</strong>
              <span>
                {workspace.kind === 'managed' ? '受管理项目' : workspace.kind}
                {workspace.metadata?.file_count != null
                  ? ` · ${workspace.metadata.file_count} 个文件`
                  : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </header>
  )
}
