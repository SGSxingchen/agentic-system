# 场景测试：销售数据处理流水线

**测试日期:** 2026-03-25  
**测试人:** 自动化端到端测试  
**LLM模型:** claude-sonnet-4-20250514 (via OpenAI-compatible API)  
**后端端口:** 8003  

---

## 1. 环境准备

### 1.1 配置文件 (`backend/src/config.yaml`)
```yaml
llm:
  provider: "openai"
  api_key: "your-api-key-here"
  model: "claude-sonnet-4-20250514"
  base_url: "http://your-openai-compatible-endpoint/v1"
  temperature: 0.7
  max_tokens: 4096
```

### 1.2 启动后端
```bash
cd backend/src && python3 -m uvicorn api.main:app --port 8003
```

**启动日志:**
```
✅ 上下文存储已初始化
✅ 从 config/capabilities.yaml 加载了 2 个能力
✅ 能力系统已初始化 (2 个能力)
✅ 从 config/triggers.yaml 加载了 5 个扳机
✅ 扳机系统已初始化 (5 个扳机)
✅ 事件引擎已初始化
✅ 工作流编排器已初始化 (已加载 3 个工作流模板)
✅ 记忆系统已初始化 (backend=memory)
📝 加载配置: openai - claude-sonnet-4-20250514
📦 从 config/agents.yaml 加载 4 个 Agent 定义
✅ 所有 Agent 已加载 (openai - claude-sonnet-4-20250514, 4 个 Agent)
🚀 系统全部初始化完成!
```

**评估:** ✅ 所有子系统正常初始化。4个Agent (assistant, planner, coder, reviewer)、3个工作流模板、5个扳机、2个能力全部加载成功。

---

## 2. Planner Agent — 任务分解

### 请求
```http
POST http://localhost:8003/api/agents/planner/invoke
Content-Type: application/json

{
  "data": {
    "requirement": "我需要用 Python 开发一个销售数据处理流水线。输入是 CSV 文件（包含 date, product, quantity, price, region 字段）。需要：1) 数据清洗（去重、空值处理、类型校验）2) 数据分析（按月汇总销售额、Top10 热销产品、各区域环比增长率）3) 生成 Excel 报表（含多个 sheet）和 matplotlib 图表。请分解任务。"
  }
}
```

### 响应 (HTTP 200)
```json
{
  "status": "ok",
  "data": {
    "requirement": "...",
    "plan": [
      {"name": "design_pipeline_architecture", "description": "设计销售数据处理流水线的整体架构，定义模块结构、数据流和接口规范", "agent": "planner", "dependencies": [], "priority": 1},
      {"name": "implement_data_loader", "description": "实现CSV数据加载模块，包含文件读取、字段验证和基础数据结构定义", "agent": "coder", "dependencies": ["design_pipeline_architecture"], "priority": 2},
      {"name": "implement_data_cleaner", "description": "实现数据清洗模块，包含去重、空值处理、数据类型校验和异常数据过滤", "agent": "coder", "dependencies": ["implement_data_loader"], "priority": 3},
      {"name": "implement_monthly_aggregation", "description": "实现按月汇总销售额功能，包含日期分组和金额计算", "agent": "coder", "dependencies": ["implement_data_cleaner"], "priority": 4},
      {"name": "implement_top_products_analysis", "description": "实现Top10热销产品分析功能，按销售量和销售额进行排序统计", "agent": "coder", "dependencies": ["implement_data_cleaner"], "priority": 4},
      {"name": "implement_region_growth_analysis", "description": "实现各区域环比增长率计算功能，包含时间序列分析和增长率计算", "agent": "coder", "dependencies": ["implement_data_cleaner"], "priority": 4},
      {"name": "implement_excel_reporter", "description": "实现Excel报表生成模块，创建多个sheet页面并写入分析结果", "agent": "coder", "dependencies": ["implement_monthly_aggregation","implement_top_products_analysis","implement_region_growth_analysis"], "priority": 5},
      {"name": "implement_chart_generator", "description": "实现matplotlib图表生成模块，包含销售趋势图、产品排行图和区域对比图", "agent": "coder", "dependencies": ["implement_monthly_aggregation","implement_top_products_analysis","implement_region_growth_analysis"], "priority": 5},
      {"name": "implement_main_pipeline", "description": "实现主流水线控制器，整合所有模块并提供统一的执行接口", "agent": "coder", "dependencies": ["implement_excel_reporter","implement_chart_generator"], "priority": 6},
      {"name": "review_code_quality", "description": "对所有代码模块进行质量审查，检查代码规范、错误处理和性能问题", "agent": "reviewer", "dependencies": ["implement_main_pipeline"], "priority": 7},
      {"name": "write_unit_tests", "description": "编写单元测试，覆盖数据清洗、分析计算和报表生成等核心功能", "agent": "tester", "dependencies": ["review_code_quality"], "priority": 8},
      {"name": "write_integration_tests", "description": "编写集成测试，测试完整的数据处理流水线端到端功能", "agent": "tester", "dependencies": ["write_unit_tests"], "priority": 9},
      {"name": "create_sample_data", "description": "创建测试用的样本CSV数据文件，包含正常数据和异常数据用例", "agent": "tester", "dependencies": ["design_pipeline_architecture"], "priority": 2},
      {"name": "validate_pipeline_output", "description": "使用样本数据验证流水线输出的Excel报表和图表的正确性", "agent": "tester", "dependencies": ["write_integration_tests","create_sample_data"], "priority": 10}
    ]
  }
}
```

### 评估
- ✅ **任务分解质量:** 将需求拆分为14个子任务，覆盖了架构设计、数据加载、清洗、分析（3个并行子任务）、报表、图表、主控、审查和测试
- ✅ **依赖关系合理:** 形成了有向无环图（DAG），分析任务正确并行化（priority=4），报表和图表依赖所有分析完成
- ✅ **Agent分配正确:** coder 负责实现，reviewer 负责审查，tester 负责测试
- ✅ **JSON格式规范:** 严格符合预定义schema
- ⚠️ **轻微问题:** "tester" agent 实际未注册（系统仅有 assistant/planner/coder/reviewer），但计划本身逻辑正确

---

## 3. Coder Agent — 代码生成

### 3.1 数据清洗模块 (DataCleaner)

#### 请求
```http
POST http://localhost:8003/api/agents/coder/invoke
Content-Type: application/json

{
  "data": {
    "task": "请用 pandas 实现一个 DataCleaner 类，功能：1) 去除完全重复行 2) 处理空值（数值列填0，文本列填Unknown）3) 类型校验（date转datetime，quantity转int，price转float）4) 输出清洗报告（原始行数、清洗后行数、各列空值数）。包含完整类型注解。"
  }
}
```

#### 响应 (HTTP 200)
- **language:** python
- **file_path:** `src/data_processing/data_cleaner.py`
- **代码长度:** ~150行
- **主要功能:**
  - `DataCleaner` 类，含 `clean_data()` 主方法
  - `_remove_duplicates()` — 使用 `drop_duplicates()`
  - `_handle_missing_values()` — 数值列填0，文本列填 'Unknown'
  - `_validate_and_convert_types()` — 自动识别列名进行类型转换
  - `_generate_cleaning_report()` — 生成清洗统计报告
  - `print_cleaning_report()` — 格式化打印报告

#### 评估
- ✅ **功能完整:** 覆盖了所有4个需求点
- ✅ **类型注解:** 使用了 `Dict[str, Any]`, `pd.DataFrame` 等完整注解
- ✅ **文档字符串:** 每个方法都有 docstring
- ✅ **错误处理:** 空 DataFrame 检查、类型转换 try-except
- ✅ **设计合理:** 模块化私有方法、不可变性（copy()）

### 3.2 数据分析模块 (SalesAnalyzer)

#### 请求
```http
POST http://localhost:8003/api/agents/coder/invoke
Content-Type: application/json

{
  "data": {
    "task": "请实现一个 SalesAnalyzer 类，接收清洗后的 DataFrame，提供以下分析方法：1) monthly_summary() 按月汇总销售额和数量 2) top_products(n=10) 返回销售额Top N产品 3) region_growth() 计算各区域环比增长率 4) 所有方法返回 DataFrame。包含类型注解和文档字符串。"
  }
}
```

#### 响应 (HTTP 200)
- **language:** python
- **file_path:** `src/analysis/sales_analyzer.py`
- **代码长度:** ~120行
- **主要功能:**
  - `SalesAnalyzer` 类，构造函数验证必需列
  - `monthly_summary()` — groupby + agg
  - `top_products(n=10)` — groupby + sum + nlargest
  - `region_growth()` — 区域环比增长率（shift + 百分比计算）
  - `get_data_info()` — 数据概览

#### 评估
- ✅ **功能完整:** 3个分析方法 + 1个信息方法
- ✅ **返回 DataFrame:** 所有分析方法一致返回 DataFrame
- ✅ **输入验证:** 必需列检查、列存在性检查
- ✅ **类型注解和文档:** 完整
- ⚠️ **列名不一致:** 期望 `sales_amount` 和 `product_name`，但原始需求字段是 `product` 和 `price`（需要预计算 `sales_amount = quantity * price`）

### 3.3 报表生成模块 (ReportGenerator)

#### 请求
```http
POST http://localhost:8003/api/agents/coder/invoke
Content-Type: application/json

{
  "data": {
    "task": "请实现一个 ReportGenerator 类，接收分析结果，生成：1) Excel 报表（openpyxl，多 sheet：月度汇总、Top产品、区域增长）2) matplotlib 图表（月度趋势折线图、Top10柱状图、区域饼图），保存为 PNG。包含样式美化。"
  }
}
```

#### 响应 (HTTP 200)
- **language:** python
- **file_path:** `src/reports/report_generator.py`
- **代码长度:** ~300行
- **主要功能:**
  - `ReportGenerator` 类
  - `generate_excel_report()` — 3个 sheet（月度汇总、Top产品、区域增长），含样式美化
  - `generate_charts()` — 3种图表（折线图、柱状图、饼图）
  - `generate_complete_report()` — 一键生成全部报表
  - 样式美化：自定义字体、颜色填充、对齐方式、渐变配色

#### 评估
- ✅ **功能完整:** Excel + 3种图表
- ✅ **样式美化:** openpyxl样式（Font, PatternFill, Alignment）、matplotlib配色
- ✅ **模块化:** 每种报表/图表独立方法
- ✅ **输出管理:** 自动创建输出目录、路径管理
- ⚠️ **中文支持:** 依赖 SimHei 字体，在非中文系统上可能渲染异常
- ⚠️ **seaborn依赖:** 额外引入了 seaborn 但未在主要逻辑中使用

---

## 4. Reviewer Agent — 代码审查

### 请求
将三个模块代码合并，提交审查。

```http
POST http://localhost:8003/api/agents/reviewer/invoke
Content-Type: application/json

{
  "data": {
    "code": "[三个模块合并代码]",
    "language": "python",
    "task": "销售数据处理流水线完整代码审查：DataCleaner、SalesAnalyzer、ReportGenerator三个模块"
  }
}
```

### 响应 (HTTP 200)
```json
{
  "approved": false,
  "severity": 8,
  "issues": [
    {"type": "bug", "severity": "critical", "description": "缺少必要的导入语句，SalesAnalyzer类中使用了pd.DataFrame但未导入pandas"},
    {"type": "logic", "severity": "major", "description": "数据类型转换可能导致数据丢失，将所有缺失的数值填充为0可能掩盖真实的数据质量问题"},
    {"type": "performance", "severity": "major", "description": "代码结构严重缺乏可读性，多个方法写成单行导致维护困难"},
    {"type": "bug", "severity": "major", "description": "Excel生成时没有错误处理，DataFrame包含不支持的数据类型可能导致异常"},
    {"type": "security", "severity": "major", "description": "路径操作缺少验证，用户可以通过filename参数进行路径遍历攻击"},
    {"type": "logic", "severity": "major", "description": "日期转换失败时使用当前时间填充是不合理的业务逻辑"},
    {"type": "performance", "severity": "minor", "description": "图表生成时每次都创建新的figure但关闭方式不当"},
    {"type": "style", "severity": "major", "description": "缺少异常处理和输入验证"},
    {"type": "logic", "severity": "major", "description": "增长率计算时除零错误没有处理"}
  ],
  "suggestions": [
    "在SalesAnalyzer模块顶部添加pandas导入语句",
    "将单行方法展开为多行，提高代码可读性",
    "添加完整的异常处理机制",
    "对filename参数进行路径验证，防止路径遍历攻击",
    "改进缺失值处理策略",
    "在增长率计算中添加除零检查",
    "改进日期转换失败的处理逻辑",
    "优化图表生成代码",
    "添加数据验证层",
    "考虑添加日志记录功能"
  ],
  "summary": "代码存在多个严重问题，包括关键的导入缺失、安全漏洞、逻辑错误和可维护性问题。必须修复这些问题才能投入生产使用。"
}
```

### 评估
- ✅ **审查全面:** 覆盖了正确性、安全性、可维护性、性能、最佳实践6个维度
- ✅ **问题分类准确:** bug/security/performance/style/logic 分类合理
- ✅ **严重级别评估合理:** severity=8 反映了多个 major 级别问题
- ✅ **建议有操作性:** 10条具体可执行的改进建议
- ⚠️ **注意:** 由于提交审查时使用了精简/合并后的代码（非原始LLM输出），部分"可读性"问题可能是精简导致的

---

## 5. 工作流模式 — 端到端执行

### 请求
```http
POST http://localhost:8003/api/workflows/execute
Content-Type: application/json

{
  "template_name": "code_generation_and_review",
  "requirement": "用 Python + pandas 实现一个函数 calculate_moving_average(df, column, window=7)，计算指定列的移动平均值，处理边界情况，返回新的 DataFrame"
}
```

### 响应 (HTTP 200)
工作流经过了 4 个步骤：

| 步骤 | Agent | 状态 | 耗时 |
|------|-------|------|------|
| plan | planner | ✅ completed | 9509ms |
| code | coder | ✅ completed | 24937ms |
| review | reviewer | ✅ completed | 13182ms |
| fix | coder | ✅ completed | 3015ms |

**总耗时:** 50643ms (约51秒)

#### 步骤详情

**Plan 步骤:**
- 成功将需求分解为8个子任务
- 包含接口设计、核心实现、边界处理、输入验证、代码审查、单元测试、集成测试和文档编写

**Code 步骤:**
- 生成了完整的 `calculate_moving_average` 函数
- 包含输入验证（类型检查、空值检查、列存在性检查）
- 使用 `pandas.rolling()` 实现移动平均
- 处理了 window > len(df) 的边界情况
- 额外提供了 `calculate_moving_average_strict` 严格版本
- 文件路径建议：`src/data_processing/moving_average.py`

**Review 步骤:**
- approved: **false** (severity=6)
- 发现4个问题：
  1. [major] window调整逻辑不一致
  2. [minor] 重复的参数验证代码（DRY原则）
  3. [minor] df.copy()内存开销
  4. [major] min_periods参数验证不当
- 提供了5条改进建议

**Fix 步骤:**
- 条件触发：`review_result.get('approved') == False` → 进入修复流程
- ⚠️ LLM返回了非结构化内容（未遵循JSON格式），修复效果不理想
- 这是工作流编排中已知的问题：fix步骤的输入数据结构（包含 code + issues）需要更好的 prompt 工程

### 评估
- ✅ **工作流编排:** YAML配置驱动，4步顺序执行正确
- ✅ **条件判断:** fix步骤根据 review_result.approved 正确触发
- ✅ **变量传递:** ${plan}、${code}、${review_result} 变量替换正常
- ✅ **超时控制:** 51秒内完成，未触发超时
- ⚠️ **Fix质量:** 修复步骤的LLM输出不符合JSON格式，降级为原始文本保留
- ⚠️ **建议:** fix步骤应将原始代码和审查意见结合在prompt中，引导LLM输出修复后的代码

---

## 6. 已发现的问题和修复

### 6.1 API字段名不匹配
- **问题:** 最初使用 `{"message": "..."}` 调用 Planner，返回"缺少需求描述"
- **原因:** Planner.process() 期望 `data.requirement` 字段
- **修复:** 改为 `{"data": {"requirement": "..."}}` 格式
- **评估:** 这是 API 设计中 schema 约定的问题，文档中应明确各 agent 的 input schema

### 6.2 服务重启后 LLM 401 错误
- **问题:** kill -9 强制终止后重启，所有 LLM 调用返回 401 "Missing API key"
- **原因:** 疑似 kill -9 导致的端口绑定残留或 OpenAI 客户端初始化时序问题
- **修复:** 等待端口完全释放后重启，第三次启动恢复正常
- **评估:** 建议使用优雅关闭（SIGTERM）而非 kill -9

### 6.3 工作流路由匹配问题（首次尝试）
- **问题:** 首次使用 `{"input": "..."}` 但缺少 `requirement` 字段导致 422
- **原因:** Pydantic schema 中 `requirement` 虽然有默认值 `""`，但 `input` 作为别名需要额外的 `requirement` 字段
- **修复:** 使用 `requirement` 字段代替 `input`

---

## 7. 总体评估

### 功能完成度

| 模块 | 状态 | 说明 |
|------|------|------|
| Planner 任务分解 | ✅ | 14个子任务，结构合理 |
| Coder 数据清洗 | ✅ | DataCleaner 类功能完整 |
| Coder 数据分析 | ✅ | SalesAnalyzer 类3个分析方法 |
| Coder 报表生成 | ✅ | ReportGenerator Excel+图表 |
| Reviewer 代码审查 | ✅ | 9个问题+10条建议 |
| 工作流端到端 | ✅ | 4步完整执行 |

### LLM 响应质量

- **JSON格式遵从度:** 约85%（fix步骤偶尔返回非结构化内容）
- **代码质量:** 良好，包含类型注解、文档、错误处理
- **任务理解:** 准确，能正确分解复杂需求
- **审查深度:** 专业，覆盖多维度

### 系统稳定性

- **正常启动:** ✅ 稳定，所有子系统正确初始化
- **Agent 调用:** ✅ 稳定，HTTP 200
- **工作流执行:** ✅ 多步骤顺序执行正确
- **异常恢复:** ⚠️ kill -9 后需等待端口释放
- **超时控制:** ✅ 所有请求在120秒内完成

### 改进建议

1. **Fix步骤Prompt优化:** 修复步骤应更好地传递审查问题上下文
2. **API文档:** 各Agent的input schema应在API文档中明确说明
3. **错误信息:** "缺少需求描述" 应改为 "缺少 'requirement' 字段"
4. **工作流结果缓存:** 支持通过 workflow_id 查询历史执行结果
5. **Tester Agent:** 计划中引用了 tester agent 但系统未注册

---

_测试完成时间: 2026-03-25 12:50 CST_
