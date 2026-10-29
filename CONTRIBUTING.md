# Contributing to LinguaLoop

感谢你考虑参与 LinguaLoop。项目当前处于早期阶段，最有价值的贡献是帮助明确学习闭环、MVP 范围、数据边界和可维护的实现路径。

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
- 不把 prompt 文本散落在组件中。修改模型输出格式时，同时维护解析、校验、回退和准备版本；旧缓存仍须兼容读取。
- 异常在边界转换为用户可操作的信息；广泛捕获只用于明确的容错/清理路径，并说明被保留的状态。取消和后台失败不冒充成功，也不吞掉前台错误。
- 超时、并发、输出预算和材料限制使用命名配置；参数校验集中在配置或入口。不要通过放宽断言、忽略 lint、添加无理由的 `noqa` 掩盖问题。
- 不提交 `.env`、模型调用日志、真实用户材料或私有语料。

## 本地质量检查

```powershell
uv sync --locked --dev --extra desktop
$env:RUN_REAL_AI_TESTS='0'
uv run --locked ruff check src tests scripts
uv run --locked python -m pytest -q
```

当前 Ruff 门禁覆盖导入位置、语法、未定义名称/错误赋值、可变默认参数、默认参数中的调用及无效语句。完整格式、导入排序、未使用导入和全库类型检查尚未设为强制门禁；现有风格债务按模块清理，避免一次性重写运行代码。规则配置显式保存于仓库，不继承个人全局规则。

新增或单独整理模块时，对本次负责的文件执行格式化并检查 diff，例如：

```powershell
uv run --locked ruff format src/lingualoop/core/ports.py
git diff --check
```

格式化不应混入正在由他人修改的文件。行为修改使用相应的边界、失败恢复和兼容测试；无需为机械格式变化添加镜像测试。修改依赖后更新 `uv.lock`，CI 使用锁定依赖。

真实 AI 测试标记 `@pytest.mark.real_ai`，必须同时显式启用命令行和环境开关：

```powershell
$env:RUN_REAL_AI_TESTS='1'
uv run --locked python -m pytest tests/test_llm.py --run-real-ai -q
$env:RUN_REAL_AI_TESTS='0'
```

单独设置环境变量或 `.env` 不启用真实测试；普通 CI 不携带服务凭据，也不运行真实调用。测试数据使用临时目录，实机验收历史与演示数据分开保存。

`.github/workflows/checks.yml` 在 Windows / Python 3.11、3.13 上执行相同的静态检查和离线回归。QML/图标变更另运行 README 的 wheel 资源检查；真人语音与真实模型延迟属于单独验收。

## 逐步降低维护成本

优先整理 ViewModel 和 OpenAI-compatible provider 的职责：界面状态、会话历史投影、模型配置、prompt 构造、输出解析与网络生命周期应有清晰边界。每次拆出一个可独立验证的职责，保持现有入口与缓存兼容，不按行数机械拆文件。应用层对具体 SQLiteStore 的依赖和 provider 对检索私有函数的依赖也是后续整理项。

审查记录和优先级见[维护性检查](./docs/validation/engineering/MAINTAINABILITY_2026-10-28.md)。工具配置参考 [Ruff 官方文档](https://docs.astral.sh/ruff/configuration/)；CI 依赖安装方式参考 [uv 官方文档](https://docs.astral.sh/uv/guides/integration/github/)。

## License

开源许可证尚未确定。在确定前，请不要假设本项目已采用 MIT、Apache-2.0 或其他许可证。
