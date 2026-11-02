# Architecture

## Physical to request, one layer at a time

| Layer | In this lab | Production analogue |
|---|---|---|
| GPU | 1x RTX 3090, 24 GB, driver 615.78.08 | H100/A100/L40S fleets, MIG or whole cards |
| Node | 1 k3s server (control-plane + worker) on Fedora 44 | Managed node pools, kubeadm, EKS/GKE/AKS |
| GPU exposure | NVIDIA container toolkit on the host, k3s auto-registers the nvidia runtime, RuntimeClass `nvidia`, device plugin DaemonSet advertises `nvidia.com/gpu: 1` | Same mechanism at any scale |
| Inference | vLLM v0.33.0 pod, Qwen3-0.6B bf16, ~20.7 GB VRAM at 0.85 utilization, probes on /health | vLLM/TGI/TRT-LLM fleets, larger models, multi-GPU tensor parallel |
| Routing | lmcache router (production-stack) discovers engine pods via the Kubernetes API, round-robins the OpenAI API | Envoy/NGINX/gRPC L7, service meshes |
| Monitoring | kube-prometheus-stack scrapes engine + router ServiceMonitors, two vLLM Grafana dashboards | Same, plus long-term storage and alerting |
| API surface | NodePort 30080 (router), 30900 (Prometheus), 30300 (Grafana) | LoadBalancer / Ingress with TLS |

## Request path

1. A client POSTs to `localhost:30080/v1/chat/completions`. The NodePort
   Service forwards to any healthy router pod.
2. The router keeps an in-memory view of engine pods. It builds that view by
   watching pods through the Kubernetes API (namespace-scoped Role
   `vllm-reader` lets it list and watch). No pod IP is ever written into a
   config file.
3. The router picks an engine and forwards the request. Kubernetes DNS and
   Services are used for the monitoring and API plumbing; pod IPs only live
   in the router's watch cache.
4. vLLM tokenizes, prefills, and decodes on the GPU, streaming tokens back.
5. The engine exposes Prometheus metrics on /metrics; the router re-exports
   aggregated series (QPS, latency, healthy pods, queue depth) on its own
   /metrics. ServiceMonitors tell Prometheus where both are.

## Why the router and the engine scale differently

The router is CPU-only (1 core request, 2 core limit). Replicating it is
cheap: more pods, more replicas, no special hardware. The engine owns the
GPU; replicating it needs another GPU unit. This is the central shape of
serving architecture: a horizontally scalable stateless tier in front of a
hardware-constrained tier. Scaling the first is a replica count; scaling
the second is hardware, time-slicing, or smaller models.

## Single-GPU consequences baked into the config

- Engine rollout strategy is terminate-first (maxSurge 0). A surged replica
  can never schedule while the old pod holds the only GPU; surge-first
  deadlocks (observed during the build).
- Deploys restart the engine, about 3 minutes of downtime for a config
  change. With 2+ GPUs the same change would roll with zero downtime.
- The device plugin is pinned by digest and runs as a DaemonSet, so GPU
  bookkeeping recovers with the node.

## Failure model

- Engine pod deleted: the Deployment recreates it. The router keeps serving
  a clean "temporarily unavailable" error until the new pod passes its
  readiness probe. Measured recovery: about 34 seconds (small model, cached
  image). Observed and recorded on 2026-11-02.
- Router pod deleted: same shape, faster (no GPU, startup under 10 seconds).
- Node lost: everything, because there is one node. That is the
  limit of a one-machine lab.
