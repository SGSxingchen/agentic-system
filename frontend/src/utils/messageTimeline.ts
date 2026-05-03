import type { Message, MessageTimelineItem, ToolCallRecord } from '../types'

export function sortTimelineItems(items: MessageTimelineItem[]): MessageTimelineItem[] {
  return [...items].sort((a, b) => {
    const byOrder = a.order - b.order
    if (byOrder !== 0) return byOrder
    return a.id.localeCompare(b.id)
  })
}

export function appendTextTimelineItem(
  items: MessageTimelineItem[],
  content: string,
  order: number,
): MessageTimelineItem[] {
  if (!content) return items

  const next = [...items]
  const last = next[next.length - 1]
  if (last?.kind === 'text') {
    next[next.length - 1] = {
      ...last,
      content: `${last.content || ''}${content}`,
    }
    return next
  }

  next.push({
    id: `text-${order}`,
    kind: 'text',
    order,
    content,
  })
  return next
}

export function upsertToolCallTimelineItem(
  items: MessageTimelineItem[],
  call: ToolCallRecord,
  order: number,
): MessageTimelineItem[] {
  const existingIndex = items.findIndex(
    (item) => item.kind === 'tool_call' && item.toolCall?.id === call.id,
  )
  if (existingIndex >= 0) {
    const next = [...items]
    const existing = next[existingIndex]
    next[existingIndex] = {
      ...existing,
      toolCall: {
        ...existing.toolCall,
        ...call,
      },
    }
    return next
  }

  return [
    ...items,
    {
      id: `tool-${call.id || order}`,
      kind: 'tool_call',
      order,
      toolCall: call,
    },
  ]
}

export function updateToolResultTimelineItem(
  items: MessageTimelineItem[],
  callId: string,
  patch: Partial<ToolCallRecord>,
  order: number,
): MessageTimelineItem[] {
  const existingIndex = items.findIndex(
    (item) => item.kind === 'tool_call' && item.toolCall?.id === callId,
  )

  if (existingIndex >= 0) {
    const next = [...items]
    const existing = next[existingIndex]
    next[existingIndex] = {
      ...existing,
      toolCall: {
        id: callId,
        tool: patch.tool || existing.toolCall?.tool || 'unknown',
        status: patch.status || existing.toolCall?.status || 'success',
        ...existing.toolCall,
        ...patch,
      },
    }
    return next
  }

  return [
    ...items,
    {
      id: `tool-${callId || order}`,
      kind: 'tool_call',
      order,
      toolCall: {
        id: callId || `tool-result-${order}`,
        tool: patch.tool || 'unknown',
        status: patch.status || 'success',
        ...patch,
      },
    },
  ]
}

export function getMessageTimeline(message: Message): MessageTimelineItem[] {
  if (message.timeline && message.timeline.length > 0) {
    return sortTimelineItems(message.timeline)
  }

  const fallback: MessageTimelineItem[] = []
  if (message.content) {
    fallback.push({
      id: `${message.id}-content`,
      kind: 'text',
      order: 0,
      content: message.content,
    })
  }
  if (message.toolCalls?.length) {
    message.toolCalls.forEach((call, index) => {
      fallback.push({
        id: `${message.id}-tool-${call.id || index}`,
        kind: 'tool_call',
        order: index + 1,
        toolCall: call,
      })
    })
  }
  return fallback
}
