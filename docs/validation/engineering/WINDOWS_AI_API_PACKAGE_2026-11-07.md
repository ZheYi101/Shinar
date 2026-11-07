# Windows 0.1.1 安装包与 AI API 设置验收

日期：2026-11-07。范围：当前 Windows x64 工作树快照；保留已有语音、阅读器和视觉修改。未修改个人 `.env`、正常学习库或已安装应用，付费模型调用为 0。

## 交付物

| 文件（仓库 `dist/windows/`） | 大小（字节） | SHA256 |
| --- | ---: | --- |
| `LinguaLoop-0.1.1-windows-x64-setup.exe` | 312068298 | `7647a7951c7323eef3a5a00295b354d1b52a2acae9121143b639a231be872d5b` |
| `LinguaLoop-0.1.1-windows-x64.zip` | 359316456 | `84a675b0da435f628780497532bf9c96e53846c64486130ea45a2f707495a100` |

包体携带私有 Python 3.12.13、PySide6 6.11.1、锁定依赖及使用指南，无需用户预装 Python。Inno Setup 6.7.4 制作当前用户安装器；默认安装不需要管理员权限。构建目录为 `build/windows/build-c9p4q_wy`，其 payload 共 14700 个文件、955046044 字节。未携带开发者密钥、学习库、模型权重或调用日志。版本和锁文件均更新为 0.1.1。

## 实现

原服务页只有只读状态。本轮新增页内 API 地址、密码式密钥输入、双角色模型 ID、可选模型列表、保存与恢复环境入口。首次未配置时进入服务页；连接探针只发送 `GET /v1/models`，不会请求生成。保存后清空输入框，Windows DPAPI 当前用户密文保存在应用数据目录的 `ai-services.json`；活动 provider 不变，重启后加载。显式界面配置优先于环境，CLI 仍读环境。界面全部使用 Qt 翻译入口，更新翻译源及随包 QM。

主要代码：`infrastructure/ai_configuration.py`、`providers/service_probe.py`、`desktop/ai_services.py`、`desktop/app.py`、`qml/components/AIServiceSettings.qml` 及设置页。打包扫描增加 `ai-services.json` 拒绝项。机制与使用方式见 [Windows 分发指南](../../desktop/WINDOWS_DISTRIBUTION.md) 和 Decision 0040。

## 已执行验证

所有普通回归显式设置 `RUN_REAL_AI_TESTS=0`。

| 检查 | 结果与证据（本地 ignored 路径） |
| --- | --- |
| Ruff 全库 | `src tests scripts` 通过，`build/ai-api-ruff-final.log` |
| 全量离线回归 | **542 passed、10 skipped**，197.27 s；`build/ai-api-full-tests.log` |
| 新增配置相关测试 | 覆盖真实 DPAPI 往返／篡改、原子写失败保留、URL 校验、安全错误、禁止重定向、仅元数据请求、QML 输入／保存、旧回调拒绝、环境优先级与当前 provider 保留 |
| wheel | **133 项资源**及隔离安装后的 QML smoke 通过；`build/ai-api-wheel-check.log` |
| 私有运行时与 ZIP 迁移 | 解压到含中文和空格的新目录，原生 EXE 启动、RTC／ORT 导入、字体、图标、WebEngine 资源和隔离 profile 通过；`build/windows/api-0.1.1-visible-20261107/report.json` |
| 包内可见 QML 设置 | 本机 HTTP 模拟服务，实际输入地址和假密钥、点击读取模型与保存；验证密钥非明文、输入框清空、重载 provider；恰好一次 `GET /v1/models`，无生成请求；同上报告 |
| 首次未配置及缩放 | 私有运行时在两个全新数据目录分别以 **125%／150%** 启动，自动进入 API 设置；真实 QML 配置和加密重载通过；`build/windows/api-0.1.1-first-run-20261107/report.json` |
| 布局 | 明暗主题分别检查 360／600／800／1180／1440px，另有上述两组缩放截图；字段和主要按钮无水平越界，窄窗保持可滚动。截图在两组报告旁；已人工查看浅色窄窗截图 |
| 安装／卸载 | 独立目录安装、已安装 EXE smoke、卸载返回码均 0；独立验证登记已清理、正常安装登记不变、外部数据保留、残留程序文件为 0；`build/windows/api-0.1.1-installer-20261107/report.json` |

可重复的检查命令与保护范围见分发指南。日志中的离屏 WebEngine OpenGL 上下文告警后 QML smoke 仍成功；本轮不将软件渲染通过当作全部硬件驱动兼容结论。

## 限制

- 这是未签名的开发预览包；没有执行干净 Windows 虚拟机矩阵、代码签名或占用文件时的升级验收。
- 只用本机模拟 API 检查设置与请求协议，未调用远端付费模型；`/models` 成功不证明模型生成权限、余额、质量或延迟达标。
- 本地 STT/TTS 权重、CUDA 等资产仍需在设置中显式下载；本次未重新执行空目录的全部模型安装。真实耳机／扬声器、AEC、插话和最终人工听感仍沿用独立门禁，打包通过不替代这些证据。
- 用户当前 Windows 凭据保护的密文不能直接迁移给另一账户或机器；卸载保留学习库、模型缓存及个人配置。
