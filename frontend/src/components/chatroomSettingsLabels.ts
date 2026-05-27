// Localized labels & hints for ChatroomPanel SettingsForm.
// Backend keys (auto_host, host_agent, recent_n, ...) stay unchanged;
// only the UI display strings are localized here.
//
// B5 — 2026-05-28 自由化与 UI 增强 plan, Task 1.

export interface SettingLabel {
  label: string
  hint: string
}

export const SETTING_LABELS: Record<string, SettingLabel> = {
  auto_host: {
    label: '自动主持人',
    hint: '没被 @ 时，自动让主持 Agent 接话',
  },
  host_agent: {
    label: '主持 Agent',
    hint: '自动接话时由谁说，必须是房间成员',
  },
  recent_n: {
    label: '上下文条数',
    hint: '给 Agent 看的最近 N 条消息',
  },
  summary_threshold_m: {
    label: '摘要触发阈值',
    hint: '早于上下文窗口的消息累计达 M 条时自动摘要',
  },
  max_relay_depth: {
    label: '最大接力层数',
    hint: '一条消息触发的连锁 @ 最多几层，避免死循环',
  },
  max_members: {
    label: '房间成员上限',
    hint: '',
  },
  allow_agent_invite: {
    label: '允许 Agent 互相拉人',
    hint: '关闭后只有用户能拉人',
  },
  auto_memory: {
    label: '自动记忆',
    hint: 'Spec 1 A1：自动检索长期记忆并在消息生成后反思沉淀',
  },
  allow_subagent_dispatch: {
    label: '允许私下派子 Agent',
    hint: 'Spec 2 A21：默认关。开启后房间成员可调 dispatch_agent',
  },
}

export function getSettingLabel(key: string): SettingLabel {
  const entry = SETTING_LABELS[key]
  if (entry) return entry
  return { label: key, hint: '' }
}
