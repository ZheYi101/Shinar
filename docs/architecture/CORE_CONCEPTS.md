# Core Concepts

本文档解释 `src/shinar/core` 里最基础的业务对象和 Python / Pydantic 写法。它面向刚开始写 core 的项目参与者，帮助大家理解为什么这些概念需要存在，而不是只记住代码长什么样。

## Core 的边界

Core 负责定义 Shinar 的稳定学习语义。这里应该放项目长期会依赖的业务对象和协议，例如学习材料、练习会话、消息、反馈、复习项、事件、Pattern contract 和 capability contract。

Core 不应该直接绑定 LangGraph、LiveKit、OpenAI SDK、数据库 ORM 或前端框架。那些工具属于 adapter、plugin 或 app 层。这样做的目标是：以后替换 workflow runtime、LLM provider 或存储层时，不需要重写学习数据模型。

## Core、Kernel 和 Adapter 的区别

可以把三层理解为名词、动词和运行方式：

```text
core
  定义 Shinar 世界里的稳定名词和协议：材料、片段、会话、消息、反馈、复习项、事件、Pattern、Capability、Provider contract。

kernel
  定义这些对象如何协作完成一次学习动作：开始会话、选择 Pattern、检查 capability、调用 provider、处理用户消息、写入事件、生成复习项。

adapter / plugin
  定义外部工具如何接入：LangGraph 怎么跑流程、OpenAI-compatible provider 怎么生成内容、SQLite 怎么存事件、LiveKit 怎么处理语音。
```

所以 `kernel` 不是 `core` 的普通实现类。它依赖 core 的对象和协议，但表达的是 Shinar 的流程规则。一个简单判断规则是：

- 换掉 LangGraph、OpenAI、SQLite 后仍然成立的业务对象，放 `core`。
- 描述“收到用户回答后下一步应该做什么”的流程，放 `kernel`。
- 描述“某个框架或 SDK 具体怎么接入”的代码，放 `engine`、`providers` 或 `plugins`。

这也是为什么 `domain.py` 在后端项目里不只是前端常见的 `types/` 文件。它不仅提供类型提示，还定义产品承认的学习事实和校验规则。

## Agent 的定位

Shinar 的 agent 不负责自由规划任务；它负责执行可声明、可测试、可复盘的语言学习 Pattern。

这和通用 coding agent 或任务 agent 不一样。Shinar 的用户交互基本围绕学习材料和练习语句展开，系统需要解决的是一套专一的 language learning loop：输入理解、任务化对话、即时纠错、复述输出和间隔复习。

因此项目应该手写领域化的 agent kernel，而不是手写通用 agent harness。灵活度主要由 Pattern 提供：不同 Pattern 决定练习模式、语境、纠错策略、语音或打字、结束条件和复习节奏。Kernel 负责执行这些 Pattern，并把过程记录成稳定的领域对象和事件。

可以参考 Codex、Claude Code 或 DeepSeek Harness 的 event log、checkpoint、capability registry、context 管理和 provider adapter，但不应该照搬它们的自由规划 agent loop。

## 文件拆分原则

初始化阶段可以把核心对象暂时放在一个 `domain.py` 中，方便快速看清对象之间的关系。但当文件继续增长时，应按业务边界拆分，而不是按类数量机械拆分。

推荐演进方向：

```text
src/shinar/core/
  base.py          # DomainModel, utc_now, new_id
  enums.py         # MessageRole, SessionStatus, FeedbackType 等枚举
  materials.py     # LearningMaterial, MaterialAnalysis
  sessions.py      # PracticeSession, Message, SessionEvent
  feedback.py      # FeedbackItem
  review.py        # ReviewItem
  patterns.py      # PracticePlan, PracticeInstruction, PatternManifest
  capabilities.py  # CapabilityRequirement, PluginManifest
  ports.py         # Protocol / interfaces
  __init__.py      # 对外统一导出稳定 API
```

拆分时保持一个原则：业务上一起变化的对象放在一起。例如 `LearningMaterial` 和 `MaterialAnalysis` 可以同文件；`FeedbackItem` 和 `ReviewItem` 虽然相关，但生命周期不同，后面可以分开。

## DomainModel

`DomainModel` 是 Shinar 自己的项目级 Pydantic 基类：

```python
class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

`BaseModel` 来自 Pydantic。继承它之后，业务对象会获得字段校验、默认值、序列化、复制和反序列化能力，例如 `model_dump()`、`model_validate()` 和 `model_copy()`。

`model_config` 是 Pydantic v2 识别的模型配置类属性。`ConfigDict(extra="forbid")` 表示不允许传入模型没有声明的字段。

例如：

```python
LearningMaterial(
    title="Market trip",
    target_language="English",
    native_language="Chinese",
    content="Yesterday I went to the market.",
    unexpected="value",
)
```

这里的 `unexpected` 字段不在模型定义里，因此会触发校验错误。这对 Shinar 很重要，因为 LLM 结构化输出和用户学习数据都应该尽早暴露 schema 漂移问题，不应该静默吞掉未知字段。

把配置集中到 `DomainModel` 的好处是，所有继承它的领域对象都会共享同一套规则。以后如果需要统一调整 datetime 序列化、赋值校验或 JSON schema 行为，只需要改项目级基类。

## ID 生成

当前 core 里用 `new_id(prefix)` 生成可读 ID：

```python
def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
```

`uuid4()` 生成一个随机 UUID。标准 UUID 字符串通常长这样：

```text
550e8400-e29b-41d4-a716-446655440000
```

`.hex` 会把中间的连字符去掉，得到 32 个十六进制字符：

```text
550e8400e29b41d4a716446655440000
```

加上前缀后，最终 ID 类似：

```text
session_550e8400e29b41d4a716446655440000
feedback_550e8400e29b41d4a716446655440000
```

前缀不是为了安全，而是为了调试和阅读事件流时更清楚。看到 `review_...` 就能知道这是复习项，看到 `msg_...` 就能知道这是消息。

## `from __future__ import annotations`

`from __future__ import annotations` 会让 Python 延迟解析类型注解。

它解决的问题是：领域模型之间经常互相引用，或者某个类型在文件后面才定义。如果不延迟解析，Python 在定义类时可能找不到后面才出现的类型。

例如：

```python
class PracticeSession(DomainModel):
    messages: list[Message]

class Message(DomainModel):
    content: str
```

启用延迟注解后，类型注解会先以较宽松的方式保存，后续再解析。对于 Pydantic model、复杂类型和未来可能出现的循环引用，这能减少类型声明顺序带来的摩擦。

## 关键领域对象

`LearningMaterial` 表示用户导入的学习材料，包括标题、目标语言、母语、正文、来源类型和可选的材料分析结果。它是学习闭环的起点。

`MaterialAnalysis` 表示对材料的结构化理解，例如摘要、关键词、表达点、难点和推荐练习目标。它后续会由 material analysis pipeline 生成。

`PracticePlan` 表示一次练习的计划。它来自 Pattern，包含练习标题、步骤和所需 capability。它回答的是“这次怎么练”。

`PracticeInstruction` 表示练习中的一个具体指令，例如“请用目标语言复述这段材料”或“你来扮演点餐顾客”。

`PracticeSession` 表示一次正在进行或已经完成的练习会话。它聚合当前状态：材料 ID、Pattern、难度、消息、反馈项、复习项和计划。

`Message` 表示会话中的一条消息。消息有角色，例如 user、assistant 或 system，也可以关联反馈项。

`FeedbackItem` 表示一次纠错或表达建议。它应该能关联到原始用户消息，方便之后解释“这个错误从哪里来”。

`ReviewItem` 表示后续复习项。它可以是完形填空、改写、回忆或表达积累。`cloze` 指完形填空 / 挖空练习，例如 `Yesterday I ___ to the market.`。

`SessionEvent` 表示学习会话中发生过的一条事实。它不是当前状态，而是历史记录中的一个事件，例如会话开始、用户发言、AI 回复、创建反馈、创建复习项。

## Provider

`LearningLLMProvider` 是 core 依赖的 LLM 能力接口。它不是某个具体模型，也不是某个 SDK，而是一组 Shinar 需要的业务能力：

```python
class LearningLLMProvider(Protocol):
    async def generate_task(...): ...
    async def generate_reply(...): ...
    async def correct_answer(...): ...
    async def create_review_items(...): ...
```

这里用 `Protocol` 是为了结构化约束：只要一个对象实现了这些 async 方法，它就可以被当作 `LearningLLMProvider` 使用。这样 core 不需要直接依赖 OpenAI、DeepSeek、PydanticAI 或 LangChain。

函数参数里的单独 `*` 表示后面的参数必须用关键字传参：

```python
await provider.generate_task(
    material_text="Yesterday I went to the market.",
    learner_level="A2",
    target_language="English",
)
```

不能写成：

```python
await provider.generate_task("Yesterday I went to the market.", "A2", "English")
```

这能避免多个字符串参数被传错位置。LLM 调用里的参数通常同为 `str` 或结构化对象，强制关键字传参更清楚，也更安全。

## EventStore

`EventStore` 是保存和读取 `SessionEvent` 的接口：

```python
class EventStore(Protocol):
    async def append(self, event: SessionEvent) -> None: ...
    async def append_many(self, events: list[SessionEvent]) -> None: ...
    async def list_session_events(self, session_id: str) -> list[SessionEvent]: ...
```

它不是具体数据库。现在可以有 `InMemoryEventStore`，以后可以换成 `SQLiteEventStore`、`PostgresEventStore` 或文件存储实现。业务 runner 只依赖接口，不关心事件到底存在哪里。

Shinar 需要 EventStore，是因为产品关注的是可复盘学习闭环，不只是最后一条 AI 回复。一次会话中发生过的事件包括：

- `session.started`: 会话开始。
- `message.user_added`: 用户输入了一条消息。
- `message.assistant_added`: AI 回复了一条消息。
- `feedback.created`: 系统生成了纠错或表达建议。
- `review_items.created`: 系统生成了复习项。
- `session.completed`: 会话结束。

可以这样理解：`PracticeSession` 是当前状态，`SessionEvent` 是发生过的事实，`EventStore` 是保存这些事实的地方。

## Pattern、Plugin 和 Capability

`Pattern` 回答“怎么学”，例如 roleplay、retell、shadowing 或 spaced review。

`Plugin` 回答“能做什么”，例如 LLM 生成、语音转文字、文字转语音、材料导入或 avatar 渲染。

`Capability` 是 Pattern 和 Plugin 之间的契约。例如 roleplay 需要 `llm.generate >= 1.0`，至于这个能力来自 OpenAI-compatible provider、DeepSeek provider 还是本地模型，对 Pattern 来说不重要。

这种分离能避免把学习流程写死到某个 provider 或 SDK 上，也能让后续语音、Live2D、导入器等能力作为插件加入。

## LangGraph 的位置

LangGraph 应该在 `shinar.engine.langgraph` 里作为 runtime adapter，而不是进入 `shinar.core`。

Core 定义稳定对象和协议；Kernel 负责把学习语义组织成可执行流程；LangGraph adapter 负责用 LangGraph 的 state、node、edge、checkpoint 等机制执行流程。

这样即使以后不用 LangGraph，或者需要多一种 direct runner / test runner，Core 里的学习材料、会话、反馈和复习项仍然可以保持不变。

## 当前实现阶段

当前实现属于早期 core scaffold。它应该优先追求对象边界清楚、能跑通一条学习闭环、能替换 provider 和 event store，而不是一次性做完整框架。

接下来建议的业务代码顺序：

1. 把 `domain.py` 按业务边界拆成多个文件。
2. 实现 `CapabilityRegistry`，让 Pattern 通过 capability 声明运行条件。
3. 实现第一个内置 `GuidedRoleplayPattern`，让 `PracticePlan` 从 Pattern 生成，而不是写死在 runner 里。
4. 保留 direct runner，等语义稳定后再让 LangGraph adapter 承担更复杂的流程编排。
5. 再补测试，优先覆盖 provider mock、event 写入、session 状态演进和 review item 生成。
