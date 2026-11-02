# GPU sharing on the RTX 3090

## MIG: not available, and not a configuration problem

MIG (Multi-Instance GPU) partitions one physical GPU into hardware-isolated
instances, each with dedicated compute and memory. It exists only on
data-center GPUs (A100, A30, H100, H200, B-series). The RTX 3090 is a
GA102 card and has no MIG support in silicon.

Verified on this machine, 2026-11-02:

```
$ nvidia-smi -q | grep -A2 'MIG Mode'
    MIG Mode
        Current                                        : N/A
$ nvidia-smi mig -lgip
No MIG-supported devices found.
```

`nvidia-smi` inside a GPU container shows the same `MIG M. N/A`. There is
nothing to configure and no fake substitute is presented in this repo.

## What the 3090 does support: time-slicing

The NVIDIA device plugin can advertise N time-sliced units per physical
GPU. Pods request a unit with `nvidia.com/gpu.shared: 1`. This is temporal
sharing: the GPU scheduler interleaves kernels from all tenants. It is not
isolation:

- All tenants see the FULL card. Every workload must cap its own memory
  (for vLLM, `--gpu-memory-utilization`) or they OOM each other.
- One tenant at full compute slows every other tenant.
- There is no memory or fault boundary. A tenant that corrupts the card
  takes everyone with it.

Config used (k8s/device-plugin-timesliced.yaml): a ConfigMap with
`sharing.timeSlicing.replicas: 2`, the plugin started with
`--config-file`, node then advertises `nvidia.com/gpu.shared: 2` next to
the untouched `nvidia.com/gpu: 1`.

## The experiment

Two vLLM instances, each `--gpu-memory-utilization 0.35` (about 8.6 GB
budget each, 17.2 GB combined of 24 GB, leaving headroom for the desktop,
an approved Ollama embedding service and CUDA overhead), deployed via
k8s/vllm-sliced.yaml with 2 replicas behind one Service (NodePort 30801).
Both pods land on the same node and share GPU 0; `nvidia-smi` showed two
vLLM compute processes on the one device.

Same benchmark shape on both arms (concurrency 16, 96 requests, 256 max
tokens, full detail in docs/BENCHMARKS.md):

| Arm | Output tok/s | TTFT p50 (ms) | TPOT p50 (ms) | Latency p50 (ms) |
|---|---|---|---|---|
| Single instance, whole GPU | 4,439.4 | 16.6 | 3.4 | 891.7 |
| Two time-sliced instances | 2,375.6 | 20.7 | 6.5 | 1,669.3 |

## What the numbers say

- Aggregate throughput DROPPED to about half. Two engines timesharing one
  card do not add compute; kernel interleaving and duplicated per-instance
  overhead subtract from it.
- TPOT roughly doubled: when both instances decode simultaneously, each
  gets about half the SM time.
- The win of time-slicing is not speed. It is tenancy: two teams, two model
  variants, or a canary and a stable release can coexist on one card with
  Kubernetes scheduling them, at a predictable throughput tax. For real
  multi-tenancy with isolation, the hardware answer is MIG (unavailable
  here) or separate GPUs.

## Revert

```bash
kubectl delete -f k8s/device-plugin-timesliced.yaml
kubectl apply -f k8s/device-plugin.yaml   # plain single-GPU plugin
kubectl delete -f k8s/vllm-sliced.yaml
kubectl -n llm scale deployment vllm-qwen-deployment-vllm --replicas=1
```

The stale `nvidia.com/gpu.shared` capacity clears itself within about a
minute of the plugin re-registering.
