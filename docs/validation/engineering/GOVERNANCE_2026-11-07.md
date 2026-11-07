# 治理迭代验收（2026-11-07）

## 交付与指标

本轮保留工作区原有修改，完成职责拆分、搜索／启动恢复、显式退出、CLI 已读授权和工程门禁。
数据库 schema、来源规范化／字符区间、缓存身份与历史 payload 未迁移；既有分轮和连续语音入口保留。

| 原始热点 | 治理前物理行 | 当前物理行 |
| --- | ---: | ---: |
| `application/learning_workbench.py` | 1245 | 791 |
| `application/semantic_preparation.py` | 896 | 772 |
| `desktop/continuous_voice.py` | 1148 | 693 |
| `desktop/speech_library.py` | 985 | 640 |
| `desktop/viewmodel.py` | 1430 | 680 |
| `desktop/workspace.py` | 1058 | 673 |
| `providers/openai_compatible.py` | 1096 | 682 |

初始 17 个超过 100 行的函数均已销账；当前所有自有生产 Python 函数最多 **100 行**。
门禁还覆盖所有自有 Python／QML／JS 文件及桌面控制器公开接口协作；vendor 和生成文件不参与。

| 原函数（现职责位置） | 原行数 | 当前行数 |
| --- | ---: | ---: |
| `application/continuous_voice.py:receive` | 117 | 95 |
| `application/material_preparation.py:_prepare_material` | 106 | 91 |
| `application/semantic_preparation.py:prepare` | 112 | 86 |
| `application/voice_session.py:_generate` | 177 | 87 |
| `core/knowledge_context.py:assemble_turn_context` | 235 | 64 |
| `desktop/continuous_voice_presentation.py:_event` | 253 | 58 |
| `infrastructure/epub_reader.py:build_reader_book` | 173 | 63 |
| `kernel/session_runner.py:handle_user_message` | 133 | 86 |
| `local_speech/benchmark.py:benchmark` | 152 | 98 |
| `local_speech/evaluation_worker.py:recognize` | 118 | 73 |
| `local_speech/evaluation_worker.py:synthesize` | 108 | 87 |
| `local_speech/evaluation_worker.py:run` | 211 | 89 |
| `local_speech/installation.py:prepare_managed_runtime` | 173 | 75 |
| `local_speech/library.py:model_rows` | 128 | 28 |
| `local_speech/paired_benchmark.py:benchmark_profiles` | 115 | 5 |
| `local_speech/paired_benchmark.py:_benchmark_profiles` | 110 | 88 |
| `local_speech/runtime_worker.py:load_model` | 103 | 60 |

## 职责与兼容

- Workbench 会话确认与提交保持一个所有者；材料／范围／参考准备在同一实例的职责基类维护。
- Qt 门面使用普通职责基类，继承属性／信号由单一 QObject 发布；无额外状态副本。最初多 QObject／重复导出方案在验证中触发元对象问题，已修正并由真实 QML 路径回归。
- provider 配置、prompt／请求包及解析分离；语义请求组件拥有预算与锁，语音缓冲组件拥有每轮合成状态。
- 文档／投影、长索引、原件保存与运行环境安装进入具名受管进程；最多每事件循环两个，取消等待真实清理。退出失败保留窗口和重试，不再吞掉清理异常。
- CLI 导入先保存，默认不授权全文；显式确认范围后开聊。默认 Mock 对齐语义主线，旧 topic-bank 契约用 LegacyMock 专测。

## 验证证据

- 最终完整离线回归：587 passed、10 skipped（262.92 秒，Windows／Python 3.13）；RUN_REAL_AI_TESTS=0，临时库／偏好。
- 最后接口／草稿／音频／阅读路径补测：48 passed；静态／provider 补测：31 passed。
- 治理缺陷、进程取消、执行器等待、退出重试、未确认 CLI 范围及维护门禁：12 passed。
- Ruff：通过。初轮回归的旧 Mock／旧 monkeypatch 目标和 fake 清理协议不匹配已修复；未移除原有兼容断言。
- 可见 Windows 阅读器：三语、明暗、680／1600 宽度、可见正文像素、选段复制发送、查找、历史隔离通过。证据：`build/governance/reader-visible/report.json`。
- 可见 Windows 生命周期：tray／dialog／window 三种实际事件循环退出、后台工作、托盘恢复与 360／1180 明暗对话框通过。证据：`build/governance/lifecycle-visible/*-report.json`。
- 可见连续语音 Mock：暗色 360／1180 的 14 个状态画面、浅色 360 的 7 个状态画面通过，QML 错误 0；包含监听、暂停保留草稿、识别／生成、插话历史、识别失败与麦克风不可用。
- 连续语音探针前两次没有进入通话：Mock 原先依赖既有运行时缓存、原生麦克风权限及未完成的预检查。探针现使用隔离的合成环境、权限与麦克风探针，并等待控件就绪；报告明确 real_devices／real_rtc／real_local_models=false，不将它计作实机语音通过。
- 来源加载移到 application 用例边界、资源线程退出校验的最后补测：37 passed。
- wheel 隔离安装／QML／字体／图标／许可证及资源检查通过，共 138 项；文件 `build/governance/dist/lingualoop-0.1.3-py3-none-any.whl`，SHA256 `d1fd14a68e4fdc5430317330b6ab67b797bd9d725f32f5183e44c2582e0f749d`。
- 最终原始证据：`build/governance/offline-final.xml`、`build/governance/reader-visible/report.json`、`build/governance/lifecycle-visible/*-report.json`、`build/governance/voice-visible/report-dark.json`、`build/governance/voice-light-visible/report-light.json`。

## 交付边界

本轮不重建 Windows 安装器，不调用真实收费 AI，不将 Mock 当作真人语音／真实质量验收。
全库现有格式、完整类型检查及 SQLite 资产目录耦合仍按既定触发条件维护；行数通过不表示所有设计债务消失。
工作区原有大量跨功能未提交修改，因此本轮未自动创建混合提交；阶段按本清单和验收结果划分。
