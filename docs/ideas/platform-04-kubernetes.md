# Kubernetes: Evaluation for IndicAgent v2.1

**Version:** 1.0
**Status:** draft
**Priority:** low
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-02
**Tags:** kubernetes, orchestration, scaling, hpa, systemd, docker, infrastructure

> **Purpose:** Document Kubernetes fundamentals, evaluate fit for IndicAgent architecture, and provide learning foundation for future container orchestration decisions.

---

## Executive Summary

**Current State:** IndicAgent runs on a single server (192.168.1.158) using:
- systemd for process management
- Docker Compose for infrastructure containers (TimescaleDB, Redpanda, Ollama)
- Prometheus + Grafana for observability
- Manual horizontal scaling (start additional processes)

**Kubernetes Opportunity:** K8s could provide:
- Automated horizontal scaling via HPA
- Self-healing (automatic restart on failure)
- Declarative deployment (YAML manifests)
- Multi-node clustering (geographic distribution)
- Rolling updates with zero-downtime

**Key Question:** Does IndicAgent's architecture benefit enough from K8s to justify the complexity?

---

## Part 1: Kubernetes Fundamentals

### What is Kubernetes?

Kubernetes (K8s) is an open-source container orchestration platform. It automates:
- **Deployment** of containerized applications
- **Scaling** (up/down) based on load
- **Healing** (restart failed containers, reschedule pods)
- **Load balancing** across instances
- **Rolling updates** and **rollbacks**

### Core K8s Concepts

| Concept | Analogy | IndicAgent Equivalent |
|---------|---------|----------------------|
| **Pod** | Smallest deployable unit (1+ containers) | systemd service (e.g., `intelligence-pipeline`) |
| **Deployment** | Manages ReplicaSet (desired state) | Current: manual service management |
| **Service** | Stable network endpoint for pods | Current: no service discovery (direct Kafka) |
| **Namespace** | Isolation boundary for resources | Current: no namespacing (flat processes) |
| **Node** | Worker machine (physical/VM) | Current: single server (192.168.1.158) |
| **Control Plane** | Cluster brain (API server, scheduler, etcd) | Current: N/A (no cluster) |

### Control Plane vs Data Plane

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CONTROL PLANE                                  │
│  (Manages cluster state, makes scheduling decisions)                   │
├─────────────────────────────────────────────────────────────────────────┤
│  • API Server (kube-apiserver)  — Front door for all requests       │
│  • Scheduler (kube-scheduler)    — Decides which node runs pods     │
│  • Controller Manager           — Maintains desired state            │
│  • etcd                       — Cluster state store                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          DATA PLANE (Nodes)                           │
│  (Runs your workloads)                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│  • kubelet                     — Talks to control plane            │
│  • kube-proxy                  — Network routing                   │
│  • Container Runtime           — Runs containers (containerd)     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Workload Resources

| Resource | Use Case | IndicAgent Mapping |
|----------|----------|-------------------|
| **Deployment** | Stateless apps, web servers | `intelligence-pipeline`, `feature-writer` |
| **StatefulSet** | Databases, unique identities | Not needed (DB is separate container) |
| **DaemonSet** | One pod per node | Monitoring agents (if per-node needed) |
| **Job/CronJob** | Run-to-completion tasks | Backfill scripts, periodic maintenance |

### Horizontal Pod Autoscaler (HPA)

**What it does:** Automatically scales number of pods based on metrics.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: intelligence-pipeline-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: intelligence-pipeline
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Pods
        value: 1
        periodSeconds: 60
```

**How it works:**
1. Metrics Server collects CPU/memory from pods (15s interval)
2. HPA controller compares current vs target
3. If `currentMetric > target`: calculate `desiredReplicas = ceil(currentReplicas × (current / target))`
4. Update Deployment replica count
5. Controller creates/deletes pods

**Key behaviors:**
- Scale-down cooldown (default: 5 minutes) prevents flapping
- Stabilization window waits before scaling
- Custom metrics via Prometheus Adapter (for Kafka lag)

---

## Part 2: Kubernetes vs Systemd for IndicAgent

### Current Architecture (Systemd)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Single Server (192.168.1.158)                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  systemd                                                               │
│    ├─→ indicagent-intelligence-pipeline (1 process)                   │
│    ├─→ indicagent-feature-writer (1 process)                          │
│    ├─→ indicagent-signal-writer (1 process)                           │
│    ├─→ indicagent-signal-tracker (1 process)                          │
│    └─→ ... (other services)                                           │
│                                                                         │
│  Docker Compose                                                         │
│    ├─→ timescaledb (container)                                         │
│    ├─→ redpanda (container)                                            │
│    └─→ ollama (container)                                              │
│                                                                         │
│  Scaling: Manual (ssh → systemctl restart)                             │
│  Monitoring: Prometheus + Grafana                                       │
│  Health checks: None (systemd Restart=always)                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Hypothetical Kubernetes Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Kubernetes Cluster                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Namespace: indicagent                                                  │
│                                                                         │
│  Deployments:                                                           │
│    ├─→ intelligence-pipeline (Deployment, 1-10 pods)                   │
│    ├─→ feature-writer (Deployment, 1-3 pods)                           │
│    ├─→ signal-writer (Deployment, 1-3 pods)                            │
│    └─→ signal-tracker (Deployment, 1-2 pods)                           │
│                                                                         │
│  StatefulSet:                                                            │
│    └─→ None (TimescaleDB runs outside cluster)                         │
│                                                                         │
│  Services:                                                              │
│    ├─→ intelligence-pipeline-svc (ClusterIP)                           │
│    └─→ feature-writer-svc (ClusterIP)                                  │
│                                                                         │
│  ConfigMaps:                                                            │
│    └─→ service-config (environment variables)                           │
│                                                                         │
│  HPAs:                                                                  │
│    ├─→ intelligence-pipeline-hpa (metric: kafka_consumer_lag)          │
│    └─→ feature-writer-hpa (metric: persistence_batch_latency)           │
│                                                                         │
│  External Services (StatefulSet managed outside or separate):           │
│    ├─→ timescaledb (StatefulSet or external)                           │
│    └─→ redpanda (StatefulSet or external)                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Trade-offs Analysis

### Kubernetes Advantages for IndicAgent

| Aspect | Kubernetes | Current (Systemd) | IndicAgent Benefit |
|--------|-----------|-------------------|-------------------|
| **Horizontal Scaling** | HPA auto-scales based on metrics | Manual ssh + systemctl | Handle load spikes automatically |
| **Self-Healing** | Auto-restart on crash | systemd Restart=always | Faster recovery, health checks |
| **Zero-Downtime Updates** | Rolling updates (pod by pod) | Stop all → start all | Continuous service during deployments |
| **Multi-Node** | Geographic distribution | Single server | Disaster recovery, regional deployment |
| **Declarative Config** | YAML manifests | Imperative scripts | GitOps, version control, rollback |
| **Service Discovery** | Built-in DNS | None | Dynamic endpoint resolution |
| **Resource Isolation** | CPU/memory limits per pod | Process-level sharing | Prevent runaway agents |

### Kubernetes Disadvantages for IndicAgent

| Aspect | Concern | Impact |
|--------|---------|--------|
| **Complexity** | Steep learning curve | Team must learn K8s (kubectl, manifests, debugging) |
| **Resource Overhead** | Control plane requires resources | ~2 vCPU, 8GB RAM minimum for control plane |
| **Operational Overhead** | Cluster maintenance | Upgrades, security patches, etcd backups |
| **Overkill for Single-Node** | Designed for distributed systems | Current architecture fits single server well |
| **Kafka Consumer Groups** | K8s pod IP addresses change | Consumer group management becomes complex |
| **Stateful Services** | TimescaleDB, Redpanda need special handling | May run outside cluster anyway |

---

## Part 4: Design Considerations for IndicAgent

### Kafka Consumer Groups in Kubernetes

**Challenge:** Each consumer in a Kafka group has a unique `group.instance.id`. When pods restart with new IPs, they may appear as new consumers.

**Solutions:**
1. **Stable consumer group IDs** — Use pod UID as instance.id, persist via StatefulSet
2. **Static pod IPs** — Use hostNetwork with static IP assignment
3. **External Kafka operators** — Use Strimzi or Kafka Operator for cluster management

**IndicAgent-Specific Consideration:**
- `intelligence_pipeline_agent` subscribes to `market.bars` and `market.bars.htf`
- Consumer lag is the primary scaling metric
- Partition assignment matters for HTF data (each pod gets subset of symbols/TFs)

### Stateful Services Strategy

**Option 1: Run Infrastructure Outside Cluster**
```
K8s Cluster (compute agents)  →  Redpanda (external)
                             →  TimescaleDB (external)
```
- Pros: K8s only manages stateless agents, simpler
- Cons: Additional operational complexity (two environments)

**Option 2: StatefulSet for Everything**
```
K8s Cluster →  TimescaleDB StatefulSet
           →  Redpanda StatefulSet
           →  Agent Deployments
```
- Pros: Single environment, GitOps for everything
- Cons: StatefulSets are more complex, storage management overhead

**Recommendation:** Start with Option 1 (compute-only K8s), keep infrastructure containers separate. This aligns with current architecture where DB/Redpanda are already Docker Compose managed.

### Resource Requirements

**Control Plane (Managed vs Self-Managed):**
- AWS EKS (managed): $72/month per cluster
- Self-hosted: 2 vCPU, 8GB RAM minimum

**Worker Nodes (per node):**
- IndicAgent agents are lightweight: ~100-500MB RSS each
- 10 agent pods × 500MB = 5GB RAM minimum per node
- Plus overhead: Recommend 2 vCPU, 4GB RAM per node minimum

**Total for 3-node cluster:**
- 3 × (2 vCPU, 4GB RAM) = 6 vCPU, 12GB RAM for workers
- Plus control plane = ~8 vCPU, 20GB RAM total

### Scaling Metrics for HPA

| Service | Primary Metric | Target | Min/Max Pods |
|---------|---------------|--------|-------------|
| `intelligence-pipeline` | `kafka_consumer_lag` (custom) | <1000 lag | 1 / 10 |
| `feature-writer` | `persistence_batch_latency_seconds` | P95 <1s | 1 / 3 |
| `signal-writer` | `persistence_batch_latency_seconds` | P95 <500ms | 1 / 3 |

**Custom Metrics Setup:** Requires Prometheus Adapter to expose Kafka consumer lag to HPA.

---

## Part 5: Migration Path (If Adopting K8s)

### Phase 1: Containerize Agents (Prerequisite)
1. Build container images for each agent
2. Test locally with `docker run` to verify behavior
3. Push to container registry (ECR, Docker Hub, or private)

### Phase 2: Single-Node Cluster (Proof of Concept)
1. Set up kind/minikube locally for testing
2. Create Deployment manifests for 1-2 agents
3. Verify Kafka connectivity from within pods
4. Test HPA with custom metrics (Kafka lag)

### Phase 3: Multi-Node Production (If Needed)
1. Choose managed (EKS, GKE, AKS) vs self-hosted
2. Set up 3-node cluster for high availability
3. Migrate infrastructure (TimescaleDB, Redpanda) or externalize
4. Gradual cutover: systemd → K8s Deployments

### Phase 4: GitOps & Automation
1. Store manifests in Git repository
2. Use ArgoCD/Flux for declarative deployment
3. Automatic sync on git push
4. Rollback via git revert

---

## Part 6: Decision Framework

### When Kubernetes Makes Sense for IndicAgent

| Scenario | Go K8s? | Reasoning |
|----------|----------|-----------|
| **Current scale (single server)** | **No** | Current architecture works well |
| **Need horizontal scaling** | **Yes** | HPA for auto-scaling based on Kafka lag |
| **Multi-region deployment** | **Yes** | Geographic distribution, disaster recovery |
| **Team has K8s expertise** | **Yes** | Leverages existing skills |
| **Team has no K8s expertise** | **No** | Learning curve too steep |
| **Zero-downtime updates critical** | **Yes** | Rolling updates without service interruption |
| **Resource efficiency is critical** | **No** | K8s overhead ~2 vCPU, 8GB RAM |

### Hybrid Approach (Recommended)

Keep systemd for now, **design K8s-ready architecture**:

1. **Containerize agents** — Build Docker images even if running via systemd
2. **Standardize configurations** — Use ConfigMaps/Secrets patterns
3. **Expose metrics consistently** — Prometheus-compatible
4. **Document deployment** — K8s manifests ready even if not used

This allows future K8s adoption without re-architecture.

---

## Part 7: Learning Resources

### Official Kubernetes Documentation
- [Kubernetes Basics](https://kubernetes.io/docs/tutorials/kubernetes-basics/)
- [Architecture Overview](https://kubernetes.io/docs/concepts/architecture/)
- [Horizontal Pod Autoscaler](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)

### AWS EKS-Specific
- [Amazon EKS Documentation](https://docs.aws.amazon.com/eks/)
- [EKS Best Practices Guide](https://aws.github.io/aws-eks-best-practices/)

### Tools to Learn
- **kind** (Kubernetes in Docker) — Local single-node cluster for testing
- **minikube** — Local development cluster
- **kubectl** — Command-line tool for K8s management

### Practice Exercises
1. Deploy a simple Python app to kind
2. Configure HPA with custom metrics
3. Test rolling updates (watch pods replace one-by-one)
4. Experiment with StatefulSet (simulate database)

---

## Part 8: Key Takeaways

1. **K8s solves real problems** at scale: auto-scaling, self-healing, zero-downtime updates
2. **K8s adds complexity**: learning curve, operational overhead, resource overhead
3. **Current IndicAgent architecture doesn't need K8s yet** — single server works well
4. **Design for future K8s readiness**: containerize, expose metrics, document deployments
5. **HPA is compelling**: Auto-scaling based on Kafka consumer lag is a perfect fit
6. **Stateful services are tricky**: TimescaleDB/Redpanda may remain outside cluster even with K8s

---

## Next Steps

1. **Build container images** for agents (even if not deploying to K8s yet)
2. **Test HPA logic** locally with kind using custom metrics
3. **Evaluate scaling triggers** — at what load does IndicAgent need horizontal scaling?
4. **Document K8s manifests** — have them ready for future use

---

## Appendix: Sample Kubernetes Manifests

### Deployment: Intelligence Pipeline

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: intelligence-pipeline
  namespace: indicagent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: intelligence-pipeline
  template:
    metadata:
      labels:
        app: intelligence-pipeline
    spec:
      containers:
      - name: pipeline
        image: indicagent/intelligence-pipeline:v2.1
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 2000m
            memory: 2Gi
        env:
        - name: KAFKA_BROKERS
          value: "redpanda:9092"
        - name: PROMETHEUS_PORT
          value: "9125"
```

### HPA: Custom Metric (Kafka Consumer Lag)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: intelligence-pipeline-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: intelligence-pipeline
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: kafka_consumer_lag
      target:
        type: AverageValue
        averageValue: 1000
```

---

**Sources:**
- [Kubernetes Concepts - Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-concepts.html)
- [Kubernetes Horizontal Pod Autoscaler](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Kubernetes Architecture Overview](https://kubernetes.io/docs/concepts/architecture/)
