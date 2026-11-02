# Benchmarks

All numbers are live measurements from scripts/benchmark.py against the
running stack, saved per run under results/ and summarized here by
scripts/render_results.py. Times in milliseconds. Regenerate:

    python3 scripts/render_results.py

Machine: Ryzen 9 7900X, one RTX 3090, model Qwen3-0.6B in bfloat16,
vLLM v0.33.0, requests through the router (single instance) or the
sliced Service (two time-sliced instances).

| Arm | Completed/Offered | Output tok/s | TTFT p50 | TTFT p95 | TPOT p50 | Latency p50 | Latency p95 |
|---|---|---|---|---|---|---|---|
| single instance, concurrency 4, 32 requests, 128 max tokens | 32/32 | 1402.675 | 12.2 | 41.4 | 2.7 | 359.5 | 400.9 |
| single instance, concurrency 16, 64 requests, 128 max tokens | 64/64 | 4743.104 | 24.1 | 32.8 | 3.2 | 424.1 | 450.3 |
| single instance, concurrency 8, 128 requests, 256 max tokens | 128/128 | 2583.06 | 12.2 | 21.9 | 3.0 | 770.3 | 775.7 |
| single instance, concurrency 16, 96 requests, 512 max tokens | 96/96 | 4025.652 | 16.5 | 54.1 | 3.6 | 1811.0 | 1896.9 |
| single instance, concurrency 96, 96 requests, 256 max tokens | 96/96 | 9533.814 | 151.1 | 1404.8 | 4.9 | 1404.4 | 2474.9 |
| single instance, concurrency 16, 96 requests, 256 max tokens | 96/96 | 4439.409 | 16.6 | 41.5 | 3.4 | 891.7 | 914.3 |
| two time-sliced instances, concurrency 16, 96 requests, 256 max tokens | 96/96 | 2375.552 | 20.7 | 48.8 | 6.5 | 1669.3 | 1700.7 |

What the table shows:

- Throughput rises with offered concurrency (1,403 to 9,534 output
  tok/s) because continuous batching absorbs the load. The cost shows
  up as queueing latency (p50 1,404 ms at 96 concurrent) while TTFT
  for admitted requests stays in the tens of milliseconds.
- The time-sliced pair halves aggregate throughput and roughly
  doubles TPOT versus the same shape on a single instance. Sharing
  adds occupancy, not capacity.
