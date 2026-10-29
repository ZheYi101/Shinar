# 语音与桌面工作区合并检查

日期：2026-10-29。环境：Windows、Python 3.13.5、PySide6 6.11.1。任务是整理现有未提交改动并分为语音基础与 QML 工作区两笔提交；没有付费模型请求，没有修改个人 `.env` 或正常学习库。

## 改动归属

| 提交范围 | 内容 |
| --- | --- |
| 基础语音与会话 | 确认事务、来源快照、双角色对话复用、分句合成、本地 CPU/GPU 进程、可选 VOICEVOX/Melo 英文、真实 STUN 与 RTC WAV/PCM；共用来源类型随该基础提交 |
| 桌面工作区 | 材料下多线程、主区导入/范围核对、原文选择与历史回看、独立草稿、分类设置、暖纸主题、字体/图标/许可与 UI 测试迁移 |

Workbench 和 ViewModel 的重叠改动按功能拆入暂存区，工作文件保持原样。第一笔的独立暂存树另行导出并测试，避免依赖尚未提交的 UI 文件。基础语音实现细节及九项真实模型/RTC 证据见[语音验收](../speech/VOICE_PYTHON_INTEGRATION_2026-10-29.md)。

## 本轮验证

| 检查 | 结果与限制 |
| --- | --- |
| 合并工作区普通 pytest | **353 passed, 10 skipped，161.96s**；显式 `RUN_REAL_AI_TESTS=0`；9 项本地语音/RTC 和 1 项付费 AI 测试按显式开关跳过 |
| 第一笔独立暂存树 Python 回归 | **278 passed，28.16s**；从导出树的 `src` 导入，未借用当前工作区的 UI 扩展 |
| Ruff | `src tests scripts` 通过 |
| wheel 资源与隔离安装 smoke | **67 项资源齐全**；QML、窗口控制器与无边框控件加载通过；含内置字体、原创图标和许可 |
| 资源来源检查 | 两份字体与六个插画图标 SHA256 与来源记录一致 |

原语音验收中保留的 14 项 UI 失败/13 项错误是较早快照；本次 UI 测试已迁移到新页面契约，完整回归通过。没有删除语音、失败重试、历史恢复或资源设置的语义断言来换取通过。

新增真实 QML 交互覆盖正反拖选、键盘选择与复制、章节切换/查找、原文加载就绪、历史来源回看、导入不替换前台线程，以及失败重试保留原指向/新草稿。既有明暗主题、窄窗口、录音/朗读重试与本地模型设置用例一起执行；中日文、emoji 和 UTF-16 位置映射有专项测试。

这是离线与离屏 Qt 证据，不代表新的真人连续语音或最终视觉审美验收。基础语音首包冷启动与完整文本一秒目标仍按各自报告保留，不能因全库 pytest 通过而改记性能达标。

## 复现与本地产物

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m pytest -q
uv build --wheel --out-dir build/commit-package-check
$linguaWheel = Get-ChildItem build/commit-package-check/*.whl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.venv\Scripts\python.exe scripts/check_wheel_resources.py $linguaWheel.FullName
```

日志保存在 ignored `build/voice-python-integration/commit-{full-regression,ruff,wheel-build,wheel-resources}.txt`；第一笔导出树及日志位于 `build/commit-organization/`。这些本地产物不随源码提交。
