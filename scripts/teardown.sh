#!/usr/bin/env bash
# Remove the lab. Two levels:
#   scripts/teardown.sh          remove the workloads (helm releases, lab namespace)
#   scripts/teardown.sh --full   also remove the k3s cluster itself and the model dir
set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

echo "Removing helm releases..."
helm uninstall vllm -n llm --wait --ignore-not-found 2>/dev/null || true
helm uninstall vllm-sliced -n llm --wait --ignore-not-found 2>/dev/null || true

echo "Removing lab namespace..."
kubectl delete namespace llm --ignore-not-found --wait=true

echo "Removing GPU test pod leftovers..."
kubectl delete pod gpu-test -n llm --ignore-not-found 2>/dev/null || true

if [ "${1:-}" = "--full" ]; then
  echo "Removing the CPU-only simulated agent node..."
  systemctl stop k3s-agent-cpu 2>/dev/null || true
  systemctl disable k3s-agent-cpu 2>/dev/null || true
  kubectl delete node lab-cpu-1 --ignore-not-found 2>/dev/null || true
  rm -f /etc/systemd/system/k3s-agent-cpu.service
  systemctl daemon-reload

  echo "Uninstalling k3s (this stops the cluster and removes cluster data)..."
  /usr/local/bin/k3s-uninstall.sh

  echo "Removing model cache..."
  rm -rf /var/lib/llm-serving-infra

  echo "Full teardown complete."
else
  echo "Workloads removed; cluster still up. Re-run with --full to remove k3s."
fi
