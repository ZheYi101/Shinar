# 桌面 UI 实施与国际化入口

日期：2026-10-29。环境：Windows、Python 3.13.5、PySide6 6.11.1。视觉基线为 `UI_LAYOUT_DESIGN.md` 修订 3；以中文浅色界面为本轮交付。实现沿用 QML/Material，不新增前端框架或服务。

本报告保留首轮实施时的计数和证据；后续控件视觉定制、386 条翻译源文案、365 项回归与 75 项分发资源的最新结果见[视觉复核记录](./UI_VISUAL_REVIEW_2026-10-29.md)。

## 起点与保留范围

基线提交为 `067dc44`，已有暖纸组件、工作区、来源快照、字体和图标实现。本轮开始时工作树已有以下修改，均作为实施基线保留：

- `learning_workbench.py` 的按浏览材料整理参考及类型标注。
- `workspace.py` 的参考资料投影与整理入口。
- `WorkbenchScaffold.qml`、`ConversationPage.qml`、`MaterialSpace.qml` 的页面调整。
- 旧 `MaterialsPage.qml` 已删除；新增未跟踪的 `MaterialReference.qml` 和 `scripts/validate_ui_workspace.py`。

没有重置工作树、修改 `.env`、重启用户原有应用或写入正常学习库。可见验证窗口由本轮脚本独立创建并关闭。

首轮普通回归显式 `RUN_REAL_AI_TESTS=0`：**352 passed、10 skipped、1 failed，162.47s**。失败是已删除旧页面留下的 `learningViewModel.materials/selectMaterial` 源码断言，已迁移为 `workspace.materials/browseMaterial`；复习答案隐藏、先提交再显示的断言保留。

## 增量与能力对应

| 增量 | 实施与核对结果 |
| --- | --- |
| 0 基线 | 核对既有主题、线程、导入、原文、复盘和本地语音能力，保留上述在途修改；“计算与加速”继续作为本地语音的二级页 |
| 1 主题与组件 | 暖纸 `#F7F3E9`、侧栏 `#EEE8DC`、深褐 `#3F382F` 与灰绿 `#56634F` 已应用；沿用内置中日文衬线字体和系统控件字体，六个 AI 图标裁切显示；标题栏热区高度与 30px 行统一 |
| 2 工作区 | 浏览材料与当前业务线程分离；新线程保留旧 active 线程、独立草稿／编辑位置／原文状态；摘要查询不装载完整历史；相同摘要不重建材料树；长开场想法保持未发送草稿，不调用自定义题准备 |
| 3 导入与范围 | QML 文件拖入、文件／粘贴输入、语言、页内范围核对；范围返回保留表单和候选位置，重复继续复用材料；替换文件失败时不能误存旧文件；窄窗口保存按钮独立于滚动字段，取消不提交 |
| 4 聊天与对照 | 原生 TextEdit 正反拖选、键盘选择／复制、章节、查找、分批注入和逐轮来源；失效旧引文拒绝错误跳转；历史直接选字转为新指向，旧消息快照不变；页面／线程变化隔离过期加载；重试沿用原文本／范围；重新输入相同草稿也不被完成回调清空；IME 组合期间 Ctrl+Enter 不发送 |
| 5 辅助页面 | 复盘、四档复习、六类设置与更多入口保持；本地语音的下载／取消／校验／卸载／试听／候选／配对测速保留；计算与加速的设备、预算、驻留、运行库和资源接口保留；删除确认使用可滚动正文并消除布局循环 |
| 6 默认入口与分发 | 新工作区为默认入口；更新旧导航测试、验证脚本、布局／功能契约、工作区与国际化指南；wheel 资源检查增加翻译目录及已删除 QML 检查 |

本轮没有增加连续麦克风、模拟波形或“打断已可用”的界面。

## 接口与数据

- 新增只读 `SessionSummary` 和 `SQLiteStore/LearningWorkbench.list_session_summaries(material_id=None)`。SQLite 直接投影 JSON 内必要字段，标题为话题名或首条真实用户发言，未发言的标题由桌面翻译成“新对话”；不生成模型标题。材料摘要来自已有内存材料对象，不重新解析原文。
- `DesktopWorkspaceController.cancelScope()` 根据入口返回导入／材料；候选阅读末尾仍仅在 `saveScope()` 后进入业务层。新增线程清空自己的初始章节与原文滚动位置，不继承上一线程。
- 原文文档、搜索、导入继续各自持有请求身份；切页、切线程和失效来源预览会废弃旧任务结果。默认来源字段、JSON 持久化和旧消息兼容方式保持，不改写原文或付费准备缓存。
- 新增 `DesktopPreferences.displayLanguage`、`DesktopLanguageController` 与系统语言／首次学习母语建议函数；中文 TS 和未来 QM 均包含在 wheel。显示语言、学习母语、目标语言分开保存。当前中文默认与旧学习 profile 不变。
- QML 与桌面固定提示采用 Qt 翻译标记，参数化动态文案。当前目录含 **380** 条源文案；业务异常、provider／语音目录状态的后续代码化边界见 [I18N](../../desktop/I18N.md)，不宣称已经有其他语言包。

## 验证证据

普通回归显式 `RUN_REAL_AI_TESTS=0`，最终 **363 passed、10 skipped，184.35s**；Ruff `src tests scripts` 与 `git diff --check` 通过。9 项真实本地语音／RTC 与 1 项付费 AI 测试依显式开关跳过。完整日志保存在 `build/ui-plan-audit/final-pytest.txt`。

- 新增和扩展测试覆盖摘要与完整历史一致、六轮以上消息排序、多材料归属、开场草稿无自定义题调用、表单取消／失败、过期来源加载、同文新草稿、录音中原文与窗口变化、历史直接选择、测试翻译器与输入法组合事件。原有语音失败恢复、四档复习、历史重启和架构导入边界一起回归。
- 可见 Windows QML：通过实际 `DropArea` 文件 URL 拖入、输入法提交事件填入中日文长标题与聊天、按钮保存范围／开聊／发送、录音／停止／识别／再发送／回放，以及结束复盘。数据库和本地语音目录全为临时目录，历史通过正常业务操作形成。
- 100%：360／600／800／1180／1200／1440 逻辑宽度，**91** 张页面截图；1200 是原文并排边界。
- 125% 与 150%：360／600／800／1180／1440 逻辑宽度，各 **76** 张截图。使用进程级 `QT_SCALE_FACTOR`，不改变用户 Windows 设置。记录 DPR 和窗口按钮实际几何位置；检查材料库、长标题材料空间、新对话、聊天／原文、导入／范围、六类设置、计算、复习／复盘。
- 最终可见记录只有 Qt FFmpeg 后端信息，没有 QML 布局循环或 undefined 属性警告。Qt 文本控制、复制、明暗兼容和长草稿另由离屏交互测试覆盖。
- 两份字体与六个图标的 **8** 项 SHA256 与来源记录一致。wheel 资源检查及隔离安装 QML smoke 通过，共 **68** 项资源。首次构建检出旧 `build/lib` 残留 `MaterialsPage.qml`，删除这一生成残留并重建后通过；检查脚本现会拒绝此类旧 QML 混入安装包。

本地产物位于 ignored `build/ui-plan-audit/`：`visible-100-final/`、`visible-125-final/`、`visible-150/` 各含截图与 `report.json`；`wheel-build.txt`、`wheel-check.txt` 和 `package/` 保存构建／分发证据。早期 `baseline-visible/`、`visible-synthetic/`、`visible-125/` 中的布局警告保留作修复前记录，不用后来的通过覆盖。

## 证据边界与后续

已完成可见 QML 自动交互与浅色截图检查；合成音频仅验证分轮控件和 adapter 调用，未使用真实麦克风／扬声器，也没有加载或下载模型。输入法提交／组合使用 Qt 事件，不能替代 Windows 实际中文／日语 IME 的候选窗、手工输入体验和触屏测试。最终个人审美确认仍由用户评审。

真实 AI 服务质量、首字／完整回复／端到端延迟、连续音轨、VAD/AEC、真人插话／打断和断线恢复均未在本轮通过；不因 Mock 或截图成功改变既有语音结论。深色视觉定稿、完整其他语言包、首次默认跟随系统并建议学习母语，按独立后续增量处理。

## 复现

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\update_translations.py
.venv\Scripts\python.exe scripts\validate_ui_workspace.py --visible --output build/ui-plan-audit/visible-100-final --widths 360,600,800,1180,1200,1440
$env:QT_SCALE_FACTOR='1.25'
.venv\Scripts\python.exe scripts\validate_ui_workspace.py --visible --output build/ui-plan-audit/visible-125-final
$env:QT_SCALE_FACTOR='1.5'
.venv\Scripts\python.exe scripts\validate_ui_workspace.py --visible --output build/ui-plan-audit/visible-150
Remove-Item Env:QT_SCALE_FACTOR
uv build --wheel --out-dir build/ui-plan-audit/package
.venv\Scripts\python.exe scripts\check_wheel_resources.py build/ui-plan-audit/package/lingualoop-0.1.0-py3-none-any.whl
```
