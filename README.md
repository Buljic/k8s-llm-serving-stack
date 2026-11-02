# k8s-llm-serving-stack

I have one RTX 3090 on my workstation and I wanted to learn how a real LLM
serving deployment behaves, not how it looks in a diagram. So I built a
small one: k3s on the same machine, vLLM serving Qwen3-0.6B, the
production-stack router in front of it, Prometheus and Grafana on top.
Everything is real: the GPU, the Kubernetes API, the failures.

The setup stays small on purpose. One node, one card, one model small
enough that the stack fits with room to watch what happens. The
interesting part is not peak throughput. It is scheduling, health checks,
routing and recovery, which are the parts that decide whether a serving
deployment works at all.

## How a request moves

```
client
  -> localhost:30080 (router, NodePort, CPU pod)
    -> router watches engine pods through the Kubernetes API
      -> vLLM pod on the RTX 3090 (runtimeClass nvidia)
        -> tokens back along the same path
```

Prometheus scrapes the engine and the router on NodePort 30900. Grafana
serves the vLLM dashboards on 30300 (admin / k8s-serving).

## Running it

Machine setup (k3s, NVIDIA container toolkit, model download) is in
docs/OPERATIONS.md. With the cluster up:

```bash
scripts/deploy-stack.sh     # router, engine, monitoring, about five minutes
scripts/smoke-test.sh       # a real request through the whole path
python3 scripts/benchmark.py --output results/run.json
```

## What I checked

docs/STATUS.md has the per-phase record with the date each claim was
checked. The short version: tokens came back from vLLM on the card on
2026-10-20; the router, the production stack and the failure drills ran on
2026-11-02, including an engine pod killed and recovered in about 34
seconds and a terminate-first rolling update; the time-slicing and vGPU
comparisons also ran on 2026-11-02. The last full smoke test was on 2026-11-02.

## What I did not do

- There is one GPU. Scaling the inference tier means a smaller model,
  time-slicing, or another card. It does not mean adding workers. The
  measurements are in docs/GPU_SHARING.md.
- The second, CPU-only node I tried on the same host destabilized the
  cluster and was removed. docs/SIMULATED_NODE.md has the sequence.
- MIG is not available on the RTX 3090. That is the card, not a missing
  config.
- No KEDA autoscaling and no multi-model serving. The chart supports
  both; this lab never turned them on.
- Grafana uses a lab password and it is committed here on purpose. Do not
  reuse it.

## Where things are

| Path | What |
|---|---|
| k8s/ | plain manifests: namespace, RuntimeClass, device plugin, test pod, phase deployments |
| helm/values/ | the vllm-stack chart values, pinned versions |
| scripts/ | deploy, smoke test, benchmark, results renderer, node experiment, teardown |
| results/ | one JSON per benchmark run; the docs table is generated from these |
| docs/ | STATUS (what was checked and when), ARCHITECTURE, OPERATIONS, BENCHMARKS, GPU_SHARING, SIMULATED_NODE, LEARNING |
