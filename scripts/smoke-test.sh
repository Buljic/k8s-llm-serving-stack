#!/usr/bin/env bash
# Smoke test: the acceptance path. A real HTTP request through the router,
# real tokens back from vLLM on the GPU, plus pod and metrics presence checks.
# Exits non-zero on any failure. Run: scripts/smoke-test.sh
set -euo pipefail

BASE="${BASE:-http://localhost:30080}"
MODEL="${MODEL:-qwen3-0.6b}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

echo "[1/5] node GPU capacity"
kubectl describe node | grep -q 'nvidia.com/gpu' || { echo "FAIL: no GPU capacity"; exit 1; }
echo "  ok"

echo "[2/5] engine and router pods running"
kubectl -n llm get pods -o wide | grep -E 'vllm|router'
kubectl -n llm wait --for=condition=ready pod -l app.kubernetes.io/name=qwen --timeout 300s
echo "  ok"

echo "[3/5] request through the router -> generated tokens"
RESP=$(curl -sf "$BASE/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"Say the word infrastructure and nothing else.\"}], \"max_tokens\": 32, \"temperature\": 0}")
echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); t=d['choices'][0]['message']['content']; assert t.strip(), 'empty completion'; print('  completion:', t[:120].replace(chr(10),' '))"

echo "[4/5] engine /metrics exposes vLLM series"
kubectl -n llm port-forward svc/vllm-qwen-engine-service 18000:8000 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
sleep 3
curl -sf localhost:18000/metrics | grep -q 'vllm:num_requests_running' || { echo "FAIL: vllm metrics missing"; exit 1; }
echo "  ok"

echo "[5/5] Prometheus scraped the engine"
curl -sf "http://localhost:30900/api/v1/query?query=up{job=~'.*vllm.*'}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert any(r['value'][1]=='1' for r in d['data']['result']), 'vllm target not up in prometheus'; print('  ok')"

echo "SMOKE TEST PASSED"
