#!/usr/bin/env bash
# Deploy the vLLM production stack (router + serving engine + monitoring)
# into namespace llm, reproducibly, from a pinned chart commit.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STACK_SHA="e8cb4959ebfa333714ef468a3aefe158a65a09e6"
STACK_DIR="${STACK_DIR:-/tmp/kilo/production-stack-chart}"
NAMESPACE="llm"
RELEASE="vllm"

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

if [ ! -d "$STACK_DIR/helm" ]; then
  git clone --depth 1 https://github.com/vllm-project/production-stack.git "$STACK_DIR"
fi
git -C "$STACK_DIR" fetch --depth 1 origin "$STACK_SHA"
git -C "$STACK_DIR" checkout -q "$STACK_SHA"
helm dependency build "$STACK_DIR/helm" >/dev/null

# Helm upgrades use server-side apply. Fields we patched on the engine
# deployment are owned by kubectl-patch and would conflict on upgrade, so the
# engine deployment is deleted and recreated by helm each deploy. Engine
# downtime is one model-load cycle, about three minutes.
kubectl -n "$NAMESPACE" delete deployment "${RELEASE}-qwen-deployment-vllm" --ignore-not-found --wait=true 2>/dev/null || true

helm upgrade --install "$RELEASE" "$STACK_DIR/helm" \
  --namespace "$NAMESPACE" \
  --values "$REPO_ROOT/helm/values/vllm-stack.yaml" \
  --wait --timeout 15m

# The chart does not render probes on the serving engine. Add them explicitly
# so the engine participates in health checking and restart-on-failure like
# every other pod in this lab.
kubectl -n "$NAMESPACE" patch deployment "${RELEASE}-qwen-deployment-vllm" --type json -p '[
  {"op": "add", "path": "/spec/template/spec/containers/0/startupProbe", "value": {
    "httpGet": {"path": "/health", "port": 8000},
    "periodSeconds": 10, "failureThreshold": 60}},
  {"op": "add", "path": "/spec/template/spec/containers/0/readinessProbe", "value": {
    "httpGet": {"path": "/health", "port": 8000},
    "periodSeconds": 10}},
  {"op": "add", "path": "/spec/template/spec/containers/0/livenessProbe", "value": {
    "httpGet": {"path": "/health", "port": 8000},
    "periodSeconds": 15, "failureThreshold": 6}}
]' || echo "probe patch failed; engine deployment name changed?"

kubectl -n "$NAMESPACE" rollout status "deployment/${RELEASE}-qwen-deployment-vllm" --timeout 15m
kubectl -n "$NAMESPACE" get pods -o wide
echo "Router (OpenAI API): http://localhost:30080/v1"
echo "Grafana:             http://localhost:30300 (admin / k8s-serving)"
echo "Prometheus:          http://localhost:30900"
