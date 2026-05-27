import { useEffect, useState } from 'react'
import * as api from '../api/client'
import type { Attachment } from '../types'
import './AttachmentChip.css'

// B1 Plan 3 P3 Task 27 — 消息卡片附件展示。
// 已发出消息只持有 attachment id 列表；这里按 id 拉一次 metadata，本地缓存，
// 图片走 <img>，其它走 📎 + filename + 点击下载。

const metadataCache = new Map<string, Attachment | null>()
const inflight = new Map<string, Promise<Attachment | null>>()

async function fetchMetadata(id: string): Promise<Attachment | null> {
  if (metadataCache.has(id)) return metadataCache.get(id) ?? null
  const cached = inflight.get(id)
  if (cached) return cached
  const promise = (async () => {
    try {
      const res = await api.getAttachmentMetadata(id)
      const data = res.status === 'ok' && res.data ? (res.data as Attachment) : null
      metadataCache.set(id, data)
      return data
    } catch {
      metadataCache.set(id, null)
      return null
    } finally {
      inflight.delete(id)
    }
  })()
  inflight.set(id, promise)
  return promise
}

function humanSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export interface AttachmentChipProps {
  id: string
  /** Optionally override the cached metadata (saves the GET roundtrip). */
  preset?: Attachment
}

export function AttachmentChip({ id, preset }: AttachmentChipProps) {
  const [meta, setMeta] = useState<Attachment | null>(preset || metadataCache.get(id) || null)
  const [loading, setLoading] = useState<boolean>(!meta)

  useEffect(() => {
    if (preset) {
      metadataCache.set(id, preset)
      setMeta(preset)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    fetchMetadata(id).then((res) => {
      if (cancelled) return
      setMeta(res)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [id, preset])

  if (loading && !meta) {
    return (
      <span className="attachment-chip attachment-chip--loading">
        <span className="attachment-chip__icon">📎</span>
        <span className="attachment-chip__name">加载中…</span>
      </span>
    )
  }
  if (!meta) {
    return (
      <span className="attachment-chip attachment-chip--missing" title={id}>
        <span className="attachment-chip__icon">⚠️</span>
        <span className="attachment-chip__name">附件已删除</span>
      </span>
    )
  }

  const url = api.attachmentContentUrl(meta.id)
  const isImage = (meta.mime_type || '').toLowerCase().startsWith('image/')
  const sizeText = humanSize(meta.size_bytes)
  const titleText = sizeText
    ? `${meta.filename} · ${meta.mime_type} · ${sizeText}`
    : `${meta.filename} · ${meta.mime_type}`

  if (isImage) {
    return (
      <a
        className="attachment-chip attachment-chip--image"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title={titleText}
      >
        <img
          src={url}
          alt={meta.filename}
          className="attachment-chip__thumb"
          loading="lazy"
        />
      </a>
    )
  }
  return (
    <a
      className="attachment-chip"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      download={meta.filename}
      title={titleText}
    >
      <span className="attachment-chip__icon">📎</span>
      <span className="attachment-chip__name">{meta.filename}</span>
      {sizeText && (
        <span className="attachment-chip__size">{sizeText}</span>
      )}
    </a>
  )
}

export interface AttachmentListProps {
  ids?: string[] | null
}

export function AttachmentList({ ids }: AttachmentListProps) {
  if (!ids || ids.length === 0) return null
  return (
    <div className="attachment-chip-list">
      {ids.map((id) => (
        <AttachmentChip key={id} id={id} />
      ))}
    </div>
  )
}
