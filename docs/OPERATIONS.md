# Operations

Commands for deploying, testing, restarting, inspecting and removing the
lab. All of these were used during the build, which ran between 2026-10-18
and 2026-11-02 on Fedora 44.

## One-time machine setup

```bash
# k3s, pinned
curl -sfL https://get.k3s.io -o /tmp/k3s-install.sh
sudo env INSTALL_K3S_VERSION=v1.36.5+k3s1 INSTALL_K3S_CHANNEL=stable \
  bash /tmp/k3s-install.sh --write-kubeconfig-mode 644
sudo systemctl start k3s
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# helm (installed to ~/.local/bin)

# NVIDIA container toolkit, official repo
curl -sfL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
  | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo
sudo dnf install -y nvidia-container-toolkit

# this workstation's root filesystem runs at ~96 percent, so kubelet's
# default eviction thresholds taint the node. Relax them for the lab:
sudo mkdir -p /etc/systemd/system/k3s.service.d
sudo tee /etc/systemd/system/k3s.service.d/override.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/local/bin/k3s server --kubelet-arg=eviction-hard=memory.available<100Mi,nodefs.available<2Gi,imagefs.available<2Gi,nodefs.inodesFree<2% --kubelet-arg=image-gc-high-threshold=98 --kubelet-arg=image-gc-low-threshold=96
EOF
sudo systemctl daemon-reload && sudo systemctl restart k3s
sudo chmod 644 /etc/rancher/k3s/k3s.yaml

# Fedora firewalld blocks pod-to-pod traffic by default; trust the cluster networks
sudo firewall-cmd --permanent --zone=trusted --add-interface=cni0
sudo firewall-cmd --permanent --zone=trusted --add-interface=flannel.1
sudo firewall-cmd --permanent --zone=trusted --add-source=10.42.0.0/16
sudo firewall-cmd --permanent --zone=trusted --add-source=10.43.0.0/16
sudo firewall-cmd --reload

# model weights (once, ~1.5 GB)
sudo mkdir -p /var/lib/llm-serving-infra/models
sudo chown -R $USER:$USER /var/lib/llm-serving-infra
hf download Qwen/Qwen3-0.6B --local-dir /var/lib/llm-serving-infra/models/qwen3-0.6b
```

Note: k3s auto-detected `nvidia-container-runtime` from the host and
registered the `nvidia` RuntimeClass by itself; no containerd config was
hand-written.

## Deploy

```bash
kubectl apply -f k8s/namespace.yaml -f k8s/runtimeclass.yaml -f k8s/device-plugin.yaml
scripts/deploy-stack.sh        # helm release vllm: router, engine, monitoring
scripts/smoke-test.sh          # real request end to end, metrics presence
```

## Test and inspect

```bash
curl http://localhost:30080/v1/models
curl http://localhost:30080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model": "qwen3-0.6b", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 32}'
kubectl -n llm get pods -o wide
kubectl describe node fedora | grep nvidia.com/gpu
kubectl -n llm logs deployment/vllm-qwen-deployment-vllm --tail=50
kubectl -n llm logs deployment/vllm-deployment-router --tail=50
python3 scripts/benchmark.py --concurrency 16 --requests 96 --output results/my-run.json
python3 scripts/render_results.py   # refresh docs/BENCHMARKS.md
```

## Restart pieces

```bash
kubectl -n llm rollout restart deployment/vllm-qwen-deployment-vllm   # engine
kubectl -n llm rollout restart deployment/vllm-deployment-router      # router
kubectl rollout restart ds/nvidia-device-plugin-daemonset -n kube-system
sudo systemctl restart k3s            # whole cluster control plane; pods restart
```

## Chaos and updates (the demos from Phase 5)

```bash
# kill the engine, watch it come back
kubectl -n llm delete pod -l app.kubernetes.io/name=qwen
kubectl -n llm get pods -w

# config change through helm (engine restarts once, ~3 min)
helm upgrade vllm /path/to/production-stack/helm -n llm \
  --values helm/values/vllm-stack.yaml \
  --set servingEngineSpec.modelSpec[0].vllmConfig.maxNumSeqs=32
# then re-apply probes, see scripts/deploy-stack.sh for the exact patch
```

## Remove

```bash
scripts/teardown.sh          # workloads + namespace, cluster stays
scripts/teardown.sh --full   # also k3s uninstall, agent unit, model cache
```

`--full` runs `k3s-uninstall.sh`, removes /var/lib/llm-serving-infra, the
CPU-agent unit and the node. Run it with sudo.

## GPU sharing experiment

docs/GPU_SHARING.md has the full procedure (device plugin time-slicing
config, two-instance deployment, measured comparison) and the revert
commands.
