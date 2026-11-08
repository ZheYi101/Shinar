# Learning Patterns

本文档定义 Shinar 中 Pattern 的产品语义和早期分类。Pattern 回答“怎么学”，Plugin 回答“能做什么”，Kernel 负责把 Pattern 编译并执行为可追踪的学习会话。

当前主旨见 [Project Brief](../product/PROJECT_BRIEF.md)。默认路径是沉浸材料的话题讨论，语音是正式 MVP 的必需能力；`input-lesson` 等流程按需进入，`guided-roleplay` 由用户自愿选择。以下是目标设计，不表示各 Pattern 已实现。

## Pattern 的定义

Pattern 是一套可声明、可测试、可复盘的学习流程。它不等于 prompt 模板，也不等于外部能力插件。

一个 Pattern 至少应定义：

- 适用学习现象：例如看得懂但说不出、语块断裂、论证复述不稳、延迟复习失败。
- 输入要求：材料类型、track、是否需要 segment、是否需要已有用户输出。
- 练习计划：本轮目标、步骤、目标数量、输出形式和结束条件。
- 反馈策略：纠错强度、是否打断、优先记录哪些错误。
- 复习策略：什么内容会变成 `ReviewItem`，何时再次出现。
- Capability requirements：需要哪些 plugin 能力，例如 `llm.generate`、`material.segment`、`stt.transcribe`。

## 共同不变量

所有 Pattern 都应遵守以下不变量：

- 练习必须尽量锚定真实材料、真实场景或真实用户输出。
- 每轮应包含主动输出或检索动作；只解释不算完成学习闭环。
- 学习状态只能由真实表现更新，不能由“系统展示过内容”更新。
- 反馈优先处理 pattern-level 问题，而不是穷尽所有小错。
- Review item 应是可再次检索、改写或迁移使用的任务，不只是收藏词条。
- Pattern 不能绕过 core schema 写学习历史；所有关键动作都应落成 `SessionEvent`。

## 初始 Pattern 家族

### `topic-discussion`

解决问题：用户已经通过沉浸接触过内容，但缺少共同语境下的口语伙伴，或不知道从什么话题开口。

适用场景：看完动画、视频、播客或文章后，讨论人物、事件、观点、个人经历和相关选择。

稳定结构：

```text
material/context understanding
  -> grounded topic suggestions and opening questions
  -> learner selects, edits or proposes a topic
  -> voice discussion
  -> optional hints and feedback
  -> learner ends session
  -> light closeout and review candidates
```

关键规则：

- 话题和追问保留材料依据及本次内容范围，材料不足时允许用户补充或缩小讨论范围。
- 不要求用户扮演角色，也不要求先完成词汇课、理解检查或固定 lesson。
- 语音为正式 MVP 的主路径，文本可用于原型、补充和回退；最终能力 contract 按所选语音实现定义。
- 纠错时机和强度可调；反馈与复习项来自用户真实输出。

MVP 地位：默认讨论 Pattern，优先与现有材料分析、反馈和复习对象整合。

### `input-lesson`

解决问题：把用户已经看过或读过的真实输入材料变成一轮可练习、可纠错、可复习的学习任务。

适用场景：字幕、文章、纪录片讲解、博客、聊天记录、课程笔记等。

稳定结构：

```text
Scene / Argument Capsule
  -> High-Value Chunks / Vocab
  -> Comprehension Check
  -> Error-Prone Rewrite
  -> Contextual Output
  -> Profile Delta + Review Candidates
```

关键规则：

- raw subtitle / transcript 必须先清洗为 lesson-ready text。
- `track` 决定目标选择和输出任务，而不是文件后缀决定。
- `live_chat` 优先互动语气、口语 chunk 和场景输出。
- `article_reading` 优先论点理解、连接词、立场表达、summary 和 paraphrase。

MVP 地位：保留为按需学习方式，不是进入话题讨论前必须完成的流程。

### `guided-roleplay`

解决问题：让学习者围绕材料语境进行多轮对话，把材料中的表达迁移到互动使用中。

适用场景：餐厅、会议、主播/观众互动、面试、旅行、协商、解释观点等。

稳定结构：

```text
material/context setup
  -> role and goal assignment
  -> assistant opens in role
  -> learner replies
  -> assistant continues in role
  -> optional feedback
  -> closeout and review candidates
```

关键规则：

- AI 不应自由扩展成无上下文聊天；每轮都应保留材料语境或练习目标。
- 纠错强度应可配置，避免打断对话流。
- 反馈应偏向可迁移表达和 recurring pattern，而不是每轮长篇批改。

MVP 地位：用户主动选择的可选讨论方式，可与 `topic-discussion` / `input-lesson` 共享材料分析结果；不作为默认入口。

### `retell`

解决问题：把输入理解转化为复述能力，暴露信息组织、时态链、连接词和表达迁移问题。

适用场景：文章总结、视频复述、历史/解释型材料、工作汇报、观点重述。

稳定结构：

```text
source capsule
  -> target expressions
  -> learner retell
  -> correction
  -> rebuilt retell
  -> review candidates
```

关键规则：

- 不要求逐字复述，要求保留核心意思和关键语言目标。
- 评价重点是信息完整性、逻辑顺序、连接词、搭配和目标表达复用。

MVP 地位：可作为 `input-lesson` 后续或 guided roleplay 之外的文本练习。

### `summary-first-review`

解决问题：用户返回学习时，系统需要从历史 review items 中选择今天最值得练的方向，而不是倾倒所有过期条目。

适用场景：长期学习工作区、旧 lesson 回访、错题/语块回忆、延迟检索。

稳定结构：

```text
review pressure summary
  -> 1-3 focus groups
  -> short context reminder
  -> small prompt set
  -> outcome capture
  -> schedule/update review items
```

关键规则：

- 默认只展示摘要和少量任务，具体 item 细节按需展开。
- 如果 review item 绑定源材料，需要先给 2-4 句 context reminder。
- outcome 至少要能表达 `again`、`hard`、`good`、`easy`、`mastered`。
- 用户可以 pause、ignore、delete、archive，且这些动作应成为事件。

MVP 地位：第一版至少要有 summary-first 的 review 入口和简单 outcome。

### `cora`

解决问题：学习者已经理解表达，但口语中不能快速稳定取出。

适用场景：口语自动化、面试回答、日常表达、即兴描述、延迟回忆。

稳定结构：

```text
Cold attempt
  -> Observe
  -> Rebuild
  -> Automate
```

关键规则：

- 冷启动尝试前不能展示 model answer。
- 每轮最多处理三个 production fractures：一个 chunk、一个 grammar/sentence-building、一个 fluency issue。
- 每轮只允许一个主题、三个 target chunks、一个 grammar target。
- 自动化依赖压缩、迁移、延迟回忆和 D+1/D+3/D+7 返回。
- 不根据 ASR 文本断言发音问题；需要音频证据。

MVP 地位：建议放入 Phase 2，不阻塞基础语音讨论 MVP；其“输出才是证据”原则应从 MVP 开始遵守。

### `shadowing`

解决问题：训练听觉-发音-节奏对齐，适合后续语音能力成熟后接入。

适用场景：跟读、语音节奏、弱读连读、语调模仿。

关键规则：

- 需要音频、TTS 或 STT capability 时，必须通过插件声明。
- 不应从纯文本 transcript 直接诊断发音。

MVP 地位：Phase 2 或语音插件验证后再实现。

## Pattern 与数据对象

| Pattern 输出 | Core 对象 | 用途 |
| --- | --- | --- |
| 练习目标和步骤 | `PracticePlan` / `PracticeInstruction` | 告诉 Kernel 本轮怎么练 |
| 用户回答 | `Message` / `SessionEvent` | 形成真实表现证据 |
| 纠错和表达建议 | `FeedbackItem` | 记录 pattern-level 问题和直接修正 |
| 复习候选 | `ReviewItem` | 支持延迟检索和后续练习 |
| 本轮画像变化 | `ProfileDelta` | 汇总当前证据，不作为唯一长期事实来源 |
| 复习结果 | `ReviewOutcome` / `SessionEvent` | 更新 review queue 和 learner profile snapshot |

`ProfileDelta` 和 `ReviewOutcome` 当前仍是待定 schema，但应在 core 里作为独立概念建模，避免把它们塞进自由文本 summary。

## Capability Requirements 示例

```text
topic-discussion
  requires:
    - llm.generate >= 1.0
    - voice.session >= 1.0
  optional:
    - material.segment >= 1.0

input-lesson
  requires:
    - llm.structured >= 1.0
  optional:
    - material.normalize >= 1.0
    - material.segment >= 1.0

guided-roleplay
  requires:
    - llm.generate >= 1.0
  optional:
    - voice.session >= 1.0
    - stt.transcribe >= 1.0
    - tts.speak >= 1.0

summary-first-review
  requires:
    - review.read >= 1.0
  optional:
    - review.schedule >= 1.0

cora
  requires:
    - llm.generate >= 1.0
  optional:
    - stt.transcribe >= 1.0
    - telemetry.record >= 1.0
```

以上是能力组合示意，不冻结语音传输方式。基础语音可采用轮流识别与合成；只提供文本的讨论可用于开发验证，但不满足正式 MVP 的语音要求。

## 第一版实现顺序

1. 复用现有文本闭环，补齐 `topic-discussion` 的话题生成、选择和最小 Pattern contract。
2. 接入基础语音能力，完成“选话题 → 多轮说话与收听回复 → 轻量复盘”，支持自愿切换到 `guided-roleplay`。
3. 将输出证据接到现有 review queue，完善 `summary-first-review` 的最小入口和 outcome。
4. 按实际需要补齐 registry、capability requirement check 与 LangGraph adapter，不让完整框架阻塞核心语音路径。
5. 将 CORA、更多练习方法与理论配置放入后续增强，保留冷启动输出和延迟输出的测量原则。

## 重新评估条件

- 如果所有 Pattern 最终都退化成同一套 prompt，则说明 Pattern 边界过弱。
- 如果每个 Pattern 都要求自定义数据模型且无法共享反馈和复习项，则说明 core schema 过窄。
- 如果 LLM 开始决定下一步学习流程而不是执行 Pattern，则需要收紧 Kernel 控制权。
- 如果 review item 数量快速膨胀但用户不复习，则需要优先优化 summary-first review，而不是继续增加 lesson 生成能力。
