# 用户视角试用记录：材料导入到复习闭环

- 日期：2026-09-09
- 入口：CLI + `LearningWorkbench`，桌面端做启动 smoke，不做手动点击
- Provider：真实 OpenAI-compatible provider，显式加载本地 `.env`
- 数据目录：临时 `LINGUALOOP_DATA_DIR`
- 材料：Project Gutenberg / Aesop fable 方向的短英文材料，保存为临时 Markdown 文件
- 来源参考：Project Gutenberg `Three Hundred Aesop's Fables` / `The Wind and the Sun`，公有领域条目：https://www.gutenberg.org/ebooks/21

## 走通的流程

1. 创建临时 Markdown 材料文件。
2. 执行 `import <file>`，输入 source language、target language、native language、level。
3. 材料成功导入并生成 normalized copy、summary、keywords 和 suggested goals。
4. 执行 `start`，生成第一条练习任务。
5. 连续执行三轮 `say`，系统返回对话回复和即时反馈。
6. 执行 `finish`，生成 session summary、focus areas、next action 和 3 个 review items。
7. 执行 `review`，可以看到 review queue。
8. 执行 `rate 1 good went`，成功记录一次复习结果并更新 next due date。
9. 重新创建 Workbench 读取同一个 SQLite，能恢复材料、已完成 session 和 review queue。

## 用户视角问题清单

### P0 / 阻断级

- CLI 默认启动不加载 `.env`。仓库根目录已有 `.env`，但直接运行 `python -m lingualoop.cli` 报 `Set OPENAI_API_KEY before creating OpenAICompatibleLLMProvider`。普通用户会认为配置失效；README 也描述默认读取环境配置。

### P1 / 核心体验问题

- Windows 默认 GBK 输出会被模型回复中的 Unicode 符号卡住。试用脚本在完整流程最后打印 transcript 时因模型输出 `✅` 触发 `UnicodeEncodeError`。CLI 真实使用时也可能因为 provider 输出 emoji 或特殊符号而崩溃，建议配置 UTF-8 stdout 或做安全输出降级。
- AI 生成的练习任务扩写了原材料。输入材料只有两句话，但 `start` 任务中出现了更完整的“The wind and the sun...”故事文本。作为用户会担心系统没有严格锚定自己导入的材料，而是在补写材料。
- 第一轮反馈过多且重复。一个回答产生了 5 条反馈，其中包含 `blowed -> blew`、`keeped -> kept` 和多条重叠句子级改写。对 A2 用户来说负担较重，也不符合“优先 pattern-level 问题”的产品原则。
- Review 结果没有校验用户答案。复习题要求两个空 `blew / shone`，但输入 `went` 后执行 `rate 1 good went` 仍然记录为 good，并把 due date 推迟。这样会把错误复习也记录成学习证据。
- Review 列表语义混乱。`review` 输出显示 `Review items (3), due now: 0`，但仍列出 3 个项目。用户会不清楚这是所有队列、今日 due 队列，还是已推迟项目。

### P2 / 可用性和产品一致性

- `import` 流程不能编辑导入标题。文件名 `lingualoop-user-trial-material.md` 变成标题 `lingualoop user trial material`，导入后没有机会确认或修改。
- `import` 流程没有 track 选择。计划里要求 `track` 是显式属性，但 CLI 导入固定走默认 `article_reading`。
- 没有 raw / normalized 预览确认。CLI 只输出 diagnostics，不展示 normalized 后的内容，用户无法确认 Markdown 清理是否损坏材料。
- `summary` 在 session completed 后仍显示 `Current task` 和最后一条 assistant message，没有突出“本轮已完成”和最终复盘摘要。
- QML 代码中 `review` 卡片直接显示“答案：...”，会破坏冷启动回忆；CLI 没显示答案，但桌面端会让用户未作答前看到答案。
- QML 已有 `materials` ViewModel 属性，但页面没有实际显示材料列表/最近材料；用户重启后能恢复数据，但 UI 上不容易发现历史材料入口。
- 桌面材料页还没有 raw/normalized 切换、纠错强度设置和导入后确认步骤。
- 复习页把会话复盘和 review practice 混在同一页，用户不容易区分“看复盘”和“开始复习”。

## 建议优先修复顺序

1. 在 CLI `main()` 或 provider builder 中加载 `.env`，并给 README/CLI 行为保持一致。
2. 配置 CLI 输出为 UTF-8 或对 stdout 编码错误使用 replacement fallback。
3. 把 review 分成 `review --all` 和默认 due-only，或修改文案为“全部复习项 / 今日到期”。
4. 为 review outcome 增加最小答案校验：至少在 `good/easy` 前比较标准答案或要求用户确认。
5. 收紧 `generate_task` prompt，要求任务不得补写未出现在材料中的事实；若生成辅助场景必须标明是“练习扩展”。
6. 限制即时反馈数量，优先输出 1-3 个 pattern-level 问题，合并重复 corrections。
7. 桌面端隐藏答案，用户提交复习回答后再显示标准答案和 outcome 按钮。
8. 补材料列表、标题确认、track 选择、raw/normalized 预览和纠错强度设置。

## 原始试用摘要

- 导入成功：Markdown formatting 被清理，raw content 保留。
- 三轮回答成功：系统能持续围绕材料提问和纠错。
- 结束复盘成功：生成 summary、focus areas、next action 和 3 个 review items。
- 复习结果成功持久化：`good` 后 next due date 更新到 2026-09-12 UTC。
- 重启恢复成功：重新创建 Workbench 后读取到 1 个材料、completed session、3 个 active review items。

## 修复后回归检测

- 时间：2026-09-09
- 入口：CLI + `LearningWorkbench`，真实 OpenAI-compatible provider，仓库根目录 `.env` 自动加载
- 数据目录：临时 `LINGUALOOP_DATA_DIR`
- 材料：短 Markdown《The Wind and the Sun》，包含 Markdown 标题和 3 句正文

### 回归流程结果

1. `build_provider(False)` 能从当前工作目录 `.env` 创建真实 provider，不再误报缺少 `OPENAI_API_KEY`。
2. `import <file>` 显示 normalized preview，提示 raw content 已单独保留，并允许标题覆盖为 `Wind and Sun Trial`、track 选择为 `article_reading`。
3. `start` 成功生成材料锚定的练习任务。
4. 连续两轮 `say` 成功返回 AI 对话回复；每轮即时反馈各 2 条，未超过 3 条上限。
5. `finish` 成功生成 completed session、复盘摘要和 3 个 review items。
6. 默认 `review` 只显示今日到期项，输出为 `今日到期复习项（0 项；全部复习项 3 项，可用 review --all 查看）。`
7. `review --all` 显示全部 active queue，输出为 `全部复习项（3 项；今日到期 0 项）：`
8. `rate 1 good definitely_wrong_answer` 被拒绝，且没有推迟原 review item 的 `due_at`。
9. 使用标准答案执行 `rate 1 good <answer>` 成功记录 outcome，并显示下一次复习时间。
10. 重新创建 `LearningWorkbench` 读取同一个 SQLite 后，恢复 1 个材料、completed session 和 3 个 active review items。
11. CLI 安全输出层在 ASCII-only stream 中输出 `✅` 时降级为 `?`，不抛出 `UnicodeEncodeError`。

### 已解决问题

- P0：CLI 默认启动不读取 `.env` 已解决。
- P1：Windows CLI Unicode 输出崩溃已解决。
- P1：任务生成 prompt 已加入材料事实边界约束，禁止补写材料中没有的事实。
- P1：即时反馈已按 `(original, corrected)` 去重并限制为最多 3 条。
- P1：`good/easy` 复习评分已加入最小答案校验；错误答案不能被记录为掌握或推迟。
- P1：`review` 默认 due-only，`review --all` 显示全部 active queue，文案已区分。
- P2：CLI import 已支持标题确认、track 输入和 normalized preview。
- P2：completed session 的 `summary` 输出已突出 `Status: completed`、复盘摘要和 next action，不再把 `Current task` 作为主要信息。
- P2：QML review 卡片默认隐藏参考答案，用户提交答案后才显示答案和评分按钮。
- P2：QML 材料页已显示最近材料列表，支持 `selectMaterial()`，并增加 raw / normalized 预览切换。
- P2：QML 复盘页已轻量分区为“本轮复盘”和“复习队列”。

### 剩余事项

- 桌面端仍是 QML smoke 验证和静态绑定检查，尚未做完整人工点击式真实 provider 试用。
- 当前答案校验只使用确定性规范化字符串相等/包含规则，不做 LLM 判分；多空答案的严格判定后续需要继续增强。
- QML 在 Windows pytest 中仍会打印 PySide6/Kirigami 相关 `0xc0000139` faulthandler 诊断，但测试进程退出码为 0，需在 runtime 文档或后续环境修复中继续跟踪。
