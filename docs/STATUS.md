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
