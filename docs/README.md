# 文档导航与分类约定

当前主旨是“沉浸提供语境，LinguaLoop 帮你练输出”。文档按用途分类：产品定义目标，架构解释机制，路线图列下一步，验收记录证明实际结果；设计草案和历史记录都不能替代已实现能力。

## 优先阅读

1. [项目主旨](./product/PROJECT_BRIEF.md)：为谁解决什么问题。
2. [MVP 范围](./product/MVP_SPEC.md)：第一版边界与验收要求。
3. [适量材料预处理与双模型协作方案](./architecture/ai/PREPARATION_AND_DIALOGUE.md)：已落地的机制与质量验收边界；不包含 UI 重做。
4. [路线图](./planning/ROADMAP.md)：当前实现、下一步和待验证项。
5. [验收记录目录](./validation/README.md)：实际运行证据与限制。

## 分类与存放规则

| 目录 | 内容 | 不放什么 |
| --- | --- | --- |
| `product/` | 定位、MVP、用户流程、交互设计 | 模型调用日志、底层实现细节 |
| `architecture/` | 系统边界、数据模型、机制设计；AI 专项放 `architecture/ai/` | 逐轮执行记录和测试成绩 |
| `decisions/` | 决策背景、选择、状态、影响与替代关系 | 重复抄录完整专项方案 |
| `research/` | 外部资料、学习依据、候选服务与方案对照 | 未经实测的交付承诺 |
| `desktop/` | 桌面运行、配置、语音与设备使用指南 | 产品愿景或日期化验收报告 |
| `planning/` | 当前路线图、正在执行且尚未收口的工作草稿 | 已稳定的验收报告和历轮执行地图 |
| `validation/` | 已形成阶段结果的文本、语音、MVP 和工程验收记录 | 未来实现方案 |
| `archive/` | 不再驱动当前工作的执行地图和历史快照 | 当前状态的唯一来源 |

`docs/` 根目录只保留本导航，不平铺新增方案或报告。长期方案使用稳定文件名；日期化实验与验收使用带日期的文件名。草案须标注“待实现”，报告须写明真实服务／Mock／离屏／实机的证据类型及限制。

## 产品与交互

- [项目主旨](./product/PROJECT_BRIEF.md)
- [MVP 规格](./product/MVP_SPEC.md)
- [项目命名探索备忘](./product/NAMING_EXPLORATION_2026-10-28.md)：独立探索暂存，未决定更名，不影响当前实现与配置。
- [视觉风格设计：暖纸与墨迹（暂定）](./product/VISUAL_STYLE_GUIDE.md)：最新融合参考图、配色、字体分工和可复用图标生成提示词；只确定视觉方向，具体 UI 待讨论，尚未实现。
- [总体布局与逐页 UI 稿](./product/UI_LAYOUT_DESIGN.md)：材料下组织多段对话、页面内导入／范围核对、六组设置与原文对照；含 30 个视图、逐页 PNG 和可点击稿，待评审，未改 QML。
- [输入与流程的外部设计参考](./product/UI_DESIGN_REFERENCES.md)：Carbon、GOV.UK、Readwise 官方资料与公开示例，记录页面内操作的依据、取舍和核验范围。
- [MD3 界面方案与历史实现](./product/UI_SURFACE_PLAN.md)
- [读后对照聊天功能设计](./product/CONVERSATION_WORKSPACE_DESIGN.md)：核心交互已认可、待实现；含组件契约、状态转移、输入细节、语音/失败时序、参考图与验收编号，是总 UI 设计的本功能输入，不改变本轮 AI 机制任务范围。

## 架构与专项设计

- [系统架构](./architecture/ARCHITECTURE.md)：当前实现、兼容路径与目标架构的边界。
- [AI：适量材料预处理与模型协作](./architecture/ai/PREPARATION_AND_DIALOGUE.md)：资料契约、流程、预算、有效期、阅读边界和验收。
- [Agent Kernel 设计](./architecture/AGENT_CORE_ARCHITECTURE.md)：含规划中的 adapter，不代表当前桌面已经采用。
- [扩展架构](./architecture/PLUGIN_ARCHITECTURE.md)
- [学习 Pattern](./architecture/LEARNING_PATTERNS.md)
- [核心概念](./architecture/CORE_CONCEPTS.md)
- [技术决策](./decisions/TECH_DECISIONS.md)：编号唯一；新设计和现有实现分开标注。

## 研究与依据

- [语言学习闭环依据](./research/LEARNING_LOOP_FOUNDATION.md)
- [既有学习工作区经验](./research/PRACTICE_WORKSPACE_FINDINGS.md)
- [服务选型与接入边界](./research/SERVICE_SELECTION_2026-10-24.md)：官方静态资料不等于真实稳定性验收。
- [用户材料整理参考方案评审](./research/REFERENCE_PLAN_REVIEW_2026-10-24.md)

## 运行与开发指南

- [QML 运行环境](./desktop/QML_RUNTIME.md)
- [分轮语音配置](./desktop/VOICE.md)
- [LiveKit 本机探针](./desktop/LIVEKIT.md)
- [可选本地语音模型库](./desktop/LOCAL_SPEECH.md)
- [仓库开发约定](../AGENTS.md)
- [贡献指南](../CONTRIBUTING.md)

## 计划、验证与归档

- [当前路线图](./planning/ROADMAP.md)
- [本地语音严格评测阶段报告](./validation/speech/LOCAL_SPEECH_STRICT_EVALUATION_2026-10-28.md)：34 个模型/语言配置的客观评测与 156 条试听样本；人工听感及完整语音链路仍未验收。
- [SenseVoice GPU、日语 STT 与 Melo 独立英文补测](./validation/speech/SPEECH_GPU_JAPANESE_MELO_FOLLOWUP_2026-10-29.md)：32 个主配置、额外 GPU 负载对照、352 条音频附件；真实 CUDA 执行、平均 500ms 筛选、否定句重复诊断及共享显存慢尾单列。
- [分类验收目录](./validation/README.md)：包含完整小说、自由聊天、真实服务、语音与工程审查。
- [语义准备与双模型协作实测](./validation/text/SEMANTIC_PREPARATION_2026-10-28.md)：100 次真实请求、全书及部分阅读、三条件比较；事实与一秒门禁尚未通过。
- [历史归档目录](./archive/README.md)：保留旧执行表与证据编号，当前工作不继承其中的角色或“进行中”状态。
