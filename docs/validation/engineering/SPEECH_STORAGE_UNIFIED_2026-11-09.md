# 单一语音资源位置与存储审查修复（2026-11-09）

状态：用户确认采用单一下载与加载位置后，已将连续通话纳入同一个语音库，关闭本轮确认的存储问题。学习库、材料原件与个人模型文件没有搬动。具体契约见 [Decision 0048](../../decisions/TECH_DECISIONS.md#decision-0048) 和[存储指南](../../desktop/SPEECH_STORAGE.md)。

## 修复范围

| 问题 | 当前行为与证据 |
| --- | --- |
| 连续通话另建数据库旁目录 | `configure_local_speech` 将 RTC、VAD、SFU 绑定到模型库根目录；普通装配和注入 Mock 都验证同根，未创建旧默认目录 |
| 旧下载失去复用机会 | 用户显式准备时才读取旧根的固定资产清单；完整文件校验 SHA，续传检查大小与稳定身份；按原租约和资产锁原子发布，忽略环境、数据库、未知文件及其他版本 wheel |
| 复用形成新重复缓存 | 新库已安装的共享资料以及已校验 wheel／原始资产不额外生成对应下载缓存；已有更长或相等的续传文件保持原样 |
| 换位置遗漏 SFU | 迁移固定归档并核对官方固定 SHA，在目标离线重建指定可执行文件；临时配置、日志及旧可执行文件留原处并列为保留项；未知目标仍拒绝，失败和取消不提交位置 |
| Python 3.11 沿 junction 统计外部文件 | 容量展示复用规范扫描器；真实临时 Windows 目录联接并移除 `Path.is_junction` 的回归验证祖先、目录和叶子检查；硬链接归属统一 |
| 释放请求后立刻迁移 | 冻结并取消预检，等待原 worker 的实际模型释放后再进独占维护；真实共享租约到独占租约交接回归通过，取消和退出也等待交接结束 |
| 旧准备状态与重复下载估算 | 更换根目录清空旧错误、提示和准备身份，拒绝旧结果；已安装 VAD／SFU 清掉下载缓存后不再计入预计下载 |

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 本轮存储、RTC、桌面与边界针对性回归 | **151 passed**，35.58 秒 |
| 本机完整离线回归 | **849 passed, 10 skipped**，308.84 秒；上一基线 800 项通过用例保留，新增 49 项通过用例 |
| Ruff、desktop／application F401、差异空白 | 通过 |
| 体积、公开协作、状态所有权及 Qt 元对象 | 完整回归中通过；生产文件 ≤800 行、Python 函数 ≤100 行 |
| 独立代码审查 | 未发现可确认的新 P1／P2；覆盖释放／关闭、旧事件、路径、租约、迁移回滚和固定资产复用，不替代真实设备测试 |
| 可见 Windows 存储页 | 明暗主题、1180／760 宽度、清理确认／完成、迁移预览；100% 和 150% 缩放分别保存七张截图并完成交互 |
| 可见连续语音 Mock | 明暗主题、360／1180 宽度；文本导入、确认范围、开聊、识别、播放、打断、失败、设备错误及结束；使用合成音频和假设备，回调错误／QML 错误均为 0 |
| 翻译 | 递归提取并编译中文目录；729 个源文本，新增／替换两处存储页文案；翻译上下文保持原值 |
| 新 wheel | 从包含 613 个 Git 文件的全新源码目录离线构建；141 项 QML／图标／许可资源校验、固定 vendor 校验、隔离安装后的学习闭环／重启恢复／QML 启动均通过；四个关键模块与当前源码字节相同 |
| 个人数据边界 | 学习数据库哈希保持原值；没有调用付费模型、采集麦克风、接受声音条款或改写个人位置／模型设置 |

wheel 为 `shinar-0.1.3-py3-none-any.whl`，26,486,463 字节，SHA256：`9c9e8a9f22db62f37a6e0d70c5406d9c3d1b30be0d0d7b8fb5ff5d3f15f8a189`。本轮没有重建 Windows 安装器。真实 AI、真人语音、本机 RTC 从旧根实际重建及旧目录回收不属于上述临时验证，不宣称已执行。

可见窗口与隔离 wheel 启动保留本机已有的 Chromium GLES3 回退日志；截图确认界面正常显示，未将这些日志误记为 QML 绑定错误。

## 本机证据与复跑

原始截图、临时模型、INI 和报告保存在忽略目录，不提交个人内容：

- `build/storage-one-root/ui/`、`ui-150/`：存储页交互报告与截图。
- `build/storage-one-root/continuous-light/`、`continuous-dark/`：连续语音合成场景截图，原始场景报告在 `build/continuous-voice/desktop-*/report.json`。
- `build/storage-one-root/source/`、`wheel/`：干净源码和本轮 wheel。

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m ruff check --select F401 src/shinar/desktop src/shinar/application
$env:QT_QPA_PLATFORM='windows'
.venv\Scripts\python.exe -m scripts.validate_speech_storage --evidence build/storage-one-root/ui
.venv\Scripts\python.exe scripts/validate_continuous_desktop.py --visible --widths 360,1180 --output build/storage-one-root/continuous-light
.venv\Scripts\python.exe scripts/check_wheel_resources.py build/storage-one-root/wheel/shinar-0.1.3-py3-none-any.whl
```
