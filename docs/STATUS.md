# Status

What is done, per phase. Every claim below was checked with a
command on the lab machine; anything I did not check is labeled.

## Phase 1, cluster and GPU

- k3s v1.36.5+k3s1 on Fedora 44, single control-plane node named `fedora`.
- NVIDIA Container Toolkit from the official NVIDIA rpm repo, driver 615.78.08,
  CUDA 13.4 on the host.
- k3s auto-detected `nvidia-container-runtime`; no manual containerd config needed.
  RuntimeClass `nvidia` registered.
- Device plugin nvcr.io/nvidia/k8s-device-plugin v0.20.1 (pinned by digest) as a
  DaemonSet; node reports `nvidia.com/gpu: 1`.
- Verification: pod `gpu-test` in namespace `llm` ran `nvidia-smi` inside a
  container and printed the RTX 3090. Completed 2026-10-18.

Notes and deviations:

- The root filesystem sits at 96 percent used, so kubelet's default eviction
  thresholds tainted the node with disk pressure immediately. The lab relaxes them
  with a systemd drop-in (`/etc/systemd/system/k3s.service.d/override.conf`):
  eviction-hard at 2 GiB free absolute, image GC at 98/96 percent. This is a lab
  trade-off on a shared workstation, not a production recommendation.
- MIG status on this GPU reads `N/A` in nvidia-smi. The RTX 3090 has no MIG
  hardware support.

## Phase 2, vLLM

- Deployment `vllm-qwen` (k8s/vllm-deployment.yaml), image
  vllm/vllm-openai:v0.32.0 pinned by digest, Qwen/Qwen3-0.6B weights from a
  hostPath volume, runtimeClassName nvidia, one nvidia.com/gpu, startup +
  readiness + liveness probes on /health, memory limits 16Gi request / 32Gi cap.
- Service `vllm-qwen` type NodePort 30800.
- Verification, 2026-10-20: `curl localhost:30800/v1/chat/completions` from the
  host returned generated tokens; usage reported 64 completion tokens;
  nvidia-smi showed 20,727 MiB used and 99 percent utilization during the
  request. Pod startup took about two minutes including CUDA graph capture.

## Phase 3, production stack

- Helm release `vllm` in namespace `llm` from the vLLM production stack chart
  0.1.13 at commit e8cb4959ebfa333714ef468a3aefe158a65a09e6, deployed by
  scripts/deploy-stack.sh.
- Router lmcache/lmstack-router v0.1.13 (digest-pinned) discovers the engine
  pod through the Kubernetes API (RBAC role `vllm-reader`) and serves the
  OpenAI API on NodePort 30080. Engine rollout strategy terminate-first
  (maxSurge 0) because one GPU cannot host the surged replica.
- The chart renders no probes on the engine; deploy-stack.sh patches
  startup/readiness/liveness probes on /health after install, and deletes the
  engine deployment before upgrade because Helm 4 server-side apply conflicts
  with kubectl-owned patched fields.
- Verification, 2026-11-02: chat completion through the router returned
  generated tokens; Prometheus scrapes both engine (330 series) and router
  targets; Grafana has the vLLM dashboards loaded.
- Deviation from the phase plan: the standalone Phase 2 Deployment was removed
  from the cluster when the stack took over the GPU; its manifests stay in the
  repo as the Phase 2 record.

Two problems cost real time, both written up below:
Fedora firewalld blocked pod-to-pod traffic to the pod CIDR (fixed by trusting
cni0/flannel.1/10.42.0.0/16), and the default surge-first rollout deadlocked
on a single GPU.
