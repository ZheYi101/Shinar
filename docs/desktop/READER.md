# EPUB 原文对照阅读器

2026-11-06。对应 Decision 0036，实际检查见[集成记录](../validation/engineering/READER_INTEGRATION_2026-11-06.md)。

## 使用行为

- EPUB 使用内置 foliate-js + Qt Quick WebEngine；不需要另装浏览器、Node.js 或在使用时下载引擎。
- 已读范围页和聊天旁原文复用同一阅读区。真实段落、标题、行内强调、ruby 和本地图片保留，出版者 CSS 由统一的纸墨排版替代。正文最大行宽 680px，默认 18／20px、行高 1.85、段间距 0.9em；中日文使用随包的 Noto Serif。
- 宽窗可拖动分隔线调整原文与聊天宽度；窄窗只显示原文，关闭后回到同一会话和草稿。
- 目录使用 EPUB nav／NCX；点章建立讨论范围，点段落或完成文字选区直接聚焦。Ctrl+F 查找当前已读范围，结果可跳到其他章节；原生复制与 Shift 键盘选区继续可用。
- 范围页的“已读至此”只改变待保存位置，保存后才改变材料范围。已发消息的来源快照保持不变。

## 资源与位置

导入 EPUB 时先保存原文件字节快照，再走原有材料保存／准备入口。受管副本在所属 SQLite 数据库旁的 `<数据库名>.assets/sources/<规范化内容哈希>.epub`；与 `SHINAR_DATA_DIR` 的数据库一起迁移即可。文件名不含用户路径、密钥、语言服务配置，目录已加入 Git 忽略。

旧材料不改 `content`、`source_hash`、准备缓存或历史。原路径仍存在时，后台读取并验证其提取结果与既存规范化文本完全一致，再补存受管原件。找不到原件、无法精确对应、固定版式或解析失败时，显示文本回退；可以重新导入同一原件补充资源，已有材料的复用仍遵循原来的标题／语言／profile 匹配规则。

显示适配沿用原提取器的 token 顺序和规范化规则，将每个静态文本 span 标记为准确的 Python 字符区间。重复句按其结构位置定位，不使用引文首次匹配。DOM 的 UTF-16 选区和元素端点在页面中转为这些区间；最终引文始终从后端当前规范化原文截取。Ruby 注音没有独立来源坐标，不能被当成原文证据。

WebEngine 收到按当前授权范围裁剪、去脚本的显示 EPUB；它不直接读取原 EPUB 路径。聊天中排除未读正文和未读目录入口；范围页可浏览整本来定位。关闭页面、切材料、换线程或开始新加载时，旧页面身份失效，不接受旧选段或位置回调。历史预览不覆盖当前选段与阅读位置。

## 维护入口

模块所有权、WebChannel 字段／事件、请求失效、资源边界、上游升级与后续拆分条件统一维护在[阅读器架构](../architecture/READER_ARCHITECTURE.md)。本指南只维护使用、备份、运行与当前限制，避免重复维护两份架构契约。

core／kernel 不依赖 Qt。页面按需创建，使用独立临时 profile 和专用桥接；书内脚本、远程资源、外部导航与下载受限，没有本地 HTTP 服务或新增模型调用。

## 验证与分发

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe scripts/validate_reader_workspace.py
```

Windows 默认打开单独的可见 Mock 窗口，使用临时库、合成 EPUB 和独立设置，输出到 `build/reader-workspace/`。它检查真实鼠标拖选、原生复制、键盘扩选、UI 输入／发送和历史预览，并采集中英日文、明暗与窄窗及边界标记。导入和末句定位由控制器调用，不能把它称为用户手动操作的完整真实材料验收。`--platform offscreen` 只用于 DOM／控制器检查；本机离屏截图可能空白，视觉检查应使用默认 Windows 窗口。

普通回归新增规范化位置、重复句、Unicode／ruby、未读裁剪、静态资源限制、原件移走后恢复及旧页面身份测试；不启用真实模型。

引擎固定提交与逐文件 SHA256 位于 `reader/foliate/UPSTREAM.json`，主库 MIT 和 zip.js BSD 许可证随包。`pyproject.toml` 分发全部页面／JS／许可资源；`scripts/check_wheel_resources.py` 检查 wheel 和隔离 QML 加载。

Windows 发行继续携带完整 PySide6 6.11.1，须保留 QtWebEngineProcess、Chromium `.pak`／ICU／locales、QtWebEngine／QtWebChannel QML 模块。`scripts/check_windows_distribution.py` 已增加这些检查；本轮没有重建完整 ZIP／安装器，后续发行须对新产物运行该探针。

## 当前限制

- 只接入可精确对应的可重排 EPUB。TXT／Markdown／DOCX／字幕等继续使用原生文本回退；不增加新材料格式承诺。
- 采用单章滚动与目录跳转，不宣称整本无缝连续滚动。原始出版者 CSS、固定版式 EPUB、SVG 插图及未索引的外置注释页面不在本次显示支持内；原文件副本仍完整保存。
- 字号按阅读区宽度采用默认值，独立字号／字体设置、跨应用阅读进度同步仍未实现。
- 当前验证为合成材料与 Mock，真实用户 EPUB、完整安装器迁移、复杂书籍版式和真实 AI 对话质量须分别验证。
