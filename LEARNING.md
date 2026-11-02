# Learning notes: Kubernetes serving compared to ASP.NET Core

I come from building ASP.NET Core services, so the way I actually
understood this stack was by mapping each piece onto something I already
know. These are the mappings that held up, plus the places where the
analogy breaks.

## The mental map

| Kubernetes concept | ASP.NET Core analogue | Where the analogy breaks |
|---|---|---|
| Pod | your app process (Kestrel + hosted services in one unit) | A pod is the scheduler's unit, not a machine or a thread; one pod usually runs one container, not your whole app |
| Deployment | `dotnet run` instances behind a script that keeps N copies alive | Declarative: you describe desired state, controllers reconcile forever |
| Service | a load balancer in front of your instances, discovered by name | Cluster-internal DNS name, kube-proxy DNAT, no external LB needed |
| NodePort | exposing Kestrel on a fixed machine port through a reverse proxy | A port range (30000-32767) reserved on every node, iptables/nftables magic behind it |
| Ingress / router | YARP or NGINX in front of apps | Here the router also does inference-aware things: engine discovery, queue-aware balancing |
| ConfigMap / Helm values | appsettings.json + environment variables | Versioned, applied declaratively, diffable; but no strongly typed options binding guardrails |
| Probes | health checks (`/health`) | Three kinds: startup, readiness, liveness. Readiness gates traffic; liveness triggers a kill. Getting this wrong kills healthy-but-slow pods |
| HPA / KEDA | scaling by CPU in app service plans | Can scale on custom metrics, like queue depth in the inference engine |

## The three surprises

1. The GPU is a schedulable resource, much like CPU and memory, but
   only because the device plugin says so. `nvidia.com/gpu: 1` in the pod
   spec looks like `requests: cpu: 4`. Behind it: container toolkit,
   runtime class, device plugin, kubelet device manager. In .NET terms it
   is as if Kestrel could only start when a co-processor driver handed out
   a token.

2. Rolling updates are not free. In IIS or a container behind a load
   balancer, surge-then-drain is the default and it just works. On one GPU,
   the surged replica can never start because the old pod still holds the
   card. The fix (terminate first) means config changes cost one restart,
   about 3 minutes here. Capacity planning and deployment strategy are the
   same problem.

3. Routing happens inside the cluster. In .NET I would point YARP at
   instance addresses registered in Consul or Eureka. Here the router
   watches Kubernetes pods directly through the API. Service discovery is
   not a sidecar or a library, it is the platform.

## What stayed familiar

- Health-check-driven traffic gating works the same as ASP.NET health
  checks gating a load balancer.
- The OpenAI API surface on top of vLLM is just an HTTP contract; nothing
  about calling it differs from calling any REST API.
- Metrics are metrics. Prometheus scrapes /metrics like any telemetry
  endpoint; Grafana is Grafana.

## Numbers that taught me something

All live, all reproducible via scripts/benchmark.py and results/:

- TTFT and TPOT measure different bottlenecks. TTFT stayed in the tens of
  milliseconds even at 96 concurrent requests; latency p50 hit 1.4 seconds.
  The queue waits, the prefill does not.
- Throughput on one small model rose to about 9,500 output tokens/s at 96
  concurrent requests, which means continuous batching absorbed six times
  the offered load of the first arm with linear latency cost.
- Time-slicing two vLLM instances halved aggregate throughput. Sharing is
  tenancy, not capacity.
