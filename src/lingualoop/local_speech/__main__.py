from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import benchmark
from .catalog import load_catalog
from .downloads import ModelStore
from .hardware import detect_hardware
from .library import model_rows
from .storage import default_cache_root


def main():
    parser = argparse.ArgumentParser(
        description="LinguaLoop local speech catalog/evaluation (no cloud requests)"
    )
    parser.add_argument(
        "command", choices=["hardware", "list", "install", "verify", "remove", "benchmark"]
    )
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--root", type=Path, default=default_cache_root())
    parser.add_argument(
        "--language", default="ja", choices=["zh", "en", "ja", "ko", "yue", "de", "fr", "es"]
    )
    parser.add_argument(
        "--scenario", default="conversation", choices=["conversation", "reading", "import"]
    )
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    store, catalog = ModelStore(args.root), load_catalog()
    selected = [next((p for p in catalog if p.id == id), None) for id in args.ids]
    if None in selected:
        parser.error("unknown model id")
    if args.command not in {"hardware", "list"} and not selected:
        parser.error("model id is required")
    if args.command == "hardware":
        result = detect_hardware(args.root)
    elif args.command == "list":
        result = model_rows(
            store, catalog, args.language, args.scenario, detect_hardware(args.root)
        )
    elif args.command == "benchmark":
        result = benchmark(
            store, selected, args.language, wav=args.wav, repeats=args.repeats, threads=args.threads
        )
    else:
        result = {}
        for package in selected:
            if args.command == "install":
                from .hardware import admission

                allowed, reason = admission(package, detect_hardware(args.root))
                if not allowed:
                    raise ValueError(reason)
                result[package.id] = str(store.install(package))
            elif args.command == "verify":
                result[package.id] = store.verify(package)
            else:
                store.uninstall(package)
                result[package.id] = "removed"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
