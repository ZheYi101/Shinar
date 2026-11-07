from __future__ import annotations

from . import RUNTIME_VERSION, adapter_revision
from .catalog import load_catalog
from .benchmark import percentile
from .hardware import admission
from .storage import read_json
from .compute import device_profile, runtime_version


def matching_reports(store, package, language, hardware, device="cpu", gpu_index=0, *, voice_id=None):
    from .model_profile import measurement_identity
    identity = measurement_identity(store.root, package, device, voice_id)
    reports = []
    revisions = {model.id: adapter_revision(model.adapter) for model in load_catalog()}
    revisions[package.id] = adapter_revision(package.adapter)
    for path in (store.root / "reports").glob("*.json"):
        report = read_json(path, {})
        measured = report.get("hardware", {})
        if (
            report.get("schema") == 1
            and (not identity or report.get("model_identities", {}).get(package.id) == identity)
            and report.get("language") == language
            and report.get("metrics", {})
            .get("runtime_versions", {})
            .get(package.id, report.get("metrics", {}).get("runtime_version"))
            == runtime_version(package)
            and report.get("metrics", {})
            .get("devices", {})
            .get(package.id, report.get("metrics", {}).get("provider"))
            == device
            and report.get("metrics", {}).get("threads_per_model") == 2
            and report.get("model_fingerprints", {}).get(package.id) == package.fingerprint
            and all(
                report.get("adapter_revisions", {}).get(model_id, 1) == revisions.get(model_id, 1)
                for model_id in report.get("model_fingerprints", {})
            )
            and (
                device == "cpu"
                or [g["name"] for g in measured.get("gpus", [])]
                == [g["name"] for g in hardware.get("gpus", [])]
            )
            and (device == "cpu" or report.get("metrics", {}).get("gpu_index") == gpu_index)
            and all(
                measured.get(key) == hardware.get(key)
                for key in ("platform", "architecture", "cpu", "logical_cpus")
            )
        ):
            reports.append(report)
    return sorted(reports, key=lambda r: r.get("timestamp", ""), reverse=True)


def model_rows(store, packages, language, scenario, hardware, devices=None, gpu_index=0):
    rows = []
    selections = read_json(store.root / "selections.json", {})
    for package in packages:
        if language not in package.available_languages or scenario not in package.scenarios:
            continue
        rows.append(_model_row(store, package, language, scenario, hardware,
                               devices, gpu_index, selections))
    # One provisional pick per task, using measured latency only. No fabricated
    # hardware min requirements or quality claims. Complete-chain validation follows.
    for task in ("STT", "TTS"):
        eligible = [
            r
            for r in rows
            if r["task"] == task
            and r["measured"]
            and r["downloadable"]
            and r["benchmarkable"]
            and not r["excluded"]
            and (scenario != "conversation" or r["withinRealtimeBudget"])
        ]
        if eligible:
            min(eligible, key=lambda row: row["latencyScore"])["recommended"] = True
    priority = {"sensevoice-fp32-20240717": 0, "reazonspeech-k2-v2-int8": 1,
                "sensevoice-int8-20240717": 2, "piper-lessac-medium": 0, "melo-zhen-onnx": 1}
    rows.sort(key=lambda r: (r["task"] != "STT", not r["selected"], not r["recommended"],
                             priority.get(r["id"], 10)))
    return rows


def identity_for_row(root, package, device):
    from .model_profile import measurement_identity
    return measurement_identity(root, package, device)


def _model_row(store, package, language, scenario, hardware, devices, gpu_index, selections):
    permitted, reason = admission(package, hardware)
    download_space = sum(f.size + f.unpacked_limit for f in package.files) + 256 * 1024**2
    downloadable = bool(package.files) and hardware.get("disk_free_bytes", 0) >= download_space
    installed = store.installed(package)
    device = (devices or {}).get(package.id, "cpu")
    excluded = package.id.startswith(("qwen3-", "kokoro-"))
    reports = (
        matching_reports(store, package, language, hardware, device, gpu_index)
        if installed
        else []
    )
    report = reports[0] if reports else None
    metrics = report.get("metrics", {}) if report else {}
    values = metrics.get("sequential", {}).get(package.task, [])
    ready = bool(values) and (package.task == "tts" or all(v.get("nonempty") for v in values))
    latency_field = "finalization_compute_ms" if package.task == "stt" else "first_pcm_ms"
    latencies = [r[latency_field] for r in values if latency_field in r]
    overlapping = metrics.get("concurrent", {}).get(package.task, [])
    concurrent_latencies = [r[latency_field] for r in overlapping if latency_field in r]
    # A measured slow local component must never become a realtime default
    # merely because it is the fastest of a slow list. Budgets leave room for
    # VAD/LLM/transport, but are not a promise of a one-second voice chain.
    local_p95 = max(
        percentile(latencies) or float("inf"), percentile(concurrent_latencies) or 0
    )
    average = sum(latencies) / len(latencies) if latencies else float("inf")
    within_budget = ready and (average <= 500 if package.task == "stt" else local_p95 <= 300)
    summary = "尚未本机测速"
    pcm_label = "整句合成" if package.adapter in {"voicevox", "melo_english"} else "首 PCM"
    if report:
        field = "compute_ms" if package.task == "stt" else "first_pcm_ms"
        p95 = percentile([v[field] for v in values if field in v])
        summary = (
            (
                f"{device.upper()} · 热态{'整段计算' if package.task == 'stt' else pcm_label} 平均 {average:.0f} / p95 {p95:.0f} ms · "
                f"{report['repeats']} 次"
            )
            if p95 is not None
            else "报告缺少延迟样本"
        )
        if latencies and package.task == "stt":
            summary += f"；结束后计算 p95 {percentile(latencies):.0f} ms（不含端点等待）"
        if concurrent_latencies:
            summary += f"；并发{pcm_label if package.task == 'tts' else '结束后计算'} p95 {percentile(concurrent_latencies):.0f} ms"
    marker = read_json(store.model_path(package) / ".installed.json", {}) if installed else {}
    disk_bytes = sum(v.get("size", 0) for v in marker.get("files", {}).values())
    selected = selections.get(f"{language}:{scenario}:{package.task}", {})
    return (
        {
            "id": package.id,
            "excluded": excluded,
            "name": package.name,
            "task": package.task.upper(),
            "streaming": package.streaming,
            "device": device,
            "deviceNote": device_profile(package)["note"],
            "gpuSupported": device_profile(package)["cuda"],
            "vramEstimateMiB": device_profile(package)["vram_mb"],
            "notes": package.notes,
            "license": package.license_note,
            "source": package.sources[0],
            "downloadBytes": package.download_bytes,
            "downloadMiB": round(package.download_bytes / 1024**2, 1),
            "evaluationBudgetMiB": package.evaluation_budget_mb,
            "unpackedLimitMiB": round(
                sum(f.unpacked_limit or f.size for f in package.files) / 1024**2
            ),
            "installed": installed,
            "downloadable": downloadable,
            "benchmarkable": permitted,
            "reason": reason,
            "installedMiB": round(disk_bytes / 1024**2, 1),
            "measured": ready,
            "measurement": summary,
            "measurementStats": _measurement_stats(ready, average, latencies, metrics, report, concurrent_latencies),
            "recommended": False,
            "latencyScore": local_p95 if local_p95 != float("inf") else -1,
            "withinRealtimeBudget": within_budget,
            "selected": selected.get("id") == package.id
            and (not identity_for_row(store.root, package, device) or selected.get("voice_id") == identity_for_row(store.root, package, device).get("voice_id"))
            and selected.get("fingerprint") == package.fingerprint
            and selected.get("runtime_version") == runtime_version(package)
            and selected.get("adapter_revision", 1) == adapter_revision(package.adapter),
            "budgetStatus": (
                "本机计算在初步实时预算内，仍需完整语音验收"
                if within_budget
                else "识别平均超过 500 ms，实时对话不推荐"
                if package.task == "stt" and ready
                else "超出初步实时预算，优先考虑朗读/离线处理"
                if ready
                else "需先测速；识别准确率与音质另行验收"
            ),
            "preview": (report.get("preview") or "")
            if report and package.task == "tts"
            else "",
        }
    )


def _measurement_stats(ready, average, latencies, metrics, report, concurrent_latencies):
    if not ready:
        return {}
    return {
        "average_ms": average, "p95_ms": percentile(latencies),
        "peak_mib": metrics.get("peak_process_rss_bytes", 0) / 1024**2,
        "repeats": report["repeats"],
        "concurrent_p95_ms": percentile(concurrent_latencies),
    }
