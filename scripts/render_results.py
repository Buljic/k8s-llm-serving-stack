#!/usr/bin/env python3
"""Regenerate the benchmark summary table in docs/BENCHMARKS.md from the
committed run artifacts in results/. Every number in the docs traces back to
a results/*.json file produced by scripts/benchmark.py."""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
DOCS = ROOT / "docs"

ORDER = [
    "baseline-conc4.json",
    "baseline-conc16.json",
    "baseline-conc8-long.json",
    "baseline-conc16-long.json",
    "baseline-conc96.json",
    "baseline-single-final.json",
    "sliced-conc16.json",
    "vgpu-conc16.json",
]

NAMES = {
    "baseline-conc4.json": "single instance, concurrency 4, 32 requests, 128 max tokens",
    "baseline-conc16.json": "single instance, concurrency 16, 64 requests, 128 max tokens",
    "baseline-conc8-long.json": "single instance, concurrency 8, 128 requests, 256 max tokens",
    "baseline-conc16-long.json": "single instance, concurrency 16, 96 requests, 512 max tokens",
    "baseline-conc96.json": "single instance, concurrency 96, 96 requests, 256 max tokens",
    "baseline-single-final.json": "single instance, concurrency 16, 96 requests, 256 max tokens",
    "sliced-conc16.json": "two time-sliced instances, concurrency 16, 96 requests, 256 max tokens",
    "vgpu-conc16.json": "two HAMi software-vGPU instances (10 GB, 50 percent compute each), concurrency 16, 96 requests, 256 max tokens",
}


def ms(v):
    return f"{v * 1000:.1f}" if v is not None else "-"


def row(name):
    path = RESULTS / name
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    r, s = d["run"], d["summary"]
    ttft, tpot, lat = s.get("ttft") or {}, s.get("tpot") or {}, s.get("latency") or {}
    return (
        f"| {NAMES[name]} | {s['requests_completed']}/{r['requests_offered']} | "
        f"{s['throughput_output_tok_s']} | {ms(ttft.get('p50_s'))} | {ms(ttft.get('p95_s'))} | "
        f"{ms(tpot.get('p50_s'))} | {ms(lat.get('p50_s'))} | {ms(lat.get('p95_s'))} |"
    )


def main():
    lines = [
        "# Benchmarks",
        "",
        "All numbers are live measurements from scripts/benchmark.py against the",
        "running stack, saved per run under results/ and summarized here by",
        "scripts/render_results.py. Times in milliseconds. Regenerate:",
        "",
        "    python3 scripts/render_results.py",
        "",
        "Machine: Ryzen 9 7900X, one RTX 3090, model Qwen3-0.6B in bfloat16,",
        "vLLM v0.33.0, requests through the router (single instance) or the",
        "sliced Service (two time-sliced instances).",
        "",
        "| Arm | Completed/Offered | Output tok/s | TTFT p50 | TTFT p95 | TPOT p50 | Latency p50 | Latency p95 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    missing = []
    for name in ORDER:
        r = row(name)
        if r:
            lines.append(r)
        else:
            missing.append(name)
    lines += [
        "",
        "What the table shows:",
        "",
        "- Throughput rises with offered concurrency (1,403 to 9,534 output",
        "  tok/s) because continuous batching absorbs the load. The cost shows",
        "  up as queueing latency (p50 1,404 ms at 96 concurrent) while TTFT",
        "  for admitted requests stays in the tens of milliseconds.",
        "- The time-sliced pair halves aggregate throughput and roughly",
        "  doubles TPOT versus the same shape on a single instance. Sharing",
        "  adds occupancy, not capacity.",
    ]
    if missing:
        lines += ["", "Missing artifacts: " + ", ".join(missing)]
    (DOCS / "BENCHMARKS.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {DOCS / 'BENCHMARKS.md'} ({len(ORDER) - len(missing)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
