import type { WorkspaceFileContent, WorkspaceFileEntry } from '../types'

export interface WorkspaceTreeFile {
  path: string
  name: string
  type: 'file' | 'directory'
  size?: number | null
  updated_at?: string | null
}

function basename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path || '/'
}

export function normalizeWorkspaceFileEntry(
  file: WorkspaceFileEntry
): WorkspaceTreeFile {
  const raw = file as WorkspaceFileEntry & {
    kind?: string | null
    modified_at?: string | null
  }
  const type = raw.type === 'directory' || raw.kind === 'directory'
    ? 'directory'
    : 'file'

  return {
    path: raw.path,
    name: raw.name || basename(raw.path),
    type,
    size: raw.size,
    updated_at: raw.updated_at ?? raw.modified_at ?? null,
  }
}

export function normalizeWorkspaceFileContent(
  content: WorkspaceFileContent
): WorkspaceFileContent {
  const raw = content as WorkspaceFileContent & {
    kind?: string | null
    binary?: boolean | null
    is_text?: boolean | null
    too_large?: boolean | null
    max_editable_bytes?: number | null
  }
  const binary = raw.binary ?? raw.kind === 'binary'
  const isText = raw.is_text ?? (!binary && typeof raw.content === 'string')
  const tooLarge = raw.too_large ?? Boolean(raw.truncated)
  const maxEditableBytes = raw.max_editable_bytes ?? raw.size

  return {
    ...raw,
    binary,
    is_text: isText,
    too_large: tooLarge,
    max_editable_bytes: maxEditableBytes,
    editable: Boolean(raw.editable && isText && !binary && !tooLarge),
  }
}
