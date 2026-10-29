"""Collect strict speech reports and build a local blind listening sheet."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import importlib.metadata
import json
import random
import shutil
from pathlib import Path

from lingualoop.local_speech.evaluation_metrics import (
    aggregate_accuracy,
    distribution,
    error_metrics,
    first_output_distribution,
    normalized_words,
    immediate_playback_gaps,
)
from lingualoop.local_speech.storage import atomic_json


def collect(runs: list[Path]) -> list[dict]:
    results = []
    for run in runs:
        for path in sorted(run.glob("*/report.json")):
            report = json.loads(path.read_text(encoding="utf-8"))
            if report.get("schema") == "strict-speech-evaluation-v1":
                report["report_path"] = str(path.resolve())
                results.append(report)
    keys = [(r["model"]["id"], r["model"]["language"]) for r in results]
    if len(keys) != len(set(keys)):
        raise ValueError("Select one comparable run per model/language; duplicate reports found.")
    return results


def summarize(report: dict) -> dict:
    model, rows = report["model"], report["rows"]
    result = {
        "id": model["id"],
        "language": model["language"],
        "task": model["task"],
        "provider": model.get("provider", "cpu"),
        "load_ms": report["load_ms"],
        "first_inference_ms": report["first_inference"]["compute_ms"],
        "first_inference_first_ms": report["first_inference"].get(
            "first_pcm_ms" if model["task"] == "tts" else "first_text_wall_ms"
        ),
        "first_inference_item_id": report["first_inference"].get("item_id"),
        "timing_samples": len(rows),
        "unique_inputs": len({r["item_id"] for r in rows}),
        "peak_ram_mib": report["peak_process_rss_bytes"] / 1024**2,
        "ram_measurement_kind": report.get("peak_memory_kind", "unspecified"),
        "human_listening_evaluated": False,
        "report_path": report["report_path"],
    }
    if model["id"] == "zipformer-small-zhen-20230216" and model.get("adapter_revision", 1) == 1:
        result["configuration_warning"] = (
            "legacy all-INT8 decoder; superseded by adapter revision 2"
        )
    if model["id"] == "sensevoice-int8-20250909":
        result["configuration_warning"] = (
            "WSYue-derived checkpoint; not the original 2024 multilingual weights"
        )
    if "peak_cuda_allocated_bytes" in report:
        result["peak_cuda_allocated_mib"] = report["peak_cuda_allocated_bytes"] / 1024**2
        result["peak_cuda_reserved_mib"] = report["peak_cuda_reserved_bytes"] / 1024**2
    if model["task"] == "stt":
        result.update(report["summary"]["accuracy"])
        result["characters_per_compute_s"] = report["summary"]["corpus_characters_per_compute_s"]
        result["first_text_compute_ms"] = distribution(
            [r["first_text_wall_ms"] for r in rows if r["first_text_wall_ms"] is not None]
        )
        result["first_text_missing_runs"] = sum(r["first_text_wall_ms"] is None for r in rows)
        result["first_text_kind"] = (
            "native partial, audio supplied without waiting"
            if rows[0]["native_partial"]
            else "offline result after complete audio supplied"
        )
        result["finalization_compute_ms"] = distribution(
            [r["finalization_compute_ms"] for r in rows]
        )
        result["paced_first_partial_ms"] = distribution(
            [
                r["first_text_wall_ms"]
                for r in report["paced"]
                if r["first_text_wall_ms"] is not None
            ]
        )
        result["paced_no_partial"] = sum(r["first_text_wall_ms"] is None for r in report["paced"])
        result["paced_recordings"] = len(report["paced"])
        result["empty_utterances"] = sum(not r["hypothesis"] for r in rows if r["repeat"] == 0)
        first_output = first_output_distribution([r["first_text_wall_ms"] for r in rows])
        result["final_compute_p95"] = result["finalization_compute_ms"]["p95"]
        if rows[0]["native_partial"]:
            first_output = first_output_distribution(
                [r["first_text_wall_ms"] for r in report["paced"]]
            )
            result["first_text_kind"] = (
                "paced prerecorded audio start to native text; includes source silence/context"
            )
        result["first_output_distribution"] = first_output
        result["first_ms_p50"] = first_output["p50"]
        result["first_ms_p95"] = first_output["p95"]
        result["successful_first_ms_p95"] = first_output["successful_only"]["p95"]
        if model["language"] == "en":
            result["words_per_compute_s"] = result["words"]["reference_units"] / sum(
                row["compute_ms"] / 1000 for row in rows if row["repeat"] == 0
            )
    else:
        result["audio_evidence"] = (
            "every timed repeat retained"
            if len({r["preview"] for r in rows}) == len(rows)
            else "repeat 0 retained; later timing rows share its preview, not their own waveform"
        )
        cold_preview = report["first_inference"].get("preview")
        result["first_inference_audio_retained"] = bool(
            cold_preview
            and cold_preview not in {r["preview"] for r in rows}
            and Path(cold_preview).is_file()
        )
        result["first_audio_kind"] = (
            "complete waveform returned by generate_custom_voice; streaming API not measured"
            if model["adapter"] == "qwen_tts"
            else "first nonempty PCM callback after complete text supplied"
        )
        result["first_pcm_ms"] = distribution(
            [r["first_pcm_ms"] for r in rows if r["first_pcm_ms"] is not None]
        )
        result["characters_per_compute_s"] = sum(r["characters"] for r in rows) / sum(
            r["compute_ms"] / 1000 for r in rows
        )
        result["spoken_characters_per_s"] = sum(r["characters"] for r in rows) / sum(
            r["duration_s"] for r in rows
        )
        result["categories"] = {
            category: distribution(
                [
                    r["first_pcm_ms"]
                    for r in rows
                    if r["category"] == category and r["first_pcm_ms"] is not None
                ]
            )
            for category in sorted({r["category"] for r in rows})
        }
        result["max_clipping_fraction"] = max(r["clipping_fraction"] for r in rows)
        result["leading_below_minus50db_ms"] = distribution(
            [
                r["leading_below_minus50db_ms"]
                for r in rows
                if r["leading_below_minus50db_ms"] is not None
            ]
        )
        result["missing_callback_runs"] = sum(r["first_pcm_ms"] is None for r in rows)
        result["rtf_aggregate"] = sum(r["compute_ms"] for r in rows) / sum(
            r["duration_s"] * 1000 for r in rows
        )
        result["simulated_playback_gap_ms"] = distribution(
            [
                immediate_playback_gaps(row["callbacks"], row["sample_rate"])["total_gap_ms"]
                for row in rows
                if row["callbacks"]
                and abs(
                    sum(c["samples"] for c in row["callbacks"])
                    - round(row["duration_s"] * row["sample_rate"])
                )
                <= 1
            ]
        )
        result["first_nonzero_callback_ms"] = distribution(
            [
                r["first_nonzero_callback_ms"]
                for r in rows
                if r["first_nonzero_callback_ms"] is not None
            ]
        )
        result["first_nonzero_callback_p95"] = result["first_nonzero_callback_ms"]["p95"]
        result["leading_below_minus50db_p95"] = result["leading_below_minus50db_ms"]["p95"]
        result["simulated_playback_gap_p95"] = result["simulated_playback_gap_ms"]["p95"]
        result["callback_coverage_mismatch_runs"] = sum(
            abs(
                sum(c["samples"] for c in r["callbacks"])
                - round(r["duration_s"] * r["sample_rate"])
            )
            > 1
            for r in rows
        )
        result["output_duration_s"] = distribution([r["duration_s"] for r in rows])
        first_output = first_output_distribution([r["first_pcm_ms"] for r in rows])
        result["first_output_distribution"] = first_output
        result["first_ms_p50"] = first_output["p50"]
        result["first_ms_p95"] = first_output["p95"]
        result["successful_first_ms_p95"] = first_output["successful_only"]["p95"]
        result["short_first_pcm_p95"] = result["categories"].get("short", {}).get("p95")
        if model["language"] == "en":
            result["words_per_compute_s"] = sum(
                len(normalized_words(row["text"])) for row in rows
            ) / sum(row["compute_ms"] / 1000 for row in rows)
    return result


def roundtrip_scores(folder: Path, *, canonical_zh: bool = False) -> list[dict]:
    """Keep judges separate; their errors cannot be attributed solely to the TTS."""
    sources = json.loads((folder / "source-items.json").read_text(encoding="utf-8"))
    results = []
    converter = None
    if canonical_zh:
        from opencc import OpenCC

        converter = OpenCC("t2s")
    for path in sorted(folder.glob("*/report.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        request = json.loads(path.with_name("request.json").read_text(encoding="utf-8"))
        references = {item["id"]: item["reference"] for item in request["items"]}
        groups = {}
        for row in report["rows"]:
            if row["repeat"] != 0:
                continue
            source = sources[row["item_id"]]
            groups.setdefault(source["tts_model"], []).append(row)
        for model_id, rows in groups.items():
            score = {
                "tts_model": model_id,
                "judge": report["model"]["id"],
                "language": report["model"]["language"],
                "scope": "ASR roundtrip proxy; includes judge errors; not human listening",
                **aggregate_accuracy(rows),
            }
            metric = "wer" if score["language"] == "en" else "cer"
            errors = sorted(
                (row for row in rows if row["accuracy"][metric] > 0),
                key=lambda row: -row["accuracy"][metric],
            )
            score["largest_error_examples"] = [
                {
                    "text_id": sources[row["item_id"]].get("text_id"),
                    "reference": references[row["item_id"]],
                    "hypothesis": row["hypothesis"],
                    "accuracy": row["accuracy"],
                    "category": sources[row["item_id"]].get("category"),
                }
                for row in errors[:3]
            ]
            if converter and score["language"] == "zh":
                canonical = [
                    {
                        "accuracy": error_metrics(
                            converter.convert(references[row["item_id"]]),
                            converter.convert(row["hypothesis"]),
                            "zh",
                        )
                    }
                    for row in rows
                ]
                score["cer_t2s"] = aggregate_accuracy(canonical)["cer"]
            results.append(score)
    return results


def listening_pack(reports: list[dict], output: Path) -> None:
    folder = output / "listening"
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for report in reports:
        if report["model"]["task"] == "tts":
            items.extend((report, row) for row in report["rows"] if row["repeat"] == 0)
    random.Random(9321).shuffle(items)
    keys, cards = [], []
    for index, (report, row) in enumerate(items, 1):
        code = f"L{index:03d}"
        destination = folder / "audio" / f"{code}.wav"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(row["preview"], destination)
        model = report["model"]
        keys.append(
            {
                "code": code,
                "model": model["id"],
                "language": model["language"],
                "text_id": row["item_id"],
                "text": row["text"],
                "category": row["category"],
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        )
        fields = "".join(
            f'<label>{label}<select data-score="{field}"><option value="">未评分</option>'
            + "".join(f'<option value="{v}">{v}</option>' for v in range(1, 6))
            + "</select></label>"
            for field, label in [
                ("naturalness", "自然度"),
                ("intelligibility", "清晰度"),
                ("pronunciation", "读音正确性"),
            ]
        )
        cards.append(
            f'<article data-code="{code}" data-language="{model["language"]}" data-text="{row["item_id"]}"><h3>{code} · {model["language"]} · {html.escape(row["category"])}</h3><p>{html.escape(row["text"])}</p><audio controls preload="none" src="audio/{code}.wav"></audio><div class="scores">{fields}</div><textarea aria-label="听感备注" placeholder="漏读、错读、断句、机械感或其他问题；请写具体位置"></textarea></article>'
        )
    atomic_json(output / "listening-key.json", keys)
    document = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LinguaLoop 语音盲听</title><style>body{font:16px/1.6 system-ui,'Microsoft YaHei',sans-serif;max-width:1050px;margin:24px auto;padding:0 18px;background:#f5f7fa;color:#162033}header{position:sticky;top:0;background:#f5f7faf5;padding:12px 0;border-bottom:1px solid #c9d3e0}button,select{font:inherit;padding:6px 10px}article{background:white;border:1px solid #d8e0eb;border-radius:12px;padding:18px;margin:16px 0}h3{margin-top:0}audio{width:100%;max-width:600px}.scores{display:flex;flex-wrap:wrap;gap:16px;margin:12px 0}label{display:flex;gap:8px;align-items:center}textarea{width:100%;box-sizing:border-box;min-height:60px;font:inherit}small{color:#526078}</style><header><h1>语音盲听</h1><p>戴同一副耳机，以舒适音量试听。每个维度 1 分最差、5 分最好；先选语言和同一句作对比。允许保留未评分，不能从测速推断听感。</p><label>语言<select id="lang"><option value="">全部</option><option>zh</option><option>en</option><option>ja</option></select></label><label>句子<select id="sentence"><option value="">全部</option></select></label><button id="export">导出已填评分</button><small id="status"></small></header><main>CARDS</main><script>
const packId='PACK_ID',articles=[...document.querySelectorAll('article')],key='lingualoop-listening-v1-'+packId;
const sentence=document.querySelector('#sentence');[...new Set(articles.map(a=>a.dataset.text))].sort().forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;sentence.append(o)});
function filter(){articles.forEach(a=>a.hidden=!!((lang.value&&a.dataset.language!==lang.value)||(sentence.value&&a.dataset.text!==sentence.value)))}const lang=document.querySelector('#lang');lang.onchange=sentence.onchange=filter;
function values(){return articles.map(a=>({code:a.dataset.code,language:a.dataset.language,ratings:Object.fromEntries([...a.querySelectorAll('select')].map(s=>[s.dataset.score,s.value?Number(s.value):null])),notes:a.querySelector('textarea').value}))}
try{const old=JSON.parse(localStorage.getItem(key)||'[]');articles.forEach(a=>{const row=old.find(r=>r.code===a.dataset.code);if(row){a.querySelectorAll('select').forEach(s=>s.value=row.ratings[s.dataset.score]||'');a.querySelector('textarea').value=row.notes||''}})}catch(e){}
function save(){const data=values();try{localStorage.setItem(key,JSON.stringify(data))}catch(e){}document.querySelector('#status').textContent=' 已评分 '+data.filter(r=>Object.values(r.ratings).some(v=>v!==null)).length+'/'+articles.length}document.addEventListener('change',save);document.addEventListener('input',save);save();
document.addEventListener('play',event=>{if(event.target.tagName==='AUDIO')document.querySelectorAll('audio').forEach(audio=>{if(audio!==event.target)audio.pause()})},true);
document.querySelector('#export').onclick=()=>{const data={schema:'lingualoop-human-listening-v1',pack_id:packId,timestamp:new Date().toISOString(),formal_mos_study:false,ratings:values()};const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='lingualoop-listening-ratings.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
</script></html>""".replace("CARDS", "\n".join(cards)).replace(
        "PACK_ID", hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()[:16]
    )
    credits = sorted(
        {report["model"]["attribution"] for report in reports if report["model"].get("attribution")}
    )
    extra = "<p>使用原始音频，未做响度匹配；这些评分不属于正式 MOS 实验。评分仅存于本浏览器，填完请导出 JSON。</p>"
    if credits:
        extra += "<p>音频署名：" + html.escape("；".join(credits)) + "</p>"
        (folder / "audio" / "ATTRIBUTION.txt").write_text(
            "\n".join(credits) + "\n仅作本地评测；保留署名。\n", encoding="utf-8"
        )
    document = document.replace("</header>", extra + "</header>")
    (folder / "index.html").write_text(document, encoding="utf-8")


def write_results(summary: list[dict], output: Path) -> None:
    def number(value, digits=0):
        return "—" if value is None else f"{value:.{digits}f}"

    lines = [
        "# LinguaLoop 本机语音评测",
        "",
        "CPU 每模型 2 线程；GPU 单列。STT 每语言 50 段真人朗读；TTS 每语言 12 条相同文本。",
        "首 PCM 从完整文本供给后计时，尚未测设备出声；离线 STT 从完整录音供给后计时。",
        "原生 STT 首字来自 200ms 真实时钟供给，包含录音本身的静音和声学上下文；n 与缺失数另列。",
        "SenseVoice、Whisper、Qwen ASR 为完整录音已供给后的离线结果；Vosk、Zipformer 为从录音起点算的原生首字。两种起点不能直接比较数值大小。",
        "总体首字分位数把未出文本计为服务失败，排在有限观测之后；若相应秩落入失败样本，记为 —。成功样本条件分位数另存 JSON / CSV。",
        "模型加载与首次推理在 summary.csv / JSON 单列；所有 p95 使用最近秩法，重复计时不扩大准确率语料。",
        "TTS 合成/播报字速以请求文本字数计算，漏读与重复会使它偏离实际读出字速；需结合回识和听评。",
        "听感评分尚未完成。[打开匿名听评](listening/index.html)。ASR 回识包含裁判自身错误，不能替代听感。",
        "现有 sensevoice-int8-20250909 是 WSYue 来源检查点；zipformer-small-zhen-20230216 在本报告保留旧全 INT8 decoder 结果，正确配置另列 fp32-decoder / fp32。",
        "",
    ]
    for provider in ["cpu", "cuda"]:
        for task in ["stt", "tts"]:
            rows = [r for r in summary if r["provider"] == provider and r["task"] == task]
            if not rows:
                continue
            lines.extend([f"## {provider.upper()} {task.upper()}", ""])
            if task == "stt":
                lines.extend(
                    [
                        "| 模型 / 语言 | 首字或离线首结果 p50 / p95 ms | 原生首字 n / 缺失 | 结束后计算 p95 ms | 字/计算秒 | CER% | 中文 t2s CER% | 英语 WER% |",
                        "|---|---:|---:|---:|---:|---:|---:|---:|",
                    ]
                )
                for r in rows:
                    native = r["paced_recordings"]
                    lines.append(
                        f"| {r['id']} / {r['language']} | {number(r['first_ms_p50'])} / {number(r['first_ms_p95'])} | {str(native) + ' / ' + str(r['paced_no_partial']) if native else '—'} | {number(r['final_compute_p95'])} | {number(r['characters_per_compute_s'], 1)} | {number(r['cer'] * 100, 2)} | {number(r.get('cer_t2s') * 100 if r.get('cer_t2s') is not None else None, 2)} | {number(r.get('wer') * 100 if r.get('wer') is not None else None, 2)} |"
                    )
            else:
                lines.extend(
                    [
                        "| 模型 / 语言 | 首 PCM p50 / p95 ms | 短应答 p95 ms | 合成字/s | 播报字/s | 合成 RTF | 听感 |",
                        "|---|---:|---:|---:|---:|---:|---|",
                    ]
                )
                for r in rows:
                    lines.append(
                        f"| {r['id']} / {r['language']} | {number(r['first_ms_p50'])} / {number(r['first_ms_p95'])} | {number(r['short_first_pcm_p95'])} | {number(r['characters_per_compute_s'], 1)} | {number(r['spoken_characters_per_s'], 1)} | {number(r['rtf_aggregate'], 3)} | 待人工 |"
                    )
                if provider == "cuda":
                    lines.extend(
                        [
                            "",
                            "本次 Qwen TTS 使用整段 generate_custom_voice API；首 PCM 等于整段返回时间，未测原生增量 API。",
                        ]
                    )
            lines.append("")
    scores = [
        (r, score) for r in summary if r["task"] == "tts" for score in r.get("asr_roundtrip", [])
    ]
    if scores:
        lines.extend(
            [
                "## TTS 回识辅助",
                "",
                "| TTS / 语言 | ASR 裁判 | CER% | 中文 t2s CER% | 英语 WER% |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for r, score in scores:
            lines.append(
                f"| {r['id']} / {r['language']} | {score['judge']} | {number(score['cer'] * 100, 2)} | {number(score.get('cer_t2s') * 100 if score.get('cer_t2s') is not None else None, 2)} | {number(score.get('wer') * 100 if score.get('wer') is not None else None, 2)} |"
            )
    (output / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--partial-runs", type=Path, nargs="+", default=[])
    parser.add_argument(
        "--roundtrip", type=Path, help="Completed synthetic TTS roundtrip directory"
    )
    parser.add_argument(
        "--canonical-zh",
        action="store_true",
        help="Also score both sides after pinned OpenCC t2s conversion; retain raw CER",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("build/local-speech-evaluation/strict/report")
    )
    args = parser.parse_args()
    reports = collect(args.runs)
    args.output.mkdir(parents=True, exist_ok=True)
    summary = [summarize(r) for r in reports]
    examples = []
    for report in reports:
        if report["model"]["task"] != "stt":
            continue
        request = json.loads(
            Path(report["report_path"]).with_name("request.json").read_text(encoding="utf-8")
        )
        items = {item["id"]: item for item in request["items"]}
        metric = "wer" if report["model"]["language"] == "en" else "cer"
        ranked = sorted(
            (row for row in report["rows"] if row["repeat"] == 0),
            key=lambda row: (-row["accuracy"][metric], row["item_id"]),
        )
        examples.extend(
            {
                "model": report["model"]["id"],
                "language": report["model"]["language"],
                "selection": f"highest {metric}; diagnostic examples, not representative sampling",
                "item_id": row["item_id"],
                "reference": items[row["item_id"]]["reference"],
                "hypothesis": row["hypothesis"],
                "accuracy": row["accuracy"],
                "public_source_audio": items[row["item_id"]]["wav"],
            }
            for row in ranked[:5]
        )
    atomic_json(args.output / "asr-error-examples.json", examples)
    if args.roundtrip:
        if not (args.roundtrip / "complete.json").exists():
            raise ValueError(
                "Roundtrip suite is incomplete; preserve failed/partial attempts separately"
            )
        completed = json.loads((args.roundtrip / "complete.json").read_text(encoding="utf-8"))
        if any(not (args.roundtrip / job / "report.json").exists() for job in completed["jobs"]):
            raise ValueError("Roundtrip completion marker has missing judge reports")
        scores = roundtrip_scores(args.roundtrip, canonical_zh=args.canonical_zh)
        atomic_json(args.output / "tts-intelligibility.json", scores)
        for row in summary:
            if row["task"] == "tts":
                row["asr_roundtrip"] = [
                    score
                    for score in scores
                    if score["tts_model"] == row["id"] and score["language"] == row["language"]
                ]
    if args.canonical_zh:
        from opencc import OpenCC

        converter = OpenCC("t2s")
        canonical_rows = []
        for report, row in zip(reports, summary):
            if row["task"] != "stt" or row["language"] != "zh":
                continue
            request = json.loads(
                Path(report["report_path"]).with_name("request.json").read_text(encoding="utf-8")
            )
            references = {item["id"]: item["reference"] for item in request["items"]}
            normalized = []
            for sample in report["rows"]:
                if sample["repeat"] != 0:
                    continue
                reference, hypothesis = (
                    converter.convert(references[sample["item_id"]]),
                    converter.convert(sample["hypothesis"]),
                )
                result = {
                    "model": row["id"],
                    "item_id": sample["item_id"],
                    "reference_t2s": reference,
                    "hypothesis_t2s": hypothesis,
                    "accuracy": error_metrics(reference, hypothesis, "zh"),
                }
                normalized.append(result)
            row["cer_t2s"] = aggregate_accuracy(normalized)["cer"]
            row["canonical_zh_transform"] = "OpenCC t2s " + importlib.metadata.version(
                "opencc-python-reimplemented"
            )
            canonical_rows.extend(normalized)
        atomic_json(args.output / "canonical-zh-rows.json", canonical_rows)
    partial_reports = {}
    for folder in args.partial_runs:
        for path in folder.glob("*/report.json"):
            partial = json.loads(path.read_text(encoding="utf-8"))
            if partial.get("schema") == "strict-first-partial-v1":
                key = (partial["model"]["id"], partial["model"]["language"])
                if key in partial_reports:
                    raise ValueError("Duplicate first-partial report")
                partial_reports[key] = (partial, path)
    for row in summary:
        found = partial_reports.get((row["id"], row["language"]))
        if found:
            partial, path = found
            first_output = first_output_distribution(
                [sample["first_text_wall_ms"] for sample in partial["rows"]]
            )
            row.update(
                {
                    "first_ms_p50": first_output["p50"],
                    "first_ms_p95": first_output["p95"],
                    "successful_first_ms_p95": first_output["successful_only"]["p95"],
                    "first_output_distribution": first_output,
                    "paced_recordings": partial["recordings"],
                    "paced_no_partial": partial["missing_partial"],
                    "first_text_kind": partial["scope"],
                    "first_partial_report": str(path.resolve()),
                }
            )
    atomic_json(args.output / "summary.json", summary)
    with (args.output / "summary.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        fields = [
            "id",
            "language",
            "task",
            "provider",
            "unique_inputs",
            "timing_samples",
            "load_ms",
            "first_inference_ms",
            "first_inference_first_ms",
            "first_inference_item_id",
            "characters_per_compute_s",
            "words_per_compute_s",
            "spoken_characters_per_s",
            "first_ms_p50",
            "first_ms_p95",
            "successful_first_ms_p95",
            "short_first_pcm_p95",
            "first_nonzero_callback_p95",
            "leading_below_minus50db_p95",
            "simulated_playback_gap_p95",
            "callback_coverage_mismatch_runs",
            "rtf_aggregate",
            "max_clipping_fraction",
            "final_compute_p95",
            "empty_utterances",
            "first_text_missing_runs",
            "first_text_kind",
            "paced_recordings",
            "paced_no_partial",
            "cer",
            "cer_t2s",
            "wer",
            "peak_ram_mib",
            "ram_measurement_kind",
            "peak_cuda_allocated_mib",
            "peak_cuda_reserved_mib",
            "first_audio_kind",
            "configuration_warning",
            "audio_evidence",
            "first_inference_audio_retained",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary)
    listening_pack(reports, args.output)
    write_results(summary, args.output)
    print(
        f"Collected {len(summary)} model/language results; blind pack: {args.output / 'listening/index.html'}"
    )


if __name__ == "__main__":
    main()
