# 记忆中心审查图

> 生成日期: 2026-05-03  
> 用途: 本次“记忆系统前端体验重置 + 记忆系统设置入口”变更的审核材料源文件。

```mermaid
flowchart LR
  Sidebar[侧边栏导航] --> MemoryGroup[记忆中心分组]
  MemoryGroup --> ManageEntry[记忆管理入口\nPanel: memory]
  MemoryGroup --> SettingsEntry[记忆设置入口\nPanel: memory-settings]

  ManageEntry --> MemoryCenter[MemoryPanel / 记忆中心]
  SettingsEntry --> MemoryCenter

  subgraph UI[Memory Center 页面结构]
    Overview[概览\n统计/后端状态/自动记忆]
    List[记忆管理\n筛选/列表/详情/编辑/删除]
    Recall[召回测试\n搜索 + 评分解释]
    Create[创建记忆\n内容/类型/重要性/标签/来源]
    Settings[系统设置\n反思/召回/持久化/巩固遗忘]
  end

  MemoryCenter --> Overview
  MemoryCenter --> List
  MemoryCenter --> Recall
  MemoryCenter --> Create
  MemoryCenter --> Settings

  subgraph API[后端 API 流向]
    StatsAPI[GET /api/memory/stats]
    ListAPI[GET /api/memory/list]
    SearchAPI[POST /api/memory/search]
    CreateAPI[POST /api/memory/create]
    UpdateAPI[PUT /api/memory/{id}]
    DeleteAPI[DELETE /api/memory/{id}]
    SettingsGet[GET /api/memory/settings]
    SettingsPost[POST /api/memory/settings]
    Consolidate[POST /api/memory/consolidate]
    Forget[POST /api/memory/forget]
  end

  Overview --> StatsAPI
  Overview --> SettingsGet
  List --> ListAPI
  List --> UpdateAPI
  List --> DeleteAPI
  Recall --> SearchAPI
  Create --> CreateAPI
  Settings --> SettingsGet
  Settings --> SettingsPost
  MemoryCenter --> Consolidate
  MemoryCenter --> Forget

  subgraph State[关键状态]
    Loading[loading\n统计/列表/设置/召回]
    Error[error alert\n可关闭]
    Empty[empty state\n无记忆/无召回]
    Confirm[危险确认\n删除/遗忘/巩固]
    Dirty[settings/edit form\n校验后保存]
  end

  MemoryCenter --> Loading
  MemoryCenter --> Error
  MemoryCenter --> Empty
  DeleteAPI --> Confirm
  Forget --> Confirm
  Consolidate --> Confirm
  SettingsPost --> Dirty
```
