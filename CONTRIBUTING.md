# Contributing to Shinar

感谢你考虑参与 Shinar。项目当前处于早期阶段，最有价值的贡献是帮助明确学习闭环、MVP 范围、数据边界和可维护的实现路径。

## 贡献范围

欢迎以下类型的贡献：

- 产品设计：学习流程、练习类型、反馈方式、复习机制
- 工程实现：前端、后端、LLM provider、数据模型、测试
- 学习内容：示例材料、语言学习任务模板、评估标准
- 文档：架构说明、开发指南、部署指南、使用说明

## 开发流程

1. 先阅读 `README.md`、`AGENTS.md` 和 `docs/product/MVP_SPEC.md`。
2. 确认变更是否属于 MVP 范围；如果不是，先更新路线图或提出设计讨论。
3. 保持 Pull Request 聚焦，避免把产品决策、重构和功能实现混在一起。
4. 新增代码时提供必要测试和最小可运行说明。
5. 涉及用户数据、LLM 调用或第三方服务时，说明隐私与失败回退策略。

## 代码风格

- Python 使用 4 空格、`snake_case` 函数/变量、`PascalCase` 类型与 `UPPER_CASE` 常量。公共接口、跨模块数据和异步返回值补全类型；优先使用领域模型，避免无约束的 `dict` 和 `**kwargs` 穿透层次。
- 格式由 `pyproject.toml` 中的 Ruff 配置统一，目标 Python 3.11、100 列、双引号；`.editorconfig` 统一编辑器缩进和编码。长中文提示词不为凑行宽改变内容。
- 使用清晰的业务命名，避免过早抽象。跨模块使用公开接口，不直接依赖其他模块的私有辅助函数。
- `core` 保存领域模型和 ports；`kernel` 依赖这些接口编排业务，不导入 Qt、HTTP、供应商或 SQLite 实现。具体服务放在 adapter，CLI/桌面入口负责组装。`tests/test_architecture.py` 自动检查内层导入边界。
- QML 页面负责展示与用户操作，复用设计系统 tokens/components；网络、长材料整理和数据库业务不进入 QML。Qt 对象的线程约束不因重构而改变。
- 跨模块改动先看[当前架构](./docs/architecture/ARCHITECTURE.md)；阅读器维护还须遵守[阅读器契约](./docs/architecture/READER_ARCHITECTURE.md)。WebEngine 是局部显示适配器，业务状态与来源坐标由 Python 管理。第三方 foliate-js 的 pin、哈希与许可一起维护，产品逻辑不写入 vendor。
- 不把 prompt 文本散落在组件中。修改模型输出格式时，同时维护解析、校验、回退和准备版本；旧缓存仍须兼容读取。
- 异常在边界转换为用户可操作的信息；广泛捕获只用于明确的容错/清理路径，并说明被保留的状态。取消和后台失败不冒充成功，也不吞掉前台错误。
- 超时、并发、输出预算和材料限制使用命名配置；参数校验集中在配置或入口。不要通过放宽断言、忽略 lint、添加无理由的 `noqa` 掩盖问题。
- 不提交 `.env`、模型调用日志、真实用户材料或私有语料。

## 本地质量检查

```powershell
uv sync --locked --dev --extra desktop
$env:RUN_REAL_AI_TESTS='0'
uv run --locked ruff check src tests scripts
uv run --locked ruff check --select F401 src/shinar/desktop src/shinar/application
uv run --locked python -m pytest -q
```

当前 Ruff 门禁覆盖导入位置、语法、未定义名称/错误赋值、可变默认参数、默认参数中的调用及无效语句。桌面与 application 另强制 F401；完整格式、导入排序和全库类型检查尚未设为强制门禁。现有风格债务按模块清理，规则配置不继承个人全局规则。

`tests/test_maintainability.py` 同时检查自有生产 Python／QML／JS 文件不超过 800 物理行，
Python 函数（含嵌套函数，按 AST 起止位置）不超过 100 行；第三方 foliate、生成文件和测试夹具除外。
职责模块共享同一业务／QObject 门面的生命周期，不另建状态副本；桌面控制器通过公开接口协作。
不要通过压缩代码、移动到 vendor 或增加无理由豁免绕过门禁。

桌面边界检查递归扫描子包，识别导入／简单赋值别名、嵌套属性和字符串 `getattr/setattr` 私有访问；同一 QObject 的 `*Mixin` 属于同一所有者。运行时导入环排除 `TYPE_CHECKING` 专用导入。连续语音通话状态只能由 `CallCoordinator` 更新，对话展示只能经既有统一入口更新。

Qt 回归集中在 `tests/desktop`，其 `conftest.py` 管理 Qt fixture 和测试平台；共享 Fake、合成音频、交互与场景工厂位于 `tests/support`。普通上下文管理器负责场景释放，不依赖 pytest，不在导入时设置平台环境。验证脚本可使用支持模块，但不能导入具体 `test_*.py`、访问 fixture `__wrapped__` 或向路径注入 tests 目录。测试 monkeypatch 必须指向真正执行操作的模块，不能靠未使用重导出维持旧补丁。LangGraph 实验测试位于 `tests/engine`。

新增或单独整理模块时，对本次负责的文件执行格式化并检查 diff，例如：

```powershell
uv run --locked ruff format src/shinar/core/ports.py
git diff --check
```

格式化不应混入正在由他人修改的文件。行为修改使用相应的边界、失败恢复和兼容测试；无需为机械格式变化添加镜像测试。修改依赖后更新 `uv.lock`，CI 使用锁定依赖。

架构审查需明确数据所有者、允许的依赖方向、后台结果失效和故障回退；新增跨语言字段／事件须同时更新两端契约。先在已有模块中完成小而明确的职责，再按真实扩展需要抽取接口，不引入没有第二个使用者的通用框架。已知耦合的后续工作应记录触发条件和验收标准，不仅写“以后重构”。

`tests/test_architecture.py` 在普通 pytest／CI 中检查内层与来源处理依赖、WebEngine 使用范围和固定 vendor 完整性。涉及来源位置另跑 EPUB／工作区行为测试；QML／JS／桥接交互需按[阅读器指南](./docs/desktop/READER.md)运行独立可见 Mock。仅修改文档时核对链接与 diff，无需启动应用；升级资源或发行依赖时分别检查 wheel 与实际 Windows 分发，不能用静态门禁替代这些验证。

真实 AI 测试标记 `@pytest.mark.real_ai`，必须同时显式启用命令行和环境开关：

```powershell
$env:RUN_REAL_AI_TESTS='1'
uv run --locked python -m pytest tests/engine/test_real_provider.py --run-real-ai -q
$env:RUN_REAL_AI_TESTS='0'
```

单独设置环境变量或 `.env` 不启用真实测试；普通 CI 不携带服务凭据，也不运行真实调用。测试数据使用临时目录，实机验收历史与演示数据分开保存。

`.github/workflows/checks.yml` 在 Windows / Python 3.11、3.13 上执行相同的静态检查和离线回归。QML/图标变更另运行 README 的 wheel 资源检查；真人语音与真实模型延迟属于单独验收。

## 逐步降低维护成本

优先整理 ViewModel 和 OpenAI-compatible provider 的职责：界面状态、会话历史投影、模型配置、prompt 构造、输出解析与网络生命周期应有清晰边界。每次拆出一个可独立验证的职责，保持现有入口与缓存兼容，不按行数机械拆文件。应用层对具体 SQLiteStore 的依赖和 provider 对检索私有函数的依赖也是后续整理项。

审查记录和优先级见[维护性检查](./docs/validation/engineering/MAINTAINABILITY_2026-10-28.md)。工具配置参考 [Ruff 官方文档](https://docs.astral.sh/ruff/configuration/)；CI 依赖安装方式参考 [uv 官方文档](https://docs.astral.sh/uv/guides/integration/github/)。

## License

开源许可证尚未确定。在确定前，请不要假设本项目已采用 MIT、Apache-2.0 或其他许可证。

桌面属性 Mixin 只能读取快照或委托命令；状态写入与后台操作属于普通协作者，不能重新新增门面的可写字段别名。tests/desktop/test_facade_contracts.py 固定三个门面公开 Qt 元对象契约、共享状态零债务和无 Qt／完整门面依赖边界；新增异步结果必须保留原任务身份。
