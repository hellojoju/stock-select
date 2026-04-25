# 前端重设计梳理方案

Last updated: 2026-04-25

## 目标

当前前端已经把主要功能接起来了：工作台、复盘、策略进化、数据与记忆都能展示。但整体体验更像“后端接口的面板集合”，还没有形成一个适合每日使用的选股研究终端。

下一轮前端重设计的目标不是做营销页，也不是做炫酷大屏，而是做一个高密度、可审计、适合反复使用的个人研究工作台：

- 让用户一眼知道今天系统处于什么状态。
- 让用户能快速判断：今天推荐什么、为什么推荐、数据是否可靠。
- 让用户能从单只股票一路追溯到证据、复盘、错误、优化信号。
- 让用户能看懂策略为什么进化、是否值得推广、是否需要回滚。
- 让 demo/live、数据缺失、LLM 是否参与、信号是否被消费这些风险状态变得非常明确。

## 当前前端问题

### 1. 信息架构不贴合每日工作流

现状：

- `今日工作台` 同时放推荐、单股复盘、复盘摘要、策略表现。
- `复盘分析` 再次放策略复盘、单股复盘、LLM 复盘、盲点复盘。
- `策略进化` 放 Challenger、候选评分、候审信号。
- `数据与记忆` 放数据质量、证据覆盖、记忆检索、调度监控。

问题：

- 页面之间职责有重叠，用户不知道应该在哪个页面完成完整任务。
- 单股复盘同时出现在工作台和复盘页，容易造成状态混乱。
- 候选评分出现在策略进化页，但它实际更属于“选股研究/推荐解释”。
- 数据质量和证据覆盖是全局风险状态，不应该只藏在数据页。

### 2. 页面层级扁平，主次关系不清

现状大量使用同一种 `Panel` 卡片，视觉重量接近。

问题：

- “今日是否可用”与“细节证据列表”视觉权重相近。
- 重要告警、数据缺失、进化风险没有统一的醒目区域。
- 用户要自己拼接信息链路：推荐 -> 因子 -> 证据 -> 复盘 -> 信号 -> 进化。

### 3. 交互模式偏静态报表

现状：

- 推荐列表点击后在下方显示单股复盘。
- 策略列表点击后替换一个面板。
- 进化 dry-run/propose/promotion/rollback 按钮直接暴露。

问题：

- 缺少 master-detail 的连续阅读体验。
- 关键动作缺少确认、预览、影响范围说明。
- 缺少“从一个股票/策略进入完整详情”的稳定路径。
- 用户做完一个动作后，系统状态变化不够清晰。

### 4. 视觉语言不够适合金融研究工具

现有风格偏复古纸张和粗边框，个性很强，但和这个产品的核心使用场景不完全匹配。

问题：

- 粗黑边框和大阴影让密集数据显得拥挤。
- Georgia/Songti 的正文风格更像文章，不像高频操作的研究终端。
- 卡片过重，表格和证据列表可读性受到影响。
- 红绿、金色、茶色混合后，风险状态不够系统化。

建议方向：

- 采用“证券研究终端”风格：克制、高密度、清晰、可审计。
- 背景保持浅色，减少装饰性网格和重阴影。
- 用色只服务状态：红=风险/亏损，绿=收益/通过，琥珀=警告/缺失，蓝灰=信息，青色=当前选中。
- 数字使用等宽或 tabular 风格；中文使用清晰 UI 字体。

## 推荐信息架构

建议从当前 4 个一级入口调整为 5 个一级入口：

1. **今日工作台**
2. **选股研究**
3. **复盘中心**
4. **策略进化**
5. **数据与运行**

原 `数据与记忆` 改名为 `数据与运行`，记忆检索放在其中，也可以在复盘页作为侧栏入口出现。

## 全局 Shell 设计

### 左侧导航

左侧只保留一级页面：

- 今日工作台
- 选股研究
- 复盘中心
- 策略进化
- 数据与运行

左侧底部展示：

- `DEMO / LIVE`
- 模拟盘资金状态
- LLM 状态：`OFF / READY / LIMITED / ERROR`
- 数据最近更新时间

### 顶部全局命令栏

每个页面顶部都应该有一致的命令栏：

- 日期选择器。
- 最近交易日快捷按钮。
- 全局股票搜索。
- 数据模式标签：`LIVE` / `DEMO`。
- 数据健康摘要：行情、因子、证据、LLM。
- 当前 pipeline 状态。

推荐视觉结构：

```text
[日期 2024-04-22] [最近交易日] [股票搜索 代码/名称]
LIVE · 行情 OK · 因子 Partial · 证据 Sparse · LLM Off
```

### 全局状态条

所有页面顶部下方放一条窄状态条，用于显示影响判断的系统风险：

- `行情真实，基本面/事件部分缺失`
- `BaoStock 成功，AKShare 校验失败`
- `市场预期源未配置`
- `LLM 复盘未启用`
- `存在 12 条 data_quality warning`

这条状态条必须是全局的，不能只在数据页看到。

## 页面 1：今日工作台

### 页面定位

今日工作台只回答四个问题：

1. 今天系统能不能用？
2. 今天推荐什么？
3. 模拟盘当前发生了什么？
4. 今天最需要我人工关注什么？

它不应该承载完整复盘细节，也不应该承载完整策略进化。

### 推荐布局

```text
顶部：日期 + 模式 + 数据健康 + 运行状态

第一行：今日概览
[市场环境] [推荐数] [模拟成交] [数据健康] [待处理信号]

主体左侧：推荐队列
- 股票代码/名称
- gene
- action
- confidence
- position
- 技术/基本面/事件/行业/风险五维小条
- 缺失证据图标
- 预计买入/卖出规则

主体右侧：今日状态
- Pipeline 时间线
- 数据质量告警
- 复盘摘要
- 人工待办

底部：模拟盘持仓/成交
```

### 推荐队列交互

点击推荐股票，不在当前页展开长复盘，而是打开右侧抽屉或跳转到单股详情：

- 快速查看：右侧抽屉。
- 完整查看：进入 `复盘中心 / 单股复盘`。

右侧抽屉内容只放摘要：

- 推荐理由一句话。
- 五维分数。
- 关键证据 3 条。
- 关键风险 3 条。
- `查看完整复盘` 按钮。

### 工作台不应该展示的内容

- 完整 evidence table。
- 大量 review errors。
- LLM 详细归因。
- Challenger 参数 diff。

这些都应该进入专门页面。

## 页面 2：选股研究

### 页面定位

选股研究用于解释“为什么这些股票进入候选池、为什么最后推荐或剔除”。

这是目前缺失最明显的页面。现在 `candidate_scores` 放在策略进化页，但实际它属于选股研究。

### 页面结构

```text
左侧：候选池筛选
- gene
- 行业
- action
- 是否推荐
- 是否缺基本面
- 是否有负面风险
- confidence 区间

中间：候选池表格
- rank
- 股票
- 行业
- gene
- total score
- technical
- fundamental
- event
- sector
- risk penalty
- missing fields
- decision: BUY/WATCH/REJECT

右侧：候选详情
- packet_json 可读化
- 数据来源
- 缺失字段
- 触发的硬过滤
- 推荐或剔除原因
```

### 候选池表格设计

表格是这个页面的核心，不应该用卡片堆叠。

建议列：

- `Rank`
- `Stock`
- `Industry`
- `Gene`
- `Decision`
- `Total`
- `Technical`
- `Fundamental`
- `Event`
- `Sector`
- `Risk`
- `Missing`
- `Source`

交互：

- 点击列头排序。
- 点击股票打开右侧详情。
- 点击 gene 过滤同策略。
- 点击 missing badge 过滤同类缺失。
- 支持只看推荐、只看 WATCH、只看被风险剔除。

### 候选详情

右侧详情应展示“选股时可见信息”，而不是复盘后信息：

- `input_snapshot_hash`
- 可见行情窗口。
- 五维评分来源。
- 缺失字段。
- 硬过滤结果。
- 风险规则。
- `invalid_if`
- `sell_rules`

这里必须明确写：只展示 `target_date` 之前可见的数据。

## 页面 3：复盘中心

### 页面定位

复盘中心回答：

1. 早盘策略整体对不对？
2. 单只股票为什么对/错？
3. 漏掉了什么？
4. 哪些错误可以转成优化信号？
5. LLM 是否提出了额外归因，是否可信？

### 页面内导航

建议使用二级 tabs：

- 策略整体复盘
- 单股复盘
- 盲点复盘
- LLM 复盘
- 优化信号

### 策略整体复盘

布局：

```text
左侧：gene 列表
- gene id
- 推荐数
- 胜率
- 平均收益
- 最大回撤
- open signals

中间：策略复盘主面板
- 参数快照
- 候选池数量
- 推荐组合
- 收益/胜率/相对收益
- factor edge
- evidence edge

右侧：策略问题
- top errors
- missed blindspots
- generated optimization signals
- evidence coverage
```

重点：

- `factor edge` 和 `evidence edge` 要分开，不要混成一个小 grid。
- 策略问题要按“可优化 / 数据缺失 / 事后事件 / 不惩罚”分组。

### 单股复盘

布局：

```text
顶部：股票身份条
股票代码 名称 行业 当日收益 相对收益 是否盲点

左侧：该股票当天所有 decision
- gene
- action
- confidence
- position
- verdict
- return

中间：复盘正文
- 判断对错
- 买入执行
- 收益结果
- 因子检查
- 错误归因

右侧：证据时间线
- 盘前可见
- 收盘观察
- 事后事件
```

关键交互：

- 不要默认展开所有 decision。
- 点击某个 decision，中间内容切换。
- 证据按时间线展示，而不是只按表格堆叠。
- 证据必须标记 `PREOPEN_VISIBLE`、`POSTCLOSE_OBSERVED`、`POSTDECISION_EVENT`。
- `POSTDECISION_EVENT` 要明确显示“不作为早盘策略惩罚”。

### 盲点复盘

盲点页不只是涨幅榜列表，而是应该回答：

- 它为什么涨？
- 盘前是否有可见证据？
- 它为什么没进候选池？
- 是策略边界问题，还是数据缺失，还是硬过滤？
- 是否应该生成优化信号？

推荐分组：

- `可学习盲点`：盘前有证据，系统漏掉。
- `不可惩罚盲点`：事件发生在盘后或盘中。
- `正确避开`：涨幅高但风险过大、流动性差或数据异常。
- `数据缺失`：关键证据源未接入。

### LLM 复盘

LLM 复盘必须作为“解释增强层”，不能和确定性复盘混在一起。

展示原则：

- 每条 LLM claim 必须显示证据引用。
- `EXTRACTED`、`INFERRED`、`AMBIGUOUS` 用不同标签。
- LLM 建议的 signal 默认是 `candidate`，需要人工接受或拒绝。
- 显示 token/cost。
- 显示 schema 校验状态。

## 页面 4：策略进化

### 页面定位

策略进化页只回答：

1. 哪些 optimization signals 通过了规则？
2. 系统准备怎么改参数？
3. 新旧策略表现如何对比？
4. 是否推广或回滚？

它不应该展示候选评分。候选评分应迁移到 `选股研究`。

### 推荐布局

```text
第一行：进化安全状态
[未消费信号] [可提案信号组] [观察中 Challenger] [可推广] [已回滚]

左侧：信号池
- signal type
- gene
- param
- direction
- strength
- sample count
- date span
- avg confidence
- status

中间：Challenger 对比
- parent gene
- child gene
- 参数 diff
- 生成原因
- consumed signal ids
- evidence ids
- 状态 observing/promoted/rolled_back

右侧：操作与审计
- Dry-run
- Propose
- Promote
- Rollback
- evolution event history
```

### 关键交互

`Dry-run`：

- 只预览参数变化。
- 不创建 gene。
- 不消费 signal。
- 显示为什么某些信号不满足条件。

`Propose`：

- 弹出确认。
- 显示将消费哪些 signal。
- 显示参数变化是否超过 5%。
- 创建 Challenger。

`Promote`：

- 必须显示观察期表现。
- 必须显示 parent/child 对比。
- 必须确认不会删除历史。

`Rollback`：

- 必须显示回滚对象。
- 必须确认保留历史 outcomes/reviews/signals。

## 页面 5：数据与运行

### 页面定位

数据与运行页是系统健康中心，回答：

1. 数据源是否正常？
2. 哪些数据是真的，哪些缺失？
3. pipeline 哪一步失败？
4. 记忆和历史经验能不能检索？

### 页面结构

```text
顶部：数据模式和最近同步

左侧：数据质量
- 行情源状态
- 双源价格校验
- 因子覆盖
- 证据覆盖
- skipped/error source

中间：运行任务
- 今日 pipeline 时间线
- 每个 phase 状态
- 手动重跑按钮
- 失败原因
- 影响范围

右侧：记忆检索
- 搜索框
- 过滤：股票/gene/error_type/date
- 结果列表
```

### 数据质量展示

建议把数据质量分成 4 个层级：

- 行情：股票池、交易日历、daily prices、index prices。
- 因子：行业、基本面、事件、风险。
- 证据：财报实际、市场预期、预期差、订单、KPI、风险事件。
- LLM：调用状态、预算、失败率。

每个层级都用同一种结构：

```text
Status: OK / Partial / Missing / Error
Coverage: 80.4%
Latest Sync: 15:05
Source: AKShare / BaoStock / skipped
Impact: 是否影响推荐/复盘/进化
```

## 关键组件重构

### 1. GlobalDateContext

当前每个页面各自维护 `date`，会导致状态不一致。

建议新增全局日期上下文：

- 当前交易日。
- 用户选择日期。
- 最近交易日。
- 日期变化时页面统一刷新。

### 2. SystemStatusBar

全局状态条组件。

输入：

- `runtime_mode`
- `is_demo_data`
- `data_quality_summary`
- `evidence_status`
- `llm_status`
- `scheduler_status`

输出：

- 简短状态。
- 严重告警。
- 点击进入数据与运行页。

### 3. StockSearch

全局股票搜索。

要求：

- 支持代码/名称。
- 支持最近查看。
- 选择后可以跳转到单股复盘或选股研究详情。

### 4. FactorScoreMatrix

统一展示五维评分：

- technical
- fundamental
- event
- sector
- risk

要求：

- 风险分数方向要明确：风险越高越差。
- 缺失不是 0 分，必须用 missing state 表示。
- 鼠标 hover 展示 source/as_of_date。

### 5. EvidenceTimeline

替代当前证据堆叠表。

分组：

- 盘前可见。
- 收盘观察。
- 事后事件。

每条证据展示：

- 类型。
- 标题/摘要。
- source。
- publish_date。
- as_of_date。
- confidence。
- 是否可用于策略惩罚。

### 6. SignalReviewList

统一展示 optimization signals。

展示字段：

- signal_type。
- param_name。
- direction。
- strength。
- sample_count。
- avg_confidence。
- evidence_ids。
- status。
- accept/reject/consumed。

### 7. EvolutionDiff

统一展示策略参数变化。

要求：

- before/after。
- delta percentage。
- 是否超过 5%。
- 来源 signal group。
- rollback pointer。

## 视觉设计建议

### 整体风格

建议从当前“复古纸张 + 粗边框”调整为“研究终端 + 审计台账”。

关键词：

- 克制。
- 高密度。
- 清晰边界。
- 状态明确。
- 少装饰，重信息。

### 色彩

建议色板：

- 背景：`#F6F4EF` 或 `#F7F8F6`
- 主文本：`#1E2422`
- 次文本：`#68716D`
- 边线：`#D8DDD7`
- 面板：`#FFFFFF`
- 当前选中：`#0E6F67`
- 收益/通过：`#157347`
- 亏损/风险：`#B42318`
- 警告/缺失：`#B7791F`
- 信息：`#2563EB`

减少：

- 大面积金色。
- 粗黑边框。
- 大阴影。
- 装饰性网格背景。

### 字体

建议：

- 中文和正文：系统 UI 字体栈，保证清晰和高密度。
- 数字：开启 `font-variant-numeric: tabular-nums;`。
- 不建议继续用 Georgia 作为全局字体，因为金融数据表和操作按钮会显得不够干净。

### 间距与密度

建议：

- 卡片圆角 6-8px。
- 面板阴影极弱或不用阴影。
- 表格行高 36-42px。
- 密集信息用 table，不用大量 card。
- 卡片只用于 summary、alert、event、decision，不用于所有列表。

## 推荐用户路径

### 路径 A：早盘查看推荐

1. 打开今日工作台。
2. 看全局状态条，确认 live、行情 OK、因子/证据覆盖。
3. 看推荐队列。
4. 点击某只股票，在右侧抽屉看摘要。
5. 对感兴趣股票进入选股研究详情。

### 路径 B：收盘复盘

1. 打开复盘中心。
2. 先看策略整体复盘。
3. 查看 top errors 和 blindspots。
4. 点击某只股票进入单股复盘。
5. 核查证据时间线。
6. 接受或拒绝优化信号。

### 路径 C：周末进化

1. 打开策略进化。
2. 看未消费信号池。
3. 点击 dry-run，查看参数变化。
4. 如果规则满足，正式 propose。
5. 观察 Challenger 表现。
6. 达标后 promote，否则 rollback。

### 路径 D：排查系统问题

1. 看到全局状态条告警。
2. 点击进入数据与运行。
3. 查看哪个源失败、影响哪个维度。
4. 手动重跑某个 phase。
5. 回到工作台确认状态恢复。

## 分阶段改造计划

### Frontend Phase 1：信息架构重排

- [TODO] F1.1 新增 `选股研究` 页面。
- [TODO] F1.2 将 `CandidateScores` 从策略进化页迁移到选股研究页。
- [TODO] F1.3 工作台只保留推荐摘要、模拟盘摘要、运行状态和待办。
- [TODO] F1.4 复盘中心增加二级 tabs。
- [TODO] F1.5 数据与记忆改名为数据与运行。

### Frontend Phase 2：全局状态与交互

- [TODO] F2.1 新增全局日期状态。
- [TODO] F2.2 新增全局 `SystemStatusBar`。
- [TODO] F2.3 新增全局股票搜索。
- [TODO] F2.4 推荐点击改为右侧抽屉或详情跳转。
- [TODO] F2.5 所有危险动作增加确认和影响说明。

### Frontend Phase 3：复盘体验升级

- [TODO] F3.1 单股复盘改为 decision list + detail + evidence timeline 三栏。
- [TODO] F3.2 策略复盘改为 gene list + review detail + issue panel。
- [TODO] F3.3 盲点复盘按可学习/不可惩罚/正确避开/数据缺失分组。
- [TODO] F3.4 LLM 复盘单独展示 claim、evidence、schema、token cost。
- [TODO] F3.5 optimization signals 使用统一审核列表。

### Frontend Phase 4：策略进化体验升级

- [TODO] F4.1 策略进化页移除候选评分。
- [TODO] F4.2 新增信号池。
- [TODO] F4.3 新增 dry-run 结果预览。
- [TODO] F4.4 新增 evolution diff。
- [TODO] F4.5 Promote/Rollback 增加确认流程和历史保留说明。

### Frontend Phase 5：视觉系统重做

- [TODO] F5.1 重建 CSS tokens。
- [TODO] F5.2 去掉重边框、重阴影、装饰网格。
- [TODO] F5.3 建立 table、badge、status、timeline、drawer、tabs 组件。
- [TODO] F5.4 统一按钮层级：primary、secondary、danger、ghost。
- [TODO] F5.5 移动端检查，保证表格和详情不重叠。

## 最小可落地版本

如果只做一轮小改，优先顺序如下：

1. 新增全局状态条。
2. 新增选股研究页，把候选评分迁过去。
3. 工作台减负，只保留今日摘要和推荐队列。
4. 单股复盘改成三栏：decision、review、evidence timeline。
5. 策略进化增加 dry-run 预览和确认。
6. 视觉上去掉粗黑边框和大阴影，改为金融终端式浅色高密度 UI。

这 6 项能明显改善“看不懂系统正在做什么”和“复盘证据链不清晰”的问题。
