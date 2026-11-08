# Shinar 图标与侧栏字标验证（2026-11-08）

## 交付内容

用户确定名称为 Shinar 后，要求 Logo 能体现巴别塔典故。图形采用层叠圆塔、上升回廊、拱洞和未完成塔顶，塔基结合对话气泡收尾；配色沿用灰绿与暖纸。名称经文出处与绘画视觉参考分别见[命名记录](../../product/NAMING.md)和[图标说明](../../../src/shinar/desktop/assets/README.md)。

SVG 为自行绘制的母版，生成 512px PNG 和 16／20／24／32／40／48／64／128／256px 九种 ICO 图层。侧栏显示 Shinar，并提供图标的无障碍名称；README 展示新图标。小尺寸保留塔形和回廊，大尺寸显示拱洞；没有引入额外模型、运行依赖或第三方图片。

## 验证

- 相关离线测试：29 passed，覆盖 Windows 图标解码、视觉控件、维护性门禁与桌面导入边界；`RUN_REAL_AI_TESTS=0`。Ruff 和增量空白检查通过。
- 可见 Windows Mock：浅色／深色各 34 个画面，覆盖 360／1180px、中日文长文、材料导入、文本、分轮语音、复盘和历史；手动读取导出的实际画面核对新图标与字标。使用合成设备、临时数据库与隔离偏好，不读取个人学习库。
- 保留的 Qt 诊断包括图形上下文回退、FFmpeg 版本信息、WebEngine profile 弃用提示，以及 clipboard／GPUInfo 提示；探针交互与画面检查均通过。
- 新 wheel 的 138 项 QML／图标／字体／许可证资源与当前源码一致，隔离解包后的 QML 启动及窗口控件探针通过。

本地证据：`build/shinar-logo/logo-proof.png` 为图标及原生尺寸对照；`visible-light/report.json`、`visible-dark/report.json` 及对应画面位于同一目录。

wheel：`build/shinar-logo/dist/lingualoop-0.1.3-py3-none-any.whl`；SHA-256：`ec7226baa5e688f51465e36cfc5aee455f28fd888e8370912c697b2932272ddf`。

## 边界

本轮更新品牌图形与侧栏字标。现有 Python 包名、CLI、AppUserModelID、QSettings 和数据目录保持兼容，其他发行版名称迁移另行实施。未重建 Windows 安装器，未验证真实模型或真人语音，未自动提交或推送 Git。
