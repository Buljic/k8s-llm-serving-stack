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

## What the 3090 does support: time-slicing and software vGPU

Two real sharing modes exist. Neither is MIG.

**Time-slicing** (NVIDIA device plugin): the plugin advertises N units per
physical GPU, pods request `nvidia.com/gpu.shared: 1`, and the GPU
scheduler interleaves kernels from all tenants. All tenants still see the
FULL card: every workload must cap its own memory (for vLLM,
`--gpu-memory-utilization`) or they OOM each other. No memory or fault
boundary exists.

**Software vGPU** (HAMi, open source): a device plugin plus scheduler
extender plus a CUDA interception library. Pods request a device plus
fractions (`nvidia.com/gpumem: 10240`, `nvidia.com/gpucores: 50`), and the
library enforces those fractions inside the container. Verified on this
machine: `nvidia-smi` inside a pod reports `memory.total = 10240 MiB` on a
card that physically has 24576 MiB. That is enforcement, not hardware
partitioning: the limit holds because the library intercepts every CUDA
allocation, and a bypass is possible in principle. MIG enforces in silicon;
HAMi enforces in software.

Config used for time-slicing (k8s/device-plugin-timesliced.yaml): a
ConfigMap with `sharing.timeSlicing.replicas: 2`, the plugin started with
`--config-file`, node then advertises `nvidia.com/gpu.shared: 2` next to
the untouched `nvidia.com/gpu: 1`.

HAMi install for the experiment (not kept running, fully reverted):

```
helm repo add hami https://project-hami.github.io/HAMi/
helm install hami hami/hami --version 2.10.0 -n kube-system \
  --set devicePlugin.runtimeClassName=nvidia
kubectl label node fedora gpu=on        # the plugin's node selector
# pods then set schedulerName: hami-scheduler and request the fractions,
# see k8s/vllm-vgpu.yaml
```

## The experiments

Experiment 1, time-slicing: two vLLM instances, each
`--gpu-memory-utilization 0.35` (about 8.6 GB budget each, 17.2 GB combined
of 24 GB), deployed via k8s/vllm-sliced.yaml, 2 replicas behind one Service
(NodePort 30801). `nvidia-smi` on the host showed two vLLM compute
processes on the one device.

Experiment 2, software vGPU: the same shape through HAMi (chart 2.10.0),
each pod hard-limited to 10240 MiB and 50 percent compute
(k8s/vllm-vgpu.yaml, NodePort 30802). `nvidia-smi` inside each pod reported
a 10240 MiB card, which is the enforcement working.

Same benchmark shape on all arms (concurrency 16, 96 requests, 256 max
tokens, full detail in docs/BENCHMARKS.md):

| Arm | Output tok/s | TTFT p50 (ms) | TPOT p50 (ms) | Latency p50 (ms) |
|---|---|---|---|---|
| Single instance, whole GPU | 4,439.4 | 16.6 | 3.4 | 891.7 |
| Two time-sliced instances | 2,375.6 | 20.7 | 6.5 | 1,669.3 |
| Two HAMi vGPU instances (10 GB, 50 percent each) | 2,377.1 | 20.4 | 6.5 | 1,666.0 |

## What the numbers say

- Aggregate throughput DROPPED to about half in both sharing modes. Two
  engines on one card do not add compute; interleaving and duplicated
  per-instance overhead subtract from it.
- TPOT roughly doubled in both modes: when both instances decode
  simultaneously, each gets about half the SM time. HAMi's 50 percent
  compute quota codifies that split in the scheduler.
- Time-slicing and HAMi measured identically on speed. The difference is
  the contract: time-slicing trusts workloads to stay inside the card;
  HAMi enforces a memory ceiling and a compute share per pod. Neither
  provides a fault boundary.
- The win of sharing is tenancy, not speed: two teams, two model variants,
  or a canary and a stable release coexist on one card with Kubernetes
  scheduling them, at a predictable throughput tax. For multi-tenancy with
  hardware isolation the answer is MIG (not on this card) or separate GPUs.

## Revert

```bash
# time-slicing
kubectl delete -f k8s/device-plugin-timesliced.yaml
kubectl delete -f k8s/vllm-sliced.yaml

# HAMi
helm uninstall hami -n kube-system
kubectl label node fedora gpu-
kubectl delete -f k8s/vllm-vgpu.yaml

# back to the standard lab
kubectl apply -f k8s/device-plugin.yaml
kubectl -n llm scale deployment vllm-qwen-deployment-vllm --replicas=1
```

The stale `nvidia.com/gpu.shared` capacity clears itself within about a
minute of the plugin re-registering.
