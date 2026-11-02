#!/usr/bin/env python3
"""Concurrent benchmark against the serving stack's OpenAI-compatible endpoint.

Measures, per request: TTFT (time to first output token), TPOT (mean time per
output token after the first), end-to-end latency, and output token count.
Aggregates p50/p95/p99 and throughput. Writes one JSON document per run so
results are regenerable artifacts, not hand-copied numbers.

Only stdlib + httpx. The server must be streaming-capable; the router and
vLLM both are.
"""

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import datetime, timezone

import httpx

PROMPTS = [
    "Explain what a Kubernetes Pod is to a junior developer, in a few sentences.",
    "Write a short note on why HTTP keep-alive matters for inference APIs.",
    "Summarize the difference between a Deployment and a StatefulSet.",
    "What is KV-cache reuse in LLM serving? Answer briefly.",
    "List three reasons a readiness probe beats a liveness probe for slow-start containers.",
    "Describe time-slicing versus MIG GPU sharing in two sentences.",
    "Why does a router sit in front of inference workers in production stacks?",
    "Explain the difference between TTFT and TPOT in request latency analysis.",
]


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


async def one_request(client, base, model, prompt, max_tokens, semaphore, results, errors):
    async with semaphore:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        t0 = time.perf_counter()
        ttft = None
        n_chunks = 0
        usage = None
        try:
            async with client.stream(
                "POST", f"{base}/chat/completions", json=payload,
                headers={"Authorization": "Bearer dummy", "Accept": "text/event-stream"},
                timeout=httpx.Timeout(600.0, connect=30.0),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    obj = json.loads(data)
                    if obj.get("usage"):
                        usage = obj["usage"]
                    for _ in obj.get("choices", []):
                        if ttft is None:
                            ttft = time.perf_counter() - t0
                        n_chunks += 1
        except Exception as exc:  # noqa: BLE001 - count every failure
            errors.append({"prompt": prompt[:60], "error": repr(exc)})
            return
        latency = time.perf_counter() - t0
        completion_tokens = (usage or {}).get("completion_tokens") or n_chunks
        # TPOT over the decode phase: total minus TTFT, over tokens after the first.
        tpot = ((latency - ttft) / (completion_tokens - 1)) if completion_tokens > 1 and ttft else None
        results.append(
            {
                "request_id": str(uuid.uuid4())[:8],
                "ttft_s": round(ttft, 6) if ttft is not None else None,
                "tpot_s": round(tpot, 6) if tpot is not None else None,
                "latency_s": round(latency, 6),
                "completion_tokens": completion_tokens,
                "prompt_index": PROMPTS.index(prompt) if prompt in PROMPTS else -1,
            }
        )


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:30080/v1", help="OpenAI base URL")
    ap.add_argument("--model", default="qwen3-0.6b")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--requests", type=int, default=32)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--output", required=True, help="JSON output path")
    ap.add_argument("--label", default="live", help="provenance label, e.g. live, sliced")
    args = ap.parse_args()

    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(args.requests)]
    semaphore = asyncio.Semaphore(args.concurrency)
    results, errors = [], []

    async with httpx.AsyncClient() as client:
        t_start = time.perf_counter()
        await asyncio.gather(
            *[
                one_request(client, args.base, args.model, p, args.max_tokens, semaphore, results, errors)
                for p in prompts
            ]
        )
        wall = time.perf_counter() - t_start

    def stats(key):
        vals = sorted(r[key] for r in results if r.get(key) is not None)
        if not vals:
            return None
        return {
            "n": len(vals),
            "p50_s": round(percentile(vals, 50), 6),
            "p95_s": round(percentile(vals, 95), 6),
            "p99_s": round(percentile(vals, 99), 6),
            "mean_s": round(statistics.fmean(vals), 6),
        }

    total_output_tokens = sum(r["completion_tokens"] for r in results)
    doc = {
        "provenance": args.label,
        "run": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "base": args.base,
            "model": args.model,
            "concurrency": args.concurrency,
            "requests_offered": args.requests,
            "max_tokens": args.max_tokens,
            "prompt_set": "scripts/benchmark.py PROMPTS (8 fixed prompts)",
            "wall_time_s": round(wall, 3),
        },
        "summary": {
            "requests_completed": len(results),
            "requests_failed": len(errors),
            "ttft": stats("ttft_s"),
            "tpot": stats("tpot_s"),
            "latency": stats("latency_s"),
            "output_tokens_total": total_output_tokens,
            "throughput_output_tok_s": round(total_output_tokens / wall, 3) if wall > 0 else None,
        },
        "errors": errors,
        "requests": results,
    }
    with open(args.output, "w") as f:
        json.dump(doc, f, indent=2)
    s = doc["summary"]
    print(f"completed {s['requests_completed']}/{args.requests} in {wall:.1f}s, "
          f"failed {s['requests_failed']}")
    print(f"throughput {s['throughput_output_tok_s']} tok/s")
    for k in ("ttft", "tpot", "latency"):
        if s[k]:
            print(f"{k:8s} p50 {s[k]['p50_s']*1000:.1f} ms  p95 {s[k]['p95_s']*1000:.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())
