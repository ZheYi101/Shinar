# 语音存储管理

入口为「设置 → 本地语音模型 → 存储管理」，也可从「数据与隐私」进入。模型、运行环境和缓存使用一个可选择的语音目录；内部目录按用途划分，不需要用户逐个管理。

## 位置与范围

未指定位置时继续读取现有 Shinar／旧 LinguaLoop 目录，不自动复制或迁移。首次下载前可以选择其他磁盘上的空文件夹。选择成功后，`storage-location.json` 保存在应用数据目录，只记录语音目录的位置。优先级为：显式构造参数、`SHINAR_SPEECH_DIR`（兼容旧变量）、显式 `SHINAR_DATA_DIR/speech`、保存的位置、原有默认目录。环境变量指定位置时，界面不覆盖它。

保存的位置失联或配置损坏会明确报错，不静默回退 C 盘或重新下载。选择新位置只影响模型库，学习数据库、材料和数据库旁的独立 `voice-runtime` 连续通话组件不在本次迁移范围。

Windows 的界面编译与图形缓存位于 `%LOCALAPPDATA%\Shinar\cache`，由 Qt 自动生成，和所选模型目录分开。早期版本同时将 Qt 的组织名与应用名设为 Shinar，产生了 `Shinar\Shinar\cache`；现已取消这层重复目录，旧缓存不会自动搬移。外观偏好仍使用显式的 Shinar／LinguaLoop QSettings 命名空间，学习库与模型位置也不随 Qt 缓存路径变化。阅读器使用临时 profile，不在这里保存材料原件或浏览器历史。

## 占用与清理

- 模型与运行环境：模型权重、共享 Python／语言资料、已准备环境及启动工具，正常使用需要保留。
- 安装与下载缓存：已完成的原始下载包、wheel 集合和安装器缓存，可以在停止语音任务后清理。
- 配置、报告及其他：模型选择、声音、条款确认、计算设置、测速报告和未识别文件。

统计按文件身份去重，模型／运行环境优先归属；硬链接只计算一次。这里显示逻辑文件字节，不是 NTFS 分配簇或磁盘实际释放承诺。只有全部链接都属于本次清理集合的文件，才计入「可清理约」。目录大小不能直接相加。

清理需要先查看确认窗口，只处理已识别的完成下载和可再生成缓存。未完成的 `.part`、未知下载文件、已安装模型、运行环境和学习资料均保留。不跟随目录联接或符号链接。扫描后文件发生变化时拒绝旧计划，重新扫描后再确认。取消可能已经清掉部分缓存，已安装资源不受影响。以后重新安装／修复时，缺少的包可能重新下载；正常使用已就绪环境不需要原始下载包。

本版不在启动、退出或刷新时自动删除缓存，也不扫描并删除其他磁盘的旧开发目录。

## 更改位置

选择空文件夹并确认预览后，软件锁定原库与目标库，复制并校验模型、共享资源、下载进度、设置和报告。Windows Python 环境含绝对路径，因此不会直接复制旧环境冒充可用：在最终目标目录重新建立环境并运行实际计算探针，全部通过后才原子保存新位置。此步骤可能联网获取缺少的固定安装资源。

成功后退出并重新打开软件生效，当前对象不会热切换到新根目录。原位置始终保留，未知文件也保留在原处；确认新位置正常后再单独处理原件，本版不会自动删除原库。取消／普通失败不切换位置并清理本次目标候选；强制结束留下的受管事务可以选择同一目标重试，来源变化或任意已有文件夹不能冒充续传目标。提交后迟到的取消以实际保存的位置为准。

下载、安装、测速、驻留推理和连续通话持有共享根目录租约，清理与迁移使用独占租约。新版本中的设置写入也遵守租约。开始真实维护前应正常退出仍运行旧代码的实例；未实现此租约的旧版本不能被新锁保护。

## 开发验证

所有回归使用临时目录、临时位置配置和 Mock，下面的可见检查不操作个人模型库：

```powershell
$env:RUN_REAL_AI_TESTS='0'
.venv\Scripts\python.exe -m pytest -q tests/local_speech/test_storage_maintenance.py tests/local_speech/test_storage_migration.py tests/desktop/test_speech_storage_management.py
$env:QT_QPA_PLATFORM='windows'
.venv\Scripts\python.exe -m scripts.validate_speech_storage --evidence build/storage-governance/ui
$env:QT_SCALE_FACTOR='1.5'
.venv\Scripts\python.exe -m scripts.validate_speech_storage --evidence build/storage-governance/ui-150
```

软件回归与发行资源检查见[存储管理验收](../validation/engineering/SPEECH_STORAGE_2026-11-09.md)。随后经用户授权执行的个人模型库迁移、环境独立性及实际清理结果单列于[本机迁移验收](../validation/engineering/SPEECH_STORAGE_HOST_2026-11-09.md)，不代表软件会自动整理其他开发目录。
