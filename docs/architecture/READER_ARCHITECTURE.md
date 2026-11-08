# 原文阅读器架构与维护契约

对应 [Decision 0036](../decisions/TECH_DECISIONS.md#decision-0036)。本文维护当前边界和后续演进条件；使用／备份见[阅读器指南](../desktop/READER.md)，引擎选择依据见[选型研究](../research/READER_ENGINE_SELECTION_2026-11-06.md)，验证结论见[集成记录](../validation/engineering/READER_INTEGRATION_2026-11-06.md)。

## 范围与事实来源

阅读器服务已有“展开原文 → 指向章节／选句 → 在同一会话讨论”的交互。当前只对可精确对应的可重排 EPUB 启用 foliate-js；其余格式与失败情况保留原生文本回退。WebEngine 是局部显示依赖，应用主壳、对话编排和数据持久化继续使用原架构。

来源事实始终是已保存的规范化 `LearningMaterial.content`、内容哈希和 Python 字符区间 `[start, end)`。坐标按 Unicode 字符计数；DOM／Qt 的 UTF-16 单位必须在边界转换。EPUB CFI、目录 href、页码和滚动像素不能替代来源区间，重复内容也不能靠 `find(quote)` 定位。

三个对象具有不同生命周期：受管 EPUB 是需备份的用户原件；静态显示 EPUB 是可重建的范围投影；浏览器 profile／DOM 是临时显示状态。重建后两者不修改规范化内容、业务缓存键或历史消息。显示格式标识 `DISPLAY_VERSION` 与来源索引标识 `source-view-v1` 属于不同语义；若后续持久化显示缓存，其键必须包含显示版本、内容哈希与范围。改变规范化或来源坐标需独立兼容决策。

## 当前模块与依赖

| 模块 | 所有权 | 不承担的职责 |
| --- | --- | --- |
| `infrastructure/material_import.py` | 捕获原 EPUB 字节；沿用既有 spine 提取和规范化 | 书页展示、授权、会话状态 |
| `infrastructure/epub_reader.py` | 原子保存／加载原件；静态 HTML 投影；nav／NCX 到来源坐标；`ReaderBook` | Qt、模型、数据库会话或用户界面文案 |
| `application/source_document.py` | 通用来源章节、段落、哈希及 UTF-16 转换 | EPUB 引擎或浏览器状态 |
| `application/learning_workbench.py` | 导入业务入口与原件保存时机；提供所属存储的资产目录 | DOM、WebEngine profile、浏览器定位 |
| `desktop/workspace.py` | 当前范围、选段、历史预览、加载代际与 UI 状态；冻结发送来源 | 新的格式解析器、浏览器资源策略或第二套会话业务 |
| `desktop/reader_runtime.py` | 临时 profile、文件白名单、专用 `ReaderBridge` | 解析、任意文件 API、业务持久化 |
| `qml/components/SourceReader.qml`、`FoliateSurface.qml` | 视图选择、工具与弹层、懒加载、主题／尺寸、加载超时与回退 | 书籍解析、授权和消息提交规则 |
| `desktop/reader/reader.js`、`index.html` | foliate 包装、样式、DOM ↔ 来源坐标、导航与位置事件 | 学习事实、模型 prompt、数据库或原件路径 |
| `desktop/reader/foliate/` | 固定提交的第三方解析／布局引擎 | Shinar 产品逻辑 |

允许 `epub_reader.py` 复用同层导入器的公开规范化／HTML 提取接口，保持新旧文本逐字对应；不再复制另一套清洗规则。WebEngine 的 Python 依赖只位于桌面装配入口与 `reader_runtime.py`，QML 依赖只位于 `FoliateSurface.qml`。业务层和格式适配器不得反向依赖这些模块。

`ReaderWorkspace.loadSource()` 保管当前／历史状态和代际；无 Qt 的 `application/source_loading.py` 按 `SourceLoadRequest` 返回章节、显示书籍和错误码，原件读取／投影运行在受管进程。
Workspace 与阅读职责基类属于同一个 QObject，路由、阅读状态和桥接仍有唯一所有者。
Workbench 仍通过具体存储路径推导资产目录；新增资产生命周期功能前再收敛该存储耦合，不提前引入通用 asset repository。

## 加载与失效流程

1. 导入时捕获原件快照，原子保存到所属数据库旁的 `<数据库名>.assets/sources/<内容哈希>.epub`，再走原有材料用例。原件路径不进入缓存键；相同内容复用原有材料与历史。
2. 工作区确定材料、会话冻结的授权末尾、当前章节和请求代际。范围编辑页可浏览整本来定位；聊天只允许当前授权前缀，不以页面可见性代替授权。
3. 后台读取受管副本；旧材料可从原路径补读。适配器按原导入规则重新提取，必须与保存文本完全一致；否则回退。ZIP／文件处理不在 Qt 主线程中执行。
4. 生成只含允许范围静态正文的显示 EPUB，记录每个文本 span 的 Python 来源区间。聊天不暴露未读正文或未读目录入口；头部标题按旧规范化占位，但不重复显示。显示原件与完整受管原件分开。
5. 后台结果通过既有请求门禁回到主线程；只有当前材料／请求仍匹配才装载。按需创建 WebEngineView，桥接对象先注册，再加载带随机文档身份的本地页面。
6. 每次页面请求由 Python 复核文档身份、代际、路由和字符范围。加载新文档、换线程、导航、关闭后旧事件不再生效；取消后台任务不替代失效校验。
7. 引擎失败或超时切到文本回退，保留会话、草稿、已读授权和来源历史。只有用户显式保存范围、确认发送等业务动作才能持久化对应事实。

所有 QObject／profile 和 QML 修改留主线程；后台仅传递普通数据与字节。阅读位置由工作区按线程保存于现有内存状态，不承诺跨设备或跨重启同步。历史预览既不覆盖当前选段，也不写当前阅读位置。

## WebChannel 契约

只向页面注册 `ReaderBridge`，不注册 workspace／viewmodel。当前操作如下；增加操作时必须更新本表、Python／JS 两端、身份门禁与测试。

| 页面 → Python | 参数与结果 | 语义 |
| --- | --- | --- |
| `document(identity)` | 返回 JSON 描述；失效返回 `{}` | 获取当前范围的显示 EPUB 与定位信息，不返回原件路径 |
| `select(identity, start, end, kind)` | `kind` 仅 `text`／`paragraph` | 请求当前选段；引文由 Python 从规范化原文截取 |
| `location(identity, position)` | Python 字符位置 | 更新当前线程阅读位置；历史预览不写入 |
| `ready(identity)`／`failed(identity)` | 文档身份 | 加载成功通知／文本回退，不改变业务 ready 状态 |
| `find(identity)` | 文档身份 | 打开既有 QML 原文查找 |

文档描述的字段：`identity`、`epub`（base64 显示副本）、`chapters`（`href/start/end`）、`language`、`start/end`、`position`、可空 `target`、`boundary`（无标记为 -1）和边界文案 `boundaryLabel`。失效时不得返回任何旧显示字节。Python → 页面只调用适配层提供的主题、定位和边界接口，动态参数经 JSON 序列化或类型约束，不能拼入用户脚本。

这是包内版本一致的私有协议，当前没有独立网络 API 或跨版本客户端兼容承诺。增加并行客户端、持久化书签／显示缓存或更换引擎前，先提炼有类型的文档结果与协议；坐标、失效和授权规则仍保持由 Python 管理。不要暴露通用 `invoke(method, args)`、任意路径读写、`eval` 或模型调用接口。

## 内容与故障边界

受管原件原样保存；显示副本去除脚本、事件属性、远程资源、出版者 CSS 和不支持的主动内容。资源白名单、临时 off-the-record profile、导航／下载限制与 CSP 共同约束显示环境。引擎只读取随包页面和经桥接传入的显示副本；不直接读取用户 EPUB 路径，不使用 CDN 或本地 HTTP 服务。

| 情况 | 处理 |
| --- | --- |
| 非 EPUB、受管与旧原路径均无原件 | 使用规范化文本；不调用模型补建原件 |
| 规范化不符、固定版式、损坏 ZIP／XML 或超限 | 文本回退；不替换历史原文、不标记解析成功 |
| QML／页面／引擎失败或加载超时 | 局部回退，既有聊天可继续 |
| 旧文档请求、越界／错误种类选区 | 拒绝，不写当前状态 |
| 历史来源版本／哈希不匹配 | 保留历史快照引用，不把当前 DOM 冒充旧来源 |

当前只支持单章滚动及目录跳转。复杂出版者版式、SVG、未索引外置注释、整本无缝滚动和独立字号设置仍是后续范围；不能因为 foliate 上游有能力就宣称应用已接入。

## 防止职责继续堆叠的演进顺序

来源加载与阅读状态的第一步收敛已在本轮治理完成；后续扩展继续按下列门槛验证，不为完成抽象而重写全库。

| 优先级与触发条件 | 目标职责 | 验收条件 |
| --- | --- | --- |
| 已落实基础边界；新增格式／引擎时继续遵守 | 无 Qt 的来源加载入口与有类型结果；受管进程产出文档、章节、范围和错误码，workspace 应用状态与本地化 | 精确映射、旧材料回退、跨章定位与晚到结果不变；单测无需 WebEngine |
| 已归入 ReaderWorkspace；新增持久进度前继续验证 | 同一 QObject 的阅读职责管理状态／加载身份；新增书签、持久化另立契约 | 当前／预览／待保存三类状态隔离；发送快照仍由现有业务入口冻结 |
| P2：新增原件删除、导出、第二种资产或第二个存储后端前 | 定义必要的资产保存／读取／缺件语义，去掉业务对 SQLite 路径形状的假设 | 重复材料共用资产时不会误删，迁移、恢复和缺件回退都有测试；不先引入通用插件平台 |
| 发行前：新引擎／Qt 或显示格式版本 | 核验上游差异、协议、资源、许可证和实际分发 | 位置／范围、可见窗口、wheel 与相应 ZIP／安装器分别验证 |

若扩展中出现重复授权判断、UI 层解析 ZIP、JS 保存会话或 vendor 中的产品补丁，应先收敛职责再添加功能。新后端使用既有来源／会话契约，不复制第二套坐标、搜索、预算或消息持久化流程。

## 上游管理与检查

`foliate/UPSTREAM.json` 是固定提交、文件哈希和附带许可证的清单。产品修改只在外围适配层；若确需上游补丁，须在决策中写明原因、补丁来源／差异、升级退出条件与验证，不能直接修改 JS 后仅更新哈希来掩盖分叉。

升级流程：查看当前锁定提交到目标提交的 API／资源／安全差异 → 更新必要模块、pin 和全部许可／哈希 → 跑架构与映射／工作区测试 → 跑可见窗口交互 → 构建 wheel 并检查资源 → 对要发行的 Windows 实际产物运行分发探针。PySide6 仍使用项目锁定版本；完整安装器未重建时明确标记未更新。

- 普通 pytest 中的架构检查拒绝来源处理依赖 Qt／业务 adapter、WebEngine 依赖扩散与 vendor 文件／许可漂移。它只检查静态导入与文件，不替代运行时内容安全或授权测试。
- `tests/infrastructure/test_epub_reader.py` 验证文本位置、重复句、Unicode／ruby、裁剪、静态化和原件恢复；`tests/test_reader_workspace.py` 验证选择、历史、跨章与过期请求。
- `scripts/validate_reader_workspace.py` 使用独立库和合成材料，检查窗口输入、复制、发送、历史与三语明暗／窄窗，并验证正文像素；不是用户真实 EPUB 或真实 AI 验收。
- `scripts/check_wheel_resources.py` 检查随包页面、字体、许可、上游哈希与隔离 QML；`scripts/check_windows_distribution.py` 另查 QtWebEngineProcess、Chromium／ICU／locales 和模块。静态通过不代表发行包、长期 GPU 使用或复杂书籍已验收。

完整系统边界见[架构总览](./ARCHITECTURE.md)，变更要求见 [AGENTS](../../AGENTS.md) 和 [CONTRIBUTING](../../CONTRIBUTING.md)。
