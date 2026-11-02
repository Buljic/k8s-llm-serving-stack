#!/usr/bin/env bash
# Join a second, CPU-only k3s agent to the lab cluster to simulate a larger
# cluster. It is a real kubelet process, but it runs on the SAME physical
# machine as the server. It has no GPU. It exists to exercise scheduling,
# labels, taints and DaemonSet behavior across nodes, not to add capacity.
#
# Because both agents share one kernel, every listening port of the second
# agent is remapped (kubelet 10260/10261, kube-proxy metrics/healthz) and its
# flannel vxlan uses VNI 2 / UDP 8473. This is simulation, documented as such.
set -euo pipefail

NODE_NAME="${NODE_NAME:-lab-cpu-1}"
DATA_DIR="${DATA_DIR:-/var/lib/rancher/k3s-agent2}"
SERVER_IP="${SERVER_IP:-192.168.0.19}"
K3S_VERSION="v1.36.5+k3s1"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

if [ "$EUID" -ne 0 ]; then
  echo "run with sudo (systemd unit install and /var/lib paths):"
  echo "  sudo $0"
  exit 1
fi

TOKEN=$(cat /var/lib/rancher/k3s/server/node-token)

mkdir -p "$DATA_DIR"
cat > "$DATA_DIR/flannel.json" <<'EOF'
{
  "Network": "10.42.0.0/16",
  "Backend": {"Type": "vxlan", "VNI": 2, "Port": 8473}
}
EOF

curl -sfL https://get.k3s.io -o /tmp/k3s-agent-install.sh

cat > /etc/systemd/system/k3s-agent-cpu.service <<EOF
[Unit]
Description=k3s CPU-only simulated agent node (same physical machine)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
Environment=K3S_URL=https://${SERVER_IP}:6443
Environment=K3S_TOKEN=${TOKEN}
ExecStart=/usr/local/bin/k3s agent \
  --node-name ${NODE_NAME} \
  --data-dir ${DATA_DIR} \
  --node-label node.kubernetes.io/worker-type=cpu-sim \
  --flannel-conf ${DATA_DIR}/flannel.json \
  --lb-server-port 6446 \
  --kubelet-arg=port=10260 \
  --kubelet-arg=healthz-port=10261 \
  --kube-proxy-arg=bind-address=127.0.0.1 \
  --kube-proxy-arg=healthz-bind-address=127.0.0.1:10257 \
  --kube-proxy-arg=metrics-bind-address=127.0.0.1:10251
KillMode=process
Delegate=yes
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now k3s-agent-cpu

# HostPort DaemonSets cannot run twice on one kernel. Pin them to the main
# node; on a real multi-machine cluster this patch would not be needed.
kubectl taint nodes "$NODE_NAME" node.kubernetes.io/worker-type=cpu-sim:NoSchedule --overwrite
kubectl -n kube-system patch ds svclb-traefik --type merge \
  -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "fedora"}}}}}'
kubectl -n llm patch ds vllm-prometheus-node-exporter --type merge \
  -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "fedora"}}}}}'

kubectl get nodes -o wide
echo "Node $NODE_NAME joined from the same physical machine. No GPU was added."
