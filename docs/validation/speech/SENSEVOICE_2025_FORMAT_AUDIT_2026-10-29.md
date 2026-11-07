# SenseVoice 2025 大小写与格式复核（2026-10-29）

2026-11-06 更新：用户已明确淘汰 2025 / WSYue 分支，当前产品目录不再提供任何语言或用途的此模型。下文保留当时的评测和取舍，不代表当前候选；原版 2024 保留。

用户指出试听页英文全大写，认为可能是大小写影响评估，并允许在其他候选不合适时考虑继续使用 2025 版。本轮检查现有文本，不重新识别、不增加 GPU/付费调用，不改原始转写或旧评分。

## 核心结果

原评分的 `normalized_words()` 和 `normalized_characters()` 都执行 Unicode NFKC + casefold，英语 WER 不区分大小写。对两个版本各 50 段逐条把输出转成小写后重算，所有分子、分母和 S/D/I 完全一致。全大写是显示风格问题，未造成已报告的 29.35% 英语 WER。

进一步对参考与输出分别使用固定版 Whisper EnglishTextNormalizer，统一数字、常见缩写及部分英美写法，结果如下。它是事后敏感性分析，不替代原主指标；由于规范化也改变参考词数，不能把分数变化直接当作精确的“格式错误占比”。

| 具体版本 | 原 WER（已忽略大小写） | 显式转小写后 | 进一步格式规范化 WER |
| --- | --- | --- | --- |
| 2025 / WSYue | 29.35% | 29.35% | 28.53% |
| 原版 2024 | 7.94% | 7.94% | 6.23% |

规范化后参考单位由 1070 变为 1076。2025 版仍有实质词形、漏字、词边界问题，不能用全大写解释全部差距；原版 2024 的英语已经达到本轮速度门槛，现阶段优先它。2025 版仍保留中文候选和受限英语备选，不永久排除。

## 截图这一句

标准：`However, due to the slow communication channels, styles in the west could lag behind by 25 to 30 year.`

2025 原输出：`HOWEVER DURE TO THE SLOW COMMUNICATION CHANNELS STYLES IN THE WEST COULD LAG BEHIND BY TWENTY FIVE TO THIY YEARS`

独立格式规范化后：`however dure to the slow communication channels styles in the west could lag behind by 25 to thiy years`

- 大小写和 `TWENTY FIVE` / `25` 可以归一化，不能作为实质识别错误。
- `due` → `DURE`、`30` → `THIY` 仍未解决；没有利用标准答案把 `THIY` 强行改成 `thirty`。
- `year` / `years` 可能涉及参考转写或实际读法，不能只看截图断言一定是模型错。本轮未重新做人工音素标注。
- 此句原 WER 为 26.32%，进一步规范化后为 15.79%；原版 2024 同句规范化后为 5.26%，仅剩 `year` / `years` 这一项字符串差异。

此外，语料中位附近也有 `hospital` → `HOSIBLE`、`followed` → `FOLLOED`、`protocol` → `PROCOLL` 等问题，并非只展示最坏个例。全部 100 条双版本参考/原输出/规范化输出和逐句指标已保留在本地 `sensevoice-format-audit/examples.csv`。

## 怎样保留使用可能性

1. 中文仍保留 2025 版：本批平均首字 438ms、CER 11.50%，与原版 2024 的 11.38% 接近。英语先使用已测且速度过线的 2024 版：平均 453ms，比 2025 的 398ms 多约 55ms，但本批错误率明显更低。
2. 2025 英语可保留为可选备选，配合原始转写可见、用户确认后发送的路径；不因大小写难看就删除模型，也不把它设为默认英语识别。
3. 若后续确需挽救此配置，先验证 language / use_itn 开关、tokenizer / 导出与精度；当前来源是 WSYue 的粤语分支。其英文退化的具体原因尚未由消融定位，不能直接断言只是量化或解码故障。不同参数或 FP32 导出都须作为新配置复测。
4. 显示层可以处理全大写、标点和数字；保留原始识别。自动猜词或用 LLM 重写不能冒充识别修复，尤其不能把学习者实际说法改掉后再作为纠错依据。新增后处理需计入端到端时间。
5. GPU 后续仍优先原版 2024，再将 2025 版作对照/受限备选。现阶段没有必要为了修复全大写而放弃已可用的原版英语候选。

## 来源与复现范围

原始模型转换仓库明确说明来自 [WSYue 的 sensevoice_small_yue](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09)，不应仅因日期更新就推断它是原版的全面升级。

辅助规范化使用 [Whisper 官方 EnglishTextNormalizer](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/whisper/normalizers/english.py)，revision `86098128c0b4f24f0e2aa2994de830614b474227`，MIT 许可，源文件及 SHA 已固定；more-itertools 10.8.0 仅安装在本次审计的独立 target 目录，未修改项目依赖或已有推理环境。原始报告 SHA、重新计分与大小写一致性断言保存在本地 summary.json。

本报告是已有有限公开朗读子集上的输出审计，不是新模型测试、实机语音通过证明或全量基准。先前[筛选与试听记录](./LOCAL_SPEECH_SELECTION_2026-10-29.md)中的速度与 TTS 取舍保持不变。
