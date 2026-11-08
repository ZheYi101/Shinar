# Agent Core Architecture

## 核心定位

Shinar 的 agent 不负责自由规划任务；它负责执行可声明、可测试、可复盘的语言学习 Pattern。

当前产品主旨见 [Project Brief](../product/PROJECT_BRIEF.md)：沉浸提供语境，语音对话练输出。本文保留内核设计与既有文本原型经验；默认 Pattern 和交付优先级按话题讨论与基础语音调整，具体实现状态以代码为准。

项目需要手写的是一个领域化的 `Language Learning Agent Kernel`，而不是 Codex、Claude Code 或 DeepSeek Harness 那种通用 agent harness：

```text
Language Learning Agent Kernel
  把输入材料、练习 Pattern、用户回复、即时反馈、复盘项和复习计划
  组织成一条可追踪、可暂停、可恢复、可回放的学习闭环
```

底层 workflow runtime 可以采用 LangGraph；结构化 LLM 调用可以采用 PydanticAI 或轻量 Pydantic provider adapter；实时语音继续放在 `voice-livekit` 插件内。但这些都是实现层能力，不应该定义 Shinar 的学习语义。

## 为什么可以手写

Shinar 的问题域比通用 coding agent 或任务 agent 窄得多。用户和 AI 的主要交互不是“让 agent 自主解决任意问题”，而是在一个明确语境中完成语言练习：理解材料、输出句子、获得纠错、复述、沉淀复习项。

因此核心复杂度不在“agent 能否自主做任何事”，而在这些领域问题：

- 什么是一次学习会话。
- 什么是一次有效练习。
- 用户输入如何推进练习状态。
- 什么错误值得变成 `FeedbackItem`。
- 什么表达值得变成 `ReviewItem`。
- Pattern 需要哪些 capability。
- SessionEvent 如何记录可复盘的学习事实。

这些判断高度 Shinar 化，通用 agent 项目的代码最多只能提供结构参考，不能直接替代项目自己的领域内核。

## 灵活度放在哪里

Shinar 的灵活度应主要通过 Pattern 放开，而不是通过一个自由规划的大 agent 放开。

```text
Pattern -> PracticePlan -> AgentFlow -> SessionEvents -> FeedbackItems / ReviewItems
```

每个 Pattern 固定一种练习方式，例如：

- `topic-discussion`: 材料理解、话题选择、语音讨论与轻量复盘，作为默认入口。
- `roleplay`: 固定角色扮演对话流程。
- `retell`: 固定理解、复述、纠错、再复述流程。
- `shadowing`: 固定听、跟读、识别差异、重复练习流程。
- `socratic`: 固定提问式理解检查流程。
- `spaced-review`: 固定复习调度和回忆练习流程。
- `input-lesson`: 固定 Scene/Argument Capsule、目标选择、理解检查、易错改写、语境输出和 Profile Delta。
- `cora`: 固定 Cold attempt、Observe、Rebuild、Automate，用于训练已经理解但不能快速取出的口语表达。

Pattern 可以决定本次练习的语境、纠错强度、是否使用语音、什么时候结束、生成什么复习项和多久后复习。Kernel 负责执行 Pattern、检查 capability、调用 provider、写入事件；LLM 负责生成具体语言内容，但不拥有流程控制权。

## 实践校准后的学习闭环

从 `input-driven-language-coach` 和 EnglishLearningWorkflow 的使用记录看，Shinar 的 agent kernel 需要保护三条学习事实：

1. 输入必须先被整理成可教学材料。raw subtitle、raw transcript 和 cleaned lesson-ready text 在数据模型中不能混为一谈。
2. 用户输出才是学习证据。系统展示过解释、model answer 或 review item，不代表学习者已经掌握。
3. 不同学习现象需要不同 Pattern。输入材料学习、对话 roleplay、复述、summary-first review 和 CORA spoken retrieval 可以共享领域对象，但不应强制共享同一个流程模板。

因此 Agent Kernel 的职责不是“多调用几次 LLM”，而是把以下过程变成可追踪事件：

```text
select pattern
  -> build practice plan
  -> require learner output
  -> collect feedback evidence
  -> emit review candidates
  -> schedule or summarize future retrieval
```

相关依据见 [Learning Loop Foundation](../research/LEARNING_LOOP_FOUNDATION.md) 和 [Practice Workspace Findings](../research/PRACTICE_WORKSPACE_FINDINGS.md)。

## 可参考但不照搬

Codex、Claude Code、DeepSeek Harness 这类系统值得参考的是工程结构，而不是 agent loop 本身。

可以参考：

- event log / checkpoint 的思想。
- capability registry / plugin registry 的边界。
- context 压缩、摘要和恢复策略。
- provider adapter 的抽象方式。
- 工具或 provider 调用失败时的 fallback。
- 如何把运行过程变成可调试轨迹。

不应照搬：

- 面向任意任务的自由规划 loop。
- 让模型决定产品流程下一步做什么。
- 把学习 Pattern 降级成普通 tool 或 skill。
- 让外部 harness 的 session / tool / UI 概念进入 Shinar 的 core schema。

核心原则是：通用 agent 解决开放任务；Shinar agent 执行领域学习闭环。

## 推荐技术方向

```text
Language
  Python-first for core, agent kernel, plugins, and patterns

Domain schema
  Pydantic v2 models

Agent orchestration runtime
  LangGraph adapter as the first AgentEngine

Typed LLM calls
  PydanticAI or lightweight Pydantic-based provider adapter

API surface
  FastAPI candidate, not required for the first handwritten core

Voice plugin
  LiveKit Agents / LiveKit SDK inside voice-livekit plugin

Testing
  pytest, provider mocks, deterministic pattern fixtures
```

这样可以把手写部分控制在项目特有的学习语义和编排边界内，同时复用成熟的 workflow 和语音基础设施。

## 分层结构

```text
apps
  api
  web
  cli / dev playground

shinar.core
  domain models
  session events
  practice state machine
  feedback / review schemas
  pattern and capability contracts

shinar.kernel
  PatternRunner
  CapabilityRegistry
  AgentEngine protocol
  SessionCoordinator
  EventStore interface
  GraphCompiler

shinar.engine.langgraph
  LangGraphAgentEngine
  graph state mapping
  checkpoint adapter
  node wrappers

shinar.llm
  typed LLM call helpers
  structured output validation
  provider abstraction
  PydanticAI adapter candidate

shinar.plugins
  llm-openai-compatible
  voice-livekit
  avatar-live2d
  importer-subtitles

shinar.patterns
  roleplay
  retell
  shadowing
  socratic
  spaced-review
```

Dependency direction:

```text
core -> no framework dependency
kernel -> core contracts
engine.langgraph -> kernel protocols + LangGraph
llm adapters -> core schemas + provider SDKs
plugins -> core capability contracts
patterns -> core pattern contracts + declared capabilities
apps -> selected kernel, plugins, patterns, persistence
```

## Shinar 应手写的部分

### Core Models

这些对象属于 Shinar，不应该委托给 LangGraph、LiveKit 或 PydanticAI：

- `UserProfile`
- `LearningMaterial`
- `MaterialAnalysis`
- `PracticeSession`
- `Message`
- `SessionEvent`
- `PracticePlan`
- `PracticeInstruction`
- `FeedbackItem`
- `ReviewItem`
- `CapabilityRequirement`
- `PatternManifest`
- `PluginManifest`

### Agent Kernel

Agent Kernel 是手写胶水层，应保持小、明确、容易测试。

```python
class PatternRunner:
    async def create_plan(self, pattern_id, material, profile): ...
    async def handle_event(self, session_id, event): ...
    async def summarize(self, session_id): ...

class CapabilityRegistry:
    def register(self, provider): ...
    def require(self, capability: str, version: str): ...
    def get(self, capability: str): ...

class AgentEngine:
    async def start(self, flow, state): ...
    async def resume(self, session_id, event): ...
    async def stream(self, session_id, event): ...
```

Kernel 决定 Shinar 语义下必须发生什么；engine adapter 决定如何执行。

### Event Store Interface

Event store 应是 Shinar 自己的接口，而不是暴露给领域层的 LangGraph checkpoint 对象。

```text
append(event)
load_session_events(session_id)
load_latest_state(session_id)
rebuild_state(session_id)
```

LangGraph checkpoint 可以在内部使用，但持久化的产品事实应保持为 `SessionEvent` 和由它派生出的状态。

## 框架应承担的部分

### LangGraph

LangGraph 应承担：

- stateful workflow execution
- graph nodes and edges
- conditional routing
- streaming execution
- checkpoint / resume support
- human-in-the-loop pauses later

LangGraph 不应拥有：

- Shinar domain objects
- Pattern semantics
- plugin permission model
- review item schema
- user-visible learning history

### PydanticAI or Provider Adapter

PydanticAI 适合 typed LLM calls 和结构化输出校验。

可用于：

- material analysis output
- practice instruction generation
- feedback item extraction
- review draft generation
- output validators and retry-on-invalid-output behavior

内部仍应保留 `LLMProvider` / `TypedLLMClient` 边界，保证未来可以替换 PydanticAI。

### LiveKit

LiveKit 保持在 `voice-livekit` 插件内部。

可用于：

- realtime audio transport
- turn detection
- interruption / barge-in
- STT-LLM-TTS pipeline
- streaming transcript and metrics

不要让 LiveKit 的 room、participant、track 概念泄漏进 `PracticeSession`。

## Agent Flow Model

Agent Kernel 应把 `PracticePlan` 编译为 `AgentFlowDefinition`。

```python
class AgentFlowDefinition(BaseModel):
    id: str
    pattern_id: str
    required_capabilities: list[CapabilityRequirement]
    initial_state: PracticeState
    steps: list[AgentStepDefinition]
```

LangGraph adapter 再把这个定义映射为 graph。

典型 graph nodes：

```text
load_context
check_capabilities
select_pattern_step
build_prompt
call_llm
validate_output
call_capability
emit_message
emit_feedback
update_pattern_state
wait_for_user_event
summarize_session
emit_review_items
```

Graph 是实现细节。稳定 contract 是 flow definition 和被写出的 session events。

## Session State

`PracticeAgentState` 应是 Core 或 Kernel 持有的 Pydantic model。

```python
class PracticeAgentState(BaseModel):
    session_id: str
    material_id: str
    pattern_id: str
    profile_snapshot: UserProfile
    material_analysis: MaterialAnalysis | None
    pattern_state: dict
    recent_messages: list[Message]
    pending_instruction: PracticeInstruction | None
    pending_feedback: list[FeedbackItem]
    pending_review_items: list[ReviewItem]
    available_capabilities: list[str]
    metrics: dict
```

State 应包含执行所需快照；持久历史应尽量从 `SessionEvent` 重建。

## Default Pattern: Topic Discussion

复用已有文本 runner，优先形成 `topic-discussion`：AI 理解沉浸材料、推荐话题，用户选择、修改或自提话题，再进入语音讨论。`guided-roleplay` 由用户主动选择，共享语境和证据对象；不要求用户先进入角色或完成课程。

必需能力：

```text
llm.generate >= 1.0
voice.session >= 1.0
```

可选能力：

```text
stt.transcribe >= 1.0
tts.speak >= 1.0
avatar.render >= 1.0
```

流程：

```text
material analysis
  -> grounded topics and opening questions
  -> learner selects or proposes a topic
  -> AI opens discussion (roleplay only if selected)
  -> learner replies
  -> AI responds in context
  -> optional correction event
  -> end condition
  -> review draft
```

这些 capability 是目标示意，具体语音 contract 仍需根据最小实现确定。基础语音可以轮流说话；仅文本流程用于原型或回退，不代替正式语音 MVP 验收。用户选择 roleplay 时增加场景和角色设定，自然讨论不要求角色设定。

## First Plugin: LLM Provider

现有 LLM provider adapter 继续作为材料理解、话题生成和对话的基础；随后通过可替换 voice provider 补齐核心语音路径。

```text
plugin: llm-openai-compatible
provides:
  - llm.generate 1.x
  - llm.structured 1.x
```

Provider 应支持：

- model name config
- base URL config
- API key from environment
- structured output when available
- fallback JSON repair / validation retry
- usage and latency metrics

它支撑文本原型、provider mock 和早期 Patterns，但正式 MVP 还必须完成话题选择和基础语音路径。

## Discovery Mechanism

Python 版本建议先用代码显式注册。等第一批 first-party plugins 跑通后，再加入 package entry point discovery。

MVP 注册方式：

```python
registry.register_plugin(OpenAICompatiblePlugin(config))
registry.register_pattern(RoleplayPattern())
```

后续 package discovery：

```text
shinar.plugins
shinar.patterns
```

通过 Python package entry points 实现。

## Persistence Strategy

推荐拆分：

```text
SessionEvent store
  product truth, replayable learning history

LangGraph checkpoint store
  engine resume / internal workflow recovery

Derived tables
  fast reads for sessions, feedback, review queue, dashboard
```

不要把 LangGraph checkpoint 当作唯一持久学习记录。

## Testing Strategy

先做 deterministic tests，再做 provider integration tests。

- Core schema tests: model validation 和 migration assumptions。
- Pattern tests: 给定 material + events，产出预期 instruction / review draft shape。
- Capability registry tests: dependency resolution 和 missing capability errors。
- Agent kernel tests: event in, event out, no provider calls。
- LangGraph adapter tests: simple flow resumes 并写出预期 events。
- LLM adapter tests: provider mock、invalid structured output retry、usage metrics。

## MVP Implementation Order

1. Core Pydantic models and event types.
2. Capability contract and registry.
3. Pattern contract and `roleplay` Pattern.
4. LLM provider contract with mock provider.
5. Agent Kernel without LangGraph: direct deterministic runner for one flow.
6. LangGraph adapter for the same flow.
7. Event store interface with in-memory implementation.
8. SQLite/Postgres implementation after the in-memory loop is stable.
9. PydanticAI adapter or lightweight provider implementation.
10. `voice-livekit` plugin only after text session semantics are stable.

Direct deterministic runner 是有意设计的临时层。它能在 LangGraph 进入之前，让第一版手写核心更容易理解和测试。

## Reopen Conditions

如果出现以下情况，应重新评估该架构：

- Patterns become mostly free-form autonomous agents instead of structured learning flows.
- Voice becomes the primary product surface before text learning semantics stabilize.
- LangGraph adapter requires domain compromises or leaks graph-specific state into Core.
- PydanticAI provider behavior blocks multi-provider support.
- Event replay becomes too slow or too complex for normal session recovery.

## 外部参考

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph graph API: https://docs.langchain.com/oss/python/langgraph/graph-api
- PydanticAI agents: https://pydantic.dev/docs/ai/core-concepts/agent/
- PydanticAI structured output: https://pydantic.dev/docs/ai/core-concepts/output/
- LiveKit Agents: https://docs.livekit.io/agents/
- DeepSeek Harness: https://www.deepseek.com/harness/en/
