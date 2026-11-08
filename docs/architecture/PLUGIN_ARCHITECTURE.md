# Extension Architecture

## 核心结论

Shinar 应采用三层扩展架构，而不是把所有东西都做成同一种插件。

```text
Shinar Core
  固定的学习领域核心

Plugins
  可用可不用的能力提供者

Patterns
  可组合的学习流程；部分 Pattern 会依赖特定 Plugin 能力
```

项目的稳定核心应定义语言学习语义和数据边界；Plugins 负责提供外部能力和交互模态；Patterns 负责组织「怎么学、怎么练、多久复习一次」。

产品主旨以 [Project Brief](../product/PROJECT_BRIEF.md) 为准：沉浸材料提供共同语境，语音讨论练输出。插件可替换不等于产品能力可省略；正式 MVP 的讨论路径必须具备基础语音，已有文本路径承担原型、辅助输入和回退。

更准确的原则是：

```text
fixed learning core + optional plugins + capability-aware patterns
```

这意味着 Shinar 可以借鉴通用 agent 系统的插件组合思想，但不能让插件任意改写学习闭环本身，也不能把学习 Pattern 简化成普通能力插件。系统的产品灵活度主要来自 Pattern，而不是来自一个自由规划的大 agent。

## 为什么不是 everything is plugin

Codex、Claude Code、DeepSeek Harness 这类通用 agent 系统的目标是让模型、工具、文件访问、session log、agent loop、UI 等能力服务于开放任务。这个思路适合通用 agent runtime，因为 agent harness 本身就是运行和组合能力的平台。

Shinar 的目标不同。它首先是语言学习产品，关键价值来自稳定的学习闭环：材料输入、任务化练习、即时反馈、结构化复盘和后续复习。用户和 AI 的交互主要围绕练习语句和材料语境展开，不需要 agent 自由决定下一步要完成什么开放任务。如果这些核心语义都变成任意插件行为，产品会很容易失去一致性、可测试性和学习数据可迁移性。

因此 Shinar 的核心应保持较小但稳定，Plugins 通过明确协议接入，Patterns 通过 core 的学习协议运行，并声明自己需要哪些 plugin capability。

## 分层模型

```text
apps
  web app
  future desktop / mobile surfaces

packages/core
  domain models
  learning session state machine
  event log schema
  pattern contracts
  feedback / review schemas

packages/plugin-runtime
  plugin manifest
  capability registry
  lifecycle hooks
  permissions and configuration
  compatibility checks

packages/plugins
  voice-livekit
  avatar-live2d
  importer-subtitles
  material-normalizer
  llm-openai-compatible
  stt-provider adapters
  tts-provider adapters

packages/patterns
  input-lesson
  roleplay
  cora
  shadowing
  retell
  socratic
  spaced-review
```

依赖方向：

```text
apps -> core
apps -> plugin-runtime
apps -> selected plugins
apps -> selected patterns

patterns -> core contracts
patterns -> declared capabilities from plugins

plugins -> core capability contracts

core -> no plugin or pattern dependency
```

Core 不导入具体 Plugins 或 Patterns。Patterns 可以依赖 Core contract，并通过 capability registry 使用插件提供的能力。Plugins 不应该依赖具体 Pattern；它们只提供通用能力。

## 稳定核心

以下概念属于 Shinar core，不应由插件随意替换或改写：

- UserProfile: 用户语言、目标、偏好设置。
- LearningMaterial: 学习材料、来源、正文、分析结果。
- LearningSegment: 可教学片段、track、起止引用、场景/论点摘要和前后文摘要。
- PracticeSession: 练习会话、目标、难度、状态和消息。
- Message: 对话消息、角色、时间、反馈引用。
- FeedbackItem: 错误类型、原句、建议句、解释、复习状态。
- ReviewItem: 表达、例句、来源会话、下次复习时间。
- SessionEvent: 可追踪、可回放的学习事件。
- PracticePlan: 一次练习的目标、步骤、约束和验收点。

这些对象是数据迁移、测试、复盘和长期产品一致性的基础。

## 三层职责

### Core

Core 是定死的产品内核，负责定义：

- 学习领域对象。
- 会话状态机。
- Session event log。
- Feedback / Review schema。
- Pattern contract。
- Capability contract。
- 权限和数据访问边界。

Core 的变化应谨慎，因为它影响数据迁移、插件兼容性和 Pattern 复用。

### Plugins

Plugins 是可用可不用的能力提供者。它们不决定学习流程，只注册能力。

典型能力包括：

- `llm.generate`: 生成模型能力。
- `stt.transcribe`: 语音转文本。
- `tts.speak`: 文本转语音。
- `voice.session`: 实时语音会话。
- `avatar.render`: avatar / Live2D 渲染。
- `material.import`: 外部材料导入。
- `material.normalize`: 将 raw subtitle / transcript 清洗为 lesson-ready text。
- `material.segment`: 按 track 生成可教学片段和前后文摘要。
- `review.schedule`: 计算或更新 review item 的下次复习时间与结果。
- `telemetry.record`: 指标记录。

一个插件可以注册多个 capability，例如 `voice-livekit` 可以同时提供 `voice.session`、`stt.transcribe`、`tts.speak` 的编排能力和语音指标。

### Patterns

Patterns 是学习流程层。它们定义练习的顺序、节奏、反馈方式和复习策略，但不直接实现底层语音、avatar 或 provider 能力。

Pattern 可以是内置的，也可以作为第三方 package 分发；但概念上它不是普通 Plugin。Pattern 使用 Core 的学习协议，并声明自己依赖哪些 plugin capability。

例如：

- `input-lesson`: 依赖 `llm.generate` / `llm.structured`，可选依赖 `material.normalize` 和 `material.segment`。
- `roleplay`: 可只依赖 `llm.generate`，也可以可选依赖 `voice.session`。
- `cora`: 可只依赖文本输入和 `llm.generate`，语音版可选依赖 `stt.transcribe`。
- `shadowing`: 通常依赖 `tts.speak`、`stt.transcribe`，可选依赖 `avatar.render`。
- `retell`: 主要依赖 `llm.generate`，可选依赖 `stt.transcribe`。
- `spaced-review`: 可以不依赖多模态插件，只依赖 core review data；更完整版本可选依赖 `review.schedule`。

## 扩展点

### 学习 Pattern

学习 Pattern 定义「怎么练」，但必须产出 Core 能理解的练习计划、下一轮指令和复盘草稿。它通过 capability requirements 声明依赖，而不是直接绑定某个具体插件实现。

```ts
interface LearningPattern {
  id: string;
  title: string;
  supportedModalities: Array<"text" | "voice" | "avatar">;
  requiredCapabilities: CapabilityRequirement[];
  optionalCapabilities?: CapabilityRequirement[];
  createPlan(input: MaterialAnalysis, profile: UserProfile): PracticePlan;
  nextTurn(state: PracticeState, event: SessionEvent): PracticeInstruction;
  summarize(state: PracticeState): ReviewDraft;
}

interface CapabilityRequirement {
  capability: string;
  version: string;
  reason: string;
}
```

候选 pattern：

- `pattern-roleplay`: 角色扮演对话。
- `pattern-shadowing`: 影子跟读。
- `pattern-retell`: 先理解、再复述、再纠错。
- `pattern-socratic`: 提问式理解检查。
- `pattern-spaced-review`: 1 天、3 天、7 天等复习调度。

Pattern 运行前，runtime 必须检查 required capabilities 是否可用；不可用时应提示用户启用插件、安装插件或切换到兼容 Pattern。

### 语音插件

语音插件定义实时口语能力，但不应定义学习数据模型，也不直接决定学习流程。LiveKit 适合作为 `voice-livekit` 插件的底层 SDK / runtime dependency，而不是 Shinar 的总基座。

```ts
interface VoiceSessionProvider {
  startSession(config: VoiceSessionConfig): Promise<VoiceSession>;
  stopSession(sessionId: string): Promise<void>;
  interrupt(sessionId: string): Promise<void>;
  onTranscript(handler: TranscriptHandler): Unsubscribe;
  onTurn(handler: TurnHandler): Unsubscribe;
  onMetrics(handler: VoiceMetricsHandler): Unsubscribe;
}
```

`voice-livekit` 插件内部可以处理：

- WebRTC room / participant / track。
- STT、LLM、TTS pipeline。
- realtime speech-to-speech model。
- turn detection。
- interruption / barge-in。
- streaming transcript。
- latency and cost metrics。

Core 只消费抽象后的 transcript、turn、interruption、latency 和 session events。

依赖示例：`shadowing` Pattern 可以要求 `voice.session` 或 `stt.transcribe` capability；实际 capability 可以由 `voice-livekit`、OpenAI Realtime adapter 或其他语音插件提供。

### Avatar / Live2D 插件

Avatar 插件负责表现层，不负责教学策略。Pattern 可以选择使用 avatar capability，但不应该直接绑定 Live2D 实现。

```ts
interface AvatarRendererPlugin {
  id: string;
  mount(target: HTMLElement, config: AvatarConfig): Promise<AvatarInstance>;
  speak(event: SpeechEvent): Promise<void>;
  setEmotion(emotion: AvatarEmotion): Promise<void>;
  dispose(): Promise<void>;
}
```

Live2D 可以作为 `avatar-live2d` 插件的实现细节。Core 不应该知道模型文件、表情参数或渲染引擎细节。

### Provider 插件

Provider 插件负责连接外部模型或服务：

- LLM provider: OpenAI-compatible、DeepSeek、local model gateway 等。
- STT provider: Deepgram、OpenAI transcription、AssemblyAI 等。
- TTS provider: Cartesia、ElevenLabs、OpenAI TTS 等。
- Importer provider: 字幕、文章、网页、PDF 或聊天记录导入。

Provider 插件必须把外部服务输出规范化为 core schema，不能把 provider 原始响应直接扩散到业务层。

## 插件权限

插件应声明能力和权限，至少包括：

- 是否需要网络访问。
- 是否读取用户学习材料全文。
- 是否接触音频流。
- 是否写入 review items。
- 是否调用外部模型服务。
- 是否需要密钥或用户级配置。

默认策略：插件只能访问它声明并被授权的能力。

## 事件边界

Session event log 是学习过程的事实来源。插件可以追加事件，但不能任意改写历史事件。

基础事件类型应包括：

- material.created
- material.analyzed
- session.started
- message.created
- feedback.created
- voice.transcript.partial
- voice.transcript.final
- voice.interruption.detected
- review.created
- session.completed

未来若插件需要自定义事件，应使用命名空间，例如 `voice-livekit.metric.recorded` 或 `pattern-shadowing.segment.completed`。

## Pattern 与 Plugin 的依赖关系

Pattern 依赖 capability，不依赖具体插件名。

```text
pattern-shadowing
  requires:
    - stt.transcribe >= 1.0
    - tts.speak >= 1.0
  optional:
    - avatar.render >= 1.0

voice-livekit plugin
  provides:
    - voice.session 1.x
    - stt.transcribe 1.x
    - tts.speak 1.x
    - telemetry.record 1.x

avatar-live2d plugin
  provides:
    - avatar.render 1.x
```

这让同一个 Pattern 可以在不同底层实现上运行：

- 文本版 `roleplay` 只需要 LLM capability。
- 语音版 `roleplay` 增加 voice capability。
- Live2D 版 `roleplay` 再增加 avatar capability。

## LiveKit 的位置

LiveKit 应进入 `voice-livekit` 插件，而不是进入 core。

```text
Shinar core
  -> VoiceSessionProvider contract
    -> voice-livekit plugin
      -> LiveKit Agents / LiveKit SDK / selected STT-LLM-TTS providers
```

这样做的好处：

- 保留未来替换为 OpenAI Realtime API、Gemini Live API、Pipecat 或其他实时语音方案的空间。
- 避免用 room / participant / track 这些实时通信概念污染学习领域模型。
- 复用已跑通的文本原型，通过可替换语音插件补齐正式 MVP 的核心语音路径。
- 让语音延迟、打断、首 token、首音频和成本指标独立评估。
- 让依赖语音的 Pattern 只声明 `voice.session` / `stt.transcribe` / `tts.speak`，不感知 LiveKit。

## DeepSeek Harness 的位置

DeepSeek Harness 可以作为参考对象或实验性 adapter，但不应成为 Shinar 的产品总基座。

可接受用法：

- 做 agent loop 和 tool plugin 的原型实验。
- 写一个 `dsh-plugin-shinar` 验证材料分析、对话练习和复盘插件。
- 借鉴 Cordis 风格的 service registry、lifecycle 和 reversible registration。

不建议用法：

- 让 Shinar 的核心数据模型依赖 DeepSeek Harness session event。
- 让产品 UI 直接绑定 Harness Web UI。
- 让学习 Pattern 只以 Harness tool 或 skill 的形式存在，缺少 Shinar 自己的 schema 和 capability requirements。

## MVP 策略

第一版复用现有文本闭环，优先验证“沉浸材料 → 话题 → 语音讨论 → 复盘”。插件架构只补齐这条路径所需的最小能力：

1. Core domain models and schemas。
2. LearningPattern contract。
3. Capability contract and requirement check。
4. LLM provider plugin contract。
5. Simple plugin registry。
6. Built-in topic discussion Pattern and optional guided roleplay。
7. Replaceable basic voice provider and failure fallback。
8. Mock LLM / voice providers for tests。

基础语音进入 MVP 关键路径；Live2D、连续实时双向语音和完整第三方插件生态作为后续增强。完整 registry 不作为接入首个语音 provider 的前提，先遵守稳定接口和必要的能力检查。

## 重新评估条件

当前产品已经明确以沉浸材料驱动语音输出，但这不自动要求更重的 voice subsystem。若后续连续实时会话、恢复和质量管理超出插件边界，再评估是否升级；无论采用哪个 SDK，都应服务于 Shinar 的学习核心。
