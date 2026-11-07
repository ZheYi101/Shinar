# 原文对照阅读器：引擎选型与嵌入验证

2026-11-06。本文记录初始选型与独立小样。用户随后授权更换，现已接入正式 EPUB 阅读区；实际实现和限制以[阅读器指南](../desktop/READER.md)与[集成记录](../validation/engineering/READER_INTEGRATION_2026-11-06.md)为准。下文“接入方案／交付条件”保留当时的设计，不能作为全部实现的声明。

## 结论

首选验证路线是 **Qt Quick `WebEngineView` + 固定提交的 foliate-js**。复用它的 EPUB 解析、章节导航、重排和位置表示，LinguaLoop 负责现有“展开原文 → 点段落／选句 → 在同一对话讨论”的交互连接。这里的 sidebar 指聊天旁的原文对照区；左侧材料／对话导航仍由现有 QML 管理。

这次需求属于 [MVP 已有的读后对照功能](../product/MVP_SPEC.md)，不是把产品改为完整阅读软件。字号、行宽、行距、配色和少量工具仍需要项目定制；下载引擎不会自动带来完整、定稿的产品界面。段落长度应尊重原文，改善的是结构保留、段间距与重排，不把正文机械切成等长块。

## 当前实现的问题

- `infrastructure/material_import.py` 的 `_read_epub()` 按 spine 读取 XHTML，再用 `_ReadableHTML` 输出纯文本；原 EPUB 的样式、链接目标、图片和大部分语义结构没有留给阅读器。章节标签主要从 h1–h3 抽取，未使用 EPUB 的 nav／NCX 目录。`raw_content` 对 EPUB 也是抽出的文字，不是原 EPUB 文件。
- `desktop/qml/components/SourceReader.qml` 用一个 `TextEdit.PlainText` 展示原文，默认 18／20px，正文跟随整个面板宽度，没有书页行宽上限、独立行距或章节排版。40,000 字符分块是加载策略，不是书籍排版结构。
- 当前原文选择和聊天快照已经使用规范化文字的位置；这些位置不能直接换成 EPUB 页码或百分比。

截图中连续的 Ten／Eleven 等短行**可能是书内目录被当成正文**；代码能确认存在结构丢失，但本轮没有读取用户的 EPUB 或实际数据库，不能据此断言该书的具体结构问题。

## 候选比较

| 候选 | 官方资料可确认的能力与限制 | 本项目判断 |
| --- | --- | --- |
| [foliate-js](https://github.com/johnfactotum/foliate-js) | 原生 ES modules；EPUB／目录／重排／选区位置；MIT。已经用于 Foliate 稳定版，但库自身明确没有稳定 API／正式 release。demo 界面也不完整 | 首选做嵌入；固定 commit，只依赖窄接口 |
| [epub.js](https://github.com/futurepress/epub.js) | EPUB 渲染、分页、滚动、内容 hooks；Free BSD；压缩 EPUB 需要 JSZip | 可行备选；没有证据证明它在本项目中比 foliate-js 更快或更美观，本轮未做同条件比较 |
| [Readium Web](https://www.edrlab.org/software/readium-web/) | 分离的客户端／publication server；客户端消费 Web Publication，而非直接处理 EPUB | 适合更完整的出版物基础设施；当前本地材料对照区引入成本较高 |
| [Readest](https://github.com/readest/readest) | 完整阅读应用，Next.js／Tauri，提供目录、主题、批注与多种阅读模式 | 可参考成熟产品的排版和工具安排；不是可以直接塞入 QML 的现成控件 |

以上“首选”是结合现有 Python／Qt 架构的工程判断，不是跨引擎性能排名。不要把完整 Foliate／Readest 应用连同其书库、账户和同步系统搬进本项目。

## 本机小样证据

本机 PySide6 为 6.11.1，`QtWebEngineQuick` 和 `QtWebChannel` 均可导入。小样实际使用 QML `WebEngineView`，不是在外部浏览器里渲染后声称 Qt 已通过。

- 上游仓库：`https://github.com/johnfactotum/foliate-js`。
- 本次 checkout：`78914aef4466eb960965702401634c2cb348e9b1`。
- 脚本：[probe_reader_engine.py](../../scripts/probe_reader_engine.py)。仅生成合成 EPUB，用随机端口的 `127.0.0.1` 临时静态服务提供小样资源，结束即关闭；WebEngine 使用临时 profile。
- 中日文显式用 CSS `@font-face` 加载仓库已有 Noto Serif SC／JP。仅调用 Qt `QFontDatabase` 不足以证明 WebEngine 已使用这些字体。
- 小样设置正文 20px、行高 1.8、最大行宽 680px、段间距 0.85em；这些是验证默认值，不是最终视觉定稿。

| 场景 | 视口 | 真实章节／8 个独立段落 | 文字选区 → CFI → 原选区 | 含中文／日文／emoji 的位置往返 | 横向溢出 |
| --- | --- | --- | --- | --- | --- |
| 英文浅色 | 1120 × 840 | 通过 | 通过 | 通过 | 无 |
| 英文浅色窄窗 | 520 × 840 | 通过 | 通过 | 通过 | 无 |
| 中文浅色 | 840 × 840 | 通过 | 通过 | 通过 | 无 |
| 中文深色 | 840 × 840 | 通过 | 通过 | 通过 | 无 |
| 日文浅色 | 840 × 840 | 通过 | 通过 | 通过 | 无 |
| 日文深色窄窗 | 520 × 840 | 通过 | 通过 | 通过 | 无 |

六组均生成截图并检查版面。CFI 是 EPUB 的内容定位信息，可表达实际文本位置；这里检查的是程序构造的文本节点 Range 往返，**不是鼠标拖选／键盘可用性验收，也尚未映射到 LinguaLoop 的字符快照**。初次用元素边界的 Range 进行往返未保留整段文字，随后改为文本节点边界并通过；正式适配须覆盖两种 DOM Range 端点，不假设所有选区都落在文本节点上。

这是离屏技术验证。运行仍出现 Chromium 的 GLES 共享上下文错误日志，但实际六张画面成功生成；不能据此宣称实际窗口 GPU 渲染、性能、显存与安装包已验收。没有启动正常应用，没有使用实际学习数据，没有模型调用。

复现（首次准备 clone 后 checkout 固定提交；不要把已有 clone 当作新目录覆盖）：

```powershell
git clone https://github.com/johnfactotum/foliate-js.git build/reader-evaluation/foliate-js
git -C build/reader-evaluation/foliate-js checkout 78914aef4466eb960965702401634c2cb348e9b1
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe scripts/probe_reader_engine.py
```

输出在忽略的 `build/reader-evaluation/`：`results.json`、6 张 PNG、合成 EPUB 和页面。不把下载的整个仓库自动加入应用依赖或发行包。

## 接入方案

### 1. 把书籍显示资源与 AI 原文索引分开

导入时在本地保存 EPUB 原文件及内容哈希，供引擎读取；继续保留当前规范化原文，供已读范围、检索和聊天快照使用。只保存原文件的路径不能保证移走文件后仍能重启恢复，需要应用自己的受管资源副本。

同时生成可追溯的位置表：`source_hash + spine 项 + DOM 文本节点／偏移 ↔ 规范化字符范围`。映射必须沿用同一份提取／规范化过程，覆盖空白合并、实体、ruby 和 Unicode；CFI 保存阅读位置，现有规范化字符范围继续作为模型授权边界。重复句用结构位置区分，不能只靠引文首次匹配。

已保存的 `material.content`、历史来源 hash 和快照不能静默重写。旧材料缺少原 EPUB 或无法与旧规范化文字精确对齐时继续提供现有文本回退；补建可验证映射与重新分析是独立操作，不默认产生模型费用。

### 2. 让两种页面复用同一个阅读组件

- 宽窗：原文与同一聊天并排，可调整分栏宽度；原文不跟随消息滚动。
- 窄窗：原文占主区，返回同一草稿／语音会话。
- 目录／搜索按需出现；EPUB nav／NCX 负责真实目录，不把目录短行排成聊天中的正文。
- 已读范围页也用同一组件，点击段落或定位末句后显示边界；提交前仍只是 pending 状态。
- 聊天中原文只给当前授权范围；章节名和引文也需检查已读边界。范围设置页可以浏览整本以选位置，不能因此把整本交给模型。

### 3. 通过有限桥接连接现有工作区

保留 `DesktopWorkspaceController` 的选章、选段、快照、历史预览和异步请求身份。由一个 desktop adapter 将引擎的定位事件转换为现有位置接口；不要直接把 workspace／数据库／文件系统的通用操作全部暴露给书内页面。

需覆盖：DOM Range 元素端点转文本边界；JS UTF-16 与 Python 字符偏移；读到段中间的末句；缩放／字体变化后的定位；切材料、切线程、关闭预览后的旧事件失效。历史来源版本失效仍只展示原确认引文。

Qt 启动需在创建 `QGuiApplication` **之前**执行 `QtWebEngineQuick.initialize()`，见 [Qt 官方说明](https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineQuick/QtWebEngineQuick.html)。阅读区按需实例化，测量新增启动时间和进程内存；QML 和 WebEngine 依赖留在 desktop，不能进入 core／kernel。

### 4. 本地资源与分发

正式集成锁定 commit，随包分发需要的 JS 模块、第三方许可证和字体；不在使用时从 CDN 下载。foliate-js 自身是 MIT，vendor 中的 zip.js 等依赖分别保留许可证。

正式 reader 使用受控本地资源通道、独立临时 profile、CSP 和资源访问限制；只允许当前材料的资源，阻止书内脚本和远程请求。它们是从纯文本转为 EPUB 内容渲染后新增的实际边界要求，具体要求见 [foliate-js Security](https://github.com/johnfactotum/foliate-js#security)。小样的临时 HTTP 服务只是验证方式，不是已选定的生产资源服务实现。

Windows 私有 Python 发行还需核实 QtWebEngineProcess、Chromium 资源、locales、QML plugins 和许可证，补 wheel／发行检查。本机可 import 不等于安装包完整。其他材料格式先沿用文本回退，后续用相同 book 接口接入语义 HTML，不顺带承诺 PDF／MOBI 等新格式。

## 正式替换的交付条件

第一增量应同时完成：保留原 EPUB、正确目录与段落显示、精确选段映射、已读边界、旧材料回退、窗口内真实复制／拖选／键盘验证，以及资源打包检查。只换一个能显示书的 WebView，无法满足现有 sidebar idea。

后续单独验证长篇加载、脚注／ruby、字体与字号控制、跨章滚动体验、真实 Windows 窗口和完整发行包。foliate-js 的 `scrolled` 与“整本无缝连续滚动”不是同一承诺；本轮只验证单章滚动和按目录切章。
