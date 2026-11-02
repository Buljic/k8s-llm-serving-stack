# Simulated CPU-only node

## What was tried

The plan was to join a second k3s agent, `lab-cpu-1`, running on the same
physical machine, to exercise multi-node scheduling, taints and DaemonSet
behavior. The script is `scripts/add-cpu-node.sh`. It is a real kubelet
process with its own containerd, remapped ports (kubelet 10260/10261,
kube-proxy 10257/10251, supervisor LB 6446) and its own flannel vxlan
(VNI 2, UDP 8473) to avoid colliding with the main instance.

## What happened

The node joined and registered as Ready. The taint
`node.kubernetes.io/worker-type=cpu-sim:NoSchedule` kept GPU and HostPort
workloads off it. Within two minutes, however, the shared kernel showed the
cost of two kubelets on one host:

- pod sandbox churn on the second agent (`SandboxChanged` loops),
- the NVIDIA device plugin DaemonSet on the GPU node started crash-looping,
- the Grafana pod lost write access to its emptyDir and crash-looped,
- the engine and router pods were restarted by the turbulence.

Stopping the agent recovered the GPU node; the Grafana pod needed a fresh pod
(a delete) to come back. Full removal (node delete, data dir, systemd unit)
returned the lab to a stable state. Cause: two kubelets sharing one kernel
and one cgroup hierarchy fight over sandbox and volume state, and the
flannel VNI remap moved pod CIDR allocations cluster-wide (pod IPs migrated
from 10.42.0.x to 10.42.1.x) mid-flight, which broke running assumptions of
already-started components.

## Verdict

On this workstation the same-host simulated node is not practical as a
side-by-side lab component. The script stays in the repo as the reproducible
record of the experiment. On two real machines the same script (minus the
port remaps) is the normal k3s agent join. This must not be read as
"Kubernetes cannot add nodes"; it reads as "one kernel cannot cleanly host
two nodes of one cluster without isolation".

## What it still shows

- Node registration, labeling and tainting work the same as on real hardware.
- DaemonSet placement across nodes, including why HostPort DaemonSets
  conflict on a shared kernel and need a nodeSelector.
- Why a simulated node adds zero GPUs and zero independent capacity.

The demo pod `cpu-demo` did pull and start on the simulated node before the
churn; the sandbox instability prevented a clean log capture, which is
recorded here rather than smoothed over.
