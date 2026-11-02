# Status

What is done, per phase. Every claim below was checked with a
command on the lab machine; anything I did not check is labeled.

Last full verification pass: 2026-11-02 evening (final smoke test green).

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
  hardware support; see docs/GPU_SHARING.md for the full explanation.

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

## Phase 6, GPU sharing

- MIG: not supported by the RTX 3090. Evidence and explanation in
  docs/GPU_SHARING.md (`nvidia-smi mig -lgip` returns "No MIG-supported
  devices found"). No substitute was faked.
- Time-slicing: device plugin config with replicas 2 exposes
  `nvidia.com/gpu.shared: 2` (k8s/device-plugin-timesliced.yaml). Two
  vLLM instances at 0.35 utilization each ran on the one physical GPU;
  `nvidia-smi` showed both compute processes on device 0, 12.8 GB used.
- Measured comparison (concurrency 16, 96 requests, 256 max tokens):
  single instance 4,439.4 tok/s, TPOT p50 3.4 ms; sliced pair 2,375.6
  tok/s, TPOT p50 6.5 ms. Sharing halves throughput and doubles TPOT.
- Experiment fully reverted; node back to `nvidia.com/gpu: 1`, engine
  serving.

## Stability incidents worth remembering

- Simulated same-host agent node (see docs/SIMULATED_NODE.md) wedged the
  kubelet device manager afterwards: the device plugin could not
  re-register and the node reported zero GPUs while `nvidia-smi` showed the
  card idle. A k3s restart cleared it; pods with pre-churn pod IPs then
  needed recreation to regain API connectivity. All recovered; the
  sequence is recorded here because it cost real debugging time.
- The same episode left CoreDNS, metrics-server and traefik with stale pod
  IPs; each needed one pod recreation. After that, every pod in the cluster
  reports healthy, `kubectl top` works, Grafana panel queries return live
  frames, and the smoke test passes end to end. Final pass: 2026-11-02.

## Phase 4, monitoring

- kube-prometheus-stack (bundled in the chart release) scrapes the engine
  ServiceMonitor and the router ServiceMonitor. Prometheus on NodePort 30900,
  Grafana on NodePort 30300 (admin / k8s-serving).
- Live data observed, 2026-11-02: `vllm:num_requests_running` sampled at 16
  during a concurrency-16 run with GPU at 100 percent; TTFT histograms
  (`vllm:time_to_first_token_seconds_*`) populated; 330 engine metric series
  scraped. Grafana has the two vLLM dashboards plus the Kubernetes fleet
  dashboards. Waiting stayed at 0 at scrape instants in the 96-concurrency
  arm; the queueing shows up in latency percentiles instead (p50 1,404 ms).

## Phase 5, production behavior

- Concurrent benchmark arms (scripts/benchmark.py, results committed):
  conc 4 x 32 reqs: 1,402.7 output tok/s, TTFT p50 12.2 ms, TPOT p50 2.7 ms.
  conc 16 x 64 reqs: 4,743.1 tok/s, TTFT p50 24.1 ms. conc 16 x 96 reqs x
  512 tokens: latency p50 770 ms. conc 96: latency p50 1,404 ms, p95 2,475 ms.
- Pod failure: engine pod deleted 19:40:47; router returned a clean
  "temporarily unavailable" during the gap; replacement ready in about 34 s;
  requests succeeded after. Startup probe events visible on the new pod.
- Rolling update: maxNumSeqs 64 to 32 via helm upgrade; terminate-first
  rollout completed in about 79 s (that downtime is the price of having one GPU);
  new pod serves with `--max-num-seqs 32`.
- Service discovery: the router lists engine pods through the Kubernetes API
  with a namespace-scoped RBAC role; no Pod IPs appear in any config.
- Simulated multi-node: attempted and rolled back, see
  docs/SIMULATED_NODE.md. Not feasible side-by-side on this host; no GPUs
  were implied or added.

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
