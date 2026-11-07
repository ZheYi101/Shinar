# 纸纹与背景装饰验证：对齐原图的修订

日期：2026-10-30。用户要求增加花纹和小图案，随后明确须结合原本打算实现的视觉效果。首轮自行选择的大枝叶、展开书和对称花饰已撤掉；本记录以修订后的实际 QML 为准，旧截图不作为本版证据。

## 视觉依据与改动

先查看[已定融合参考图](../../product/assets/visual-style/warm-paper-ink-reference-v1.png)，并逐张核对材料库、导入、聊天、材料空间与复盘的原 UI 稿。装饰语言采用原图的浅暖纸、灰绿布面书、褐色织物书签、奶油纸笺、米色胶带和淡植物印章，页面结构延续[逐页 UI 稿](../../product/UI_LAYOUT_DESIGN.md)。

- `assets/decorative/cloth-book.png`：使用内置 imagegen，以融合图右下方的布面书和小枝叶为唯一图片参考，生成独立透明插画。已保存到项目，尺寸 1536 × 1024，有真实 alpha；SHA-256 为 `1fc993396c17f5acfd04b67acf0dd720ce71d6432569632fe07fe477712dc5c2`。完整提示词与输入图片路径在[生成记录](../../../src/lingualoop/desktop/qml/assets/decorative/generation.json)。
- `assets/decorative/` 其余四份 SVG 为细纤维、淡植物印章、纸笺和短胶带，参考上述原图绘制；来源和项目授权状态见[资产说明](../../../src/lingualoop/desktop/qml/assets/decorative/README.md)。没有下载第三方图片或套用 Material 图标的许可。
- `components/PaperTexture.qml`、`InkDecoration.qml`、`ReadingNote.qml`：分别处理微弱纸感、插画／印章与内容纸笺；装饰图像没有点击、焦点或读屏语义。检查中发现直接从外壳实例化纸纹时，相对路径指向错误，已统一通过 `Qt.resolvedUrl` 在组件位置解析并重新截图。
- `pages/LibraryPage.qml`：有足够留白的宽窗口才在右下方显示布面书；列表密集或内容区窄于 720px 时隐藏，不额外增加滚动高度。修正了以装饰自身宽度决定可见性导致初始隐藏的问题，最终截图确认图像可见。
- `pages/MaterialReference.qml`：实际材料摘要使用奶油纸笺，最大宽度 760px，顶部短胶带、底部独立淡印章；摘要未添加引号，也不冒充原文引用。
- `WorkbenchScaffold.qml`、`WorkspaceSidebar.qml`、`ImportPage.qml`：保留淡纸纹，移除首轮通用页边枝叶、品牌花饰和导入插画，维持逐页稿的紧凑结构。没有修改对话／语音业务。
- `pyproject.toml` 将资源和来源记录打入 wheel。`scripts/validate_ui_workspace.py` 保留 `--theme light|dark`、显式符号／emoji 字体加载，并新增材料参考页截图。

具体视觉约束已同步到[风格指南](../../product/VISUAL_STYLE_GUIDE.md#64-已实现的背景装饰2026-10-30)。运行时没有新增网络请求或依赖；本轮只使用一次内置图像生成，没有调用业务语言模型、修改个人配置、重启正在运行的软件或使用个人学习数据。

## 验证结果

- 显式 `RUN_REAL_AI_TESTS=0`，桌面视觉控件与工作流回归 **17 passed，71.08s**；覆盖既有主题切换、窄窗口、导入、草稿、Mock 对话、重试和窗口操作。
- 本次修改的验证脚本 Ruff 检查与 whitespace 检查通过；没有为纯装饰新增业务测试。
- wheel 构建、**86 项资源检查**与隔离安装 QML smoke 通过。清除了上轮仅留在 `build/lib` 的三个旧 SVG 与 `PaperBackdrop.qml`，避免构建缓存继续分发旧资产。
- 隔离临时库和 Mock，通过实际 QML 拖入与输入事件生成截图，明确 `QT_SCALE_FACTOR=1`。最终浅色 360／600／800／1180／1440px 共 **82 张**常规截图，深色 360／800／1440px 共 **50 张**，两种主题各有两张导入中间状态。
- 人工查看最终材料库、纸笺参考页、聊天、原文对照及窄窗口：书插画可见且位于留白，窄屏隐藏；纸笺自动换行，印章未压文字；聊天和导入恢复无额外插画的布局。中文、日语、英文和 emoji 按验证字体显示。
- 报告保留 Qt 诊断，不将离屏字体目录提示说成不存在；系统中文／日语／符号／emoji 字体与自带 Noto Serif 均已显式加载。

本地证据为 ignored `build/ui-ornaments/reference-aligned/final-light/`、`final-dark/` 的 PNG 与 `report.json`，以及 `package/` 的 wheel。最初一版的证据仍留在 `build/ui-ornaments/`，不与本轮结果混用。

## 复现与边界

```powershell
$env:RUN_REAL_AI_TESTS='0'
$env:QT_SCALE_FACTOR='1'
.venv\Scripts\python.exe scripts/validate_ui_workspace.py --review-fixture --height 960 --widths 360,600,800,1180,1440 --output build/ui-ornaments/reference-aligned/final-light
.venv\Scripts\python.exe scripts/validate_ui_workspace.py --review-fixture --height 960 --widths 360,800,1440 --theme dark --output build/ui-ornaments/reference-aligned/final-dark
.venv\Scripts\python.exe -m pytest tests/test_desktop_visual_controls.py tests/test_desktop_workflow.py -q
```

本轮为离屏 QML 与 Mock 交互验证，不替代可见 Windows 窗口、真人语音或真实业务模型验收。深色只检查兼容，整体深色视觉定稿仍是后续事项。个人审美确认仍以用户查看实际效果后的反馈为准。
