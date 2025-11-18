# Cardano Node Helm Chart

Deploy highly available Cardano block producer and relay nodes on Kubernetes with **Forge Manager v2.0** for automated leader election and credential management.

## Features

- **High Availability**: StatefulSet with configurable replicas and leader election
- **Forge Manager v2.0**: Automated block production coordination
  - Local leader election (Kubernetes Lease-based)
  - Global cluster coordination (multi-region support)
  - Dynamic credential management (KES, VRF, operational certificates)
  - Health-based failover
- **Multi-Tenant Support**: Run multiple pools in the same Kubernetes cluster
- **Production Ready**: 
  - PodDisruptionBudget for controlled disruptions
  - NetworkPolicy for security
  - ServiceMonitor for Prometheus Operator
  - Configurable resource limits and requests
- **Flexible Deployment**:
  - Block producer or relay mode
  - Single-cluster or multi-cluster
  - Single-tenant or multi-tenant
- **Mithril Integration**: Fast snapshot restore for initial sync
- **Monitoring**: Prometheus metrics for both cardano-node and Forge Manager

## Prerequisites

- Kubernetes 1.29+ (for native sidecar support)
- Helm 3.x
- Storage provisioner capable of creating PersistentVolumes
- (Optional) Prometheus Operator for ServiceMonitor support

## Installation

### 1. Install CRDs

First, install the Cardano Forge Manager CRDs:

```bash
helm install cardano-forge-crds ../cardano-forge-crds \
  --namespace cardano-system \
  --create-namespace
```

### 2. Create Namespace

```bash
kubectl create namespace cardano-mainnet
```

### 3. Create Forging Keys Secret

For block producers, create a secret with your forging keys:

```bash
kubectl create secret generic mainnet-forging-keys \
  --from-file=kes.skey=path/to/kes.skey \
  --from-file=vrf.skey=path/to/vrf.skey \
  --from-file=node.cert=path/to/node.cert \
  --namespace cardano-mainnet
```

### 4. Install the Chart

#### Single-Cluster Block Producer

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set forgeManager.secretName=mainnet-forging-keys \
  -f values/single-cluster-producer.yaml
```

#### Multi-Cluster Block Producer (Primary)

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set forgeManager.secretName=mainnet-forging-keys \
  -f values/multi-cluster-primary.yaml
```

#### Relay Node

```bash
helm install cardano-relay charts/cardano-node \
  --namespace cardano-mainnet \
  -f values/relay-node.yaml
```

#### Multi-Tenant Deployment

Deploy multiple pools in the same cluster:

```bash
# Pool 1
kubectl create secret generic pool1-forging-keys \
  --from-file=kes.skey=pool1/kes.skey \
  --from-file=vrf.skey=pool1/vrf.skey \
  --from-file=node.cert=pool1/node.cert \
  --namespace cardano-multi-tenant

helm install cardano-pool1 charts/cardano-node \
  --namespace cardano-multi-tenant \
  --set forgeManager.secretName=pool1-forging-keys \
  -f values/multi-tenant-pool1.yaml

# Pool 2
kubectl create secret generic pool2-forging-keys \
  --from-file=kes.skey=pool2/kes.skey \
  --from-file=vrf.skey=pool2/vrf.skey \
  --from-file=node.cert=pool2/node.cert \
  --namespace cardano-multi-tenant

helm install cardano-pool2 charts/cardano-node \
  --namespace cardano-multi-tenant \
  --set forgeManager.secretName=pool2-forging-keys \
  -f values/multi-tenant-pool2.yaml
```

## Configuration

### Quick Configuration Examples

```yaml
# Minimal block producer
cardanoNode:
  blockProducer: true
  network: "mainnet"
forgeManager:
  enabled: true
  secretName: "my-forging-keys"

# Multi-tenant with cluster management
forgeManager:
  multiTenant:
    enabled: true
    pool:
      id: "pool1abc..."
      ticker: "MYPOOL"
  clusterManagement:
    enabled: true
    region: "us-east-1"
    priority: 1
```

### Key Configuration Sections

See [`values.yaml`](./values.yaml) for all available options. Key sections:

#### Cardano Node Configuration

```yaml
cardanoNode:
  network: "mainnet"           # Network: mainnet, preprod, preview
  magic: "764824073"           # Network magic number
  blockProducer: true          # Enable block production mode
  startAsNonProducing: true    # Start without credentials (Forge Manager provides)
  
  mithril:
    enabled: true              # Enable Mithril client
    restoreSnapshot: true      # Restore from snapshot on first boot
```

#### Forge Manager Configuration

```yaml
forgeManager:
  enabled: true
  secretName: "forging-keys"   # Secret containing KES, VRF, and cert
  
  # Multi-tenant mode (run multiple pools in same cluster)
  multiTenant:
    enabled: true
    pool:
      id: "pool1abc..."        # Unique pool identifier
      ticker: "MYPOOL"
  
  # Cluster management (multi-region coordination)
  clusterManagement:
    enabled: true
    region: "us-east-1"
    priority: 1                # Lower = higher priority
    healthCheck:
      enabled: true
      endpoint: "http://health-service:8080/health"
```

#### Storage Configuration

```yaml
persistence:
  ledger:
      enabled: true
      size: 400Gi                  # Mainnet requires ~350GB+
      storageClass: "fast-ssd"     # Use fast storage for best performance
```

#### Resource Configuration

```yaml
resources:
  cardanoNode:
    requests:
      cpu: 2000m
      memory: 20Gi
    limits:
      cpu: 4000m
      memory: 24Gi
  forgeManager:
    requests:
      cpu: 200m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 1Gi
```

#### High Availability

```yaml
replicaCount: 3                # Deploy 3 replicas

podDisruptionBudget:
  enabled: true
  minAvailable: 1              # Keep at least 1 pod available during disruptions

affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          topologyKey: kubernetes.io/hostname
```

## Architecture

### Two-Tier Leadership Model

The chart implements hierarchical leadership for block production:

1. **Local Leadership** (within cluster): Kubernetes Lease-based election among pods
2. **Global Leadership** (cross-cluster): Priority and health-based coordination via CRDs

### Components

- **Cardano Node**: The main Cardano blockchain node (block producer or relay)
- **Forge Manager**: Sidecar that manages leader election and credential distribution
- **Custom Resources**:
  - `CardanoLeader`: Local leader state (legacy, within cluster)
  - `CardanoForgeCluster`: Global cluster state (cross-region coordination)

### Leader Election Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Cluster 1 (US-East-1, Priority: 1)                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                     │
│  │ Pod-0   │  │ Pod-1   │  │ Pod-2   │                     │
│  │ Leader  │  │ Standby │  │ Standby │                     │
│  └─────────┘  └─────────┘  └─────────┘                     │
│       │                                                      │
│       └─────> Wins local lease                              │
│               CardanoForgeCluster: Enabled (highest priority)│
│               🟢 FORGING                                     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Cluster 2 (EU-West-1, Priority: 2)                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                     │
│  │ Pod-0   │  │ Pod-1   │  │ Pod-2   │                     │
│  │ Leader  │  │ Standby │  │ Standby │                     │
│  └─────────┘  └─────────┘  └─────────┘                     │
│       │                                                      │
│       └─────> Wins local lease                              │
│               CardanoForgeCluster: Disabled (lower priority) │
│               ⚪ HOT STANDBY                                 │
└─────────────────────────────────────────────────────────────┘
```

If Cluster 1 fails health checks or becomes unavailable:
- Its effective priority increases
- Cluster 2 automatically takes over forging
- When Cluster 1 recovers, it resumes forging

## Deployment Scenarios

### Scenario 1: Single-Cluster HA Block Producer

**Use case**: High availability within a single data center

```bash
helm install cardano-producer charts/cardano-node \
  -f values/single-cluster-producer.yaml
```

**Features**:
- 3 replicas with leader election
- Only the elected leader forges blocks
- Automatic failover within cluster
- No cross-region coordination

### Scenario 2: Multi-Cluster Block Producer

**Use case**: Geographic redundancy with automatic failover

Deploy in multiple regions with priority-based coordination:

```bash
# Primary cluster (US-East-1)
helm install cardano-producer charts/cardano-node \
  -f values/multi-cluster-primary.yaml

# Secondary cluster (EU-West-1)
helm install cardano-producer charts/cardano-node \
  -f values/multi-cluster-secondary.yaml
```

**Features**:
- Active-passive failover across regions
- Health check integration
- Priority-based forge enablement
- Automatic recovery

### Scenario 3: Multi-Tenant (Multiple Pools)

**Use case**: Run multiple independent pools in the same cluster

```bash
# Deploy Pool 1
helm install cardano-pool1 charts/cardano-node \
  -f values/multi-tenant-pool1.yaml

# Deploy Pool 2
helm install cardano-pool2 charts/cardano-node \
  -f values/multi-tenant-pool2.yaml
```

**Features**:
- Complete isolation between pools
- Separate leases, CRDs, and metrics per pool
- Independent leader election
- Efficient resource utilization

### Scenario 4: Relay Node

**Use case**: Public relay node for network connectivity

```bash
helm install cardano-relay charts/cardano-node \
  -f values/relay-node.yaml
```

**Features**:
- No forging credentials
- Mithril snapshot for fast sync
- Lower resource requirements
- Horizontal Pod Autoscaler support

### Scenario 5: Testnet (Preprod/Preview)

**Use case**: Testing and development

```bash
helm install cardano-preprod charts/cardano-node \
  -f values/testnet-preprod.yaml
```

**Features**:
- Reduced resource requirements
- Mithril-enabled for fast sync
- Debug logging
- Development-friendly configuration

## Monitoring

### Prometheus Metrics

The chart exposes metrics for both cardano-node and Forge Manager:

**Cardano Node Metrics** (port 12798):
- `cardano_node_metrics_*`: Node performance and state
- `cardano_node_forge_*`: Block forging statistics

**Forge Manager Metrics** (port 8000):
- `cardano_forging_enabled`: Whether this pod is forging (0 or 1)
- `cardano_leader_status`: Whether this pod is elected leader (0 or 1)
- `cardano_leadership_changes_total`: Total leadership transitions
- `cardano_sighup_signals_total`: SIGHUP signals sent to cardano-node
- `cardano_cluster_forge_enabled`: Cluster-wide forge status
- `cardano_cluster_forge_priority`: Effective priority for cluster

### ServiceMonitor

If using Prometheus Operator:

```yaml
monitoring:
  enabled: true
  serviceMonitor:
    enabled: true
    interval: 30s
```

### Grafana Dashboards

Recommended dashboards:
- **Cardano Node Dashboard**: Monitor node sync, peers, and performance
- **Forge Manager Dashboard**: Track leader election and forge coordination
- **Multi-Cluster Dashboard**: Visualize cluster priorities and failover

## Operational Tasks

### Check Leader Status

```bash
# Check which pod is the leader
kubectl get cardanoleaders -n cardano-mainnet

# Describe leader status
kubectl describe cardanoleader cardano-leader-mainnet-pool1abc -n cardano-mainnet

# Check cluster-wide status (multi-cluster)
kubectl get cardanoforgeclusters -o wide
```

### View Logs

```bash
# Cardano node logs
kubectl logs -f cardano-producer-0 -c cardano-node -n cardano-mainnet

# Forge Manager logs
kubectl logs -f cardano-producer-0 -c forge-manager -n cardano-mainnet

# All containers
kubectl logs -f cardano-producer-0 --all-containers -n cardano-mainnet
```

### Check Metrics

```bash
# Port forward metrics
kubectl port-forward svc/cardano-producer-forge-metrics 8000:8000 -n cardano-mainnet

# Query metrics
curl localhost:8000/metrics | grep cardano_forging_enabled
curl localhost:8000/metrics | grep cardano_leader_status
```

### Manual Failover (Multi-Cluster)

```bash
# Disable primary cluster for maintenance
kubectl patch cardanoforgeCluster mainnet-pool1abc-us-east-1 --type='merge' -p='{
  "spec": {
    "forgeState": "Disabled",
    "override": {
      "enabled": true,
      "reason": "Planned maintenance",
      "expiresAt": "'$(date -d "+4 hours" --iso-8601=seconds)'"
    }
  }
}'

# Re-enable after maintenance
kubectl patch cardanoforgeCluster mainnet-pool1abc-us-east-1 --type='merge' -p='{
  "spec": {
    "forgeState": "Priority-based",
    "override": {"enabled": false}
  }
}'
```

### Rotate KES Keys

```bash
# Update secret with new keys
kubectl create secret generic mainnet-forging-keys-new \
  --from-file=kes.skey=path/to/new/kes.skey \
  --from-file=vrf.skey=path/to/vrf.skey \
  --from-file=node.cert=path/to/new/node.cert \
  --namespace cardano-mainnet

# Update deployment
helm upgrade cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set forgeManager.secretName=mainnet-forging-keys-new \
  --reuse-values

# Delete old secret after verification
kubectl delete secret mainnet-forging-keys -n cardano-mainnet
```

### Scale Replicas

```bash
# For block producers (be cautious - affects leader election)
helm upgrade cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set replicaCount=5 \
  --reuse-values

# For relay nodes (safe to scale freely)
kubectl scale statefulset cardano-relay --replicas=5 -n cardano-mainnet
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl describe pod cardano-producer-0 -n cardano-mainnet

# Check events
kubectl get events -n cardano-mainnet --sort-by='.lastTimestamp'

# Check logs
kubectl logs cardano-producer-0 -c cardano-node -n cardano-mainnet
```

### Leader Election Issues

```bash
# Check lease
kubectl get lease -n cardano-mainnet
kubectl describe lease cardano-leader-mainnet-pool1abc -n cardano-mainnet

# Check CRD status
kubectl get cardanoleaders -n cardano-mainnet -o yaml
```

### Credential Distribution Issues

```bash
# Check if credentials exist in leader pod
kubectl exec -it cardano-producer-0 -c forge-manager -n cardano-mainnet -- \
  ls -la /ipc/

# Check Forge Manager logs for credential operations
kubectl logs cardano-producer-0 -c forge-manager -n cardano-mainnet | grep -i credential
```

### Node Not Syncing

```bash
# Check node tip
kubectl exec -it cardano-producer-0 -c cardano-node -n cardano-mainnet -- \
  cardano-cli query tip --mainnet

# Check topology connections
kubectl exec -it cardano-producer-0 -c cardano-node -n cardano-mainnet -- \
  cat /config/topology.json

# Check P2P connectivity
kubectl exec -it cardano-producer-0 -c cardano-node -n cardano-mainnet -- \
  netstat -an | grep 3001
```

## Security Considerations

- **Secrets**: Forging keys stored as Kubernetes Secrets with restricted permissions
- **RBAC**: Minimal permissions for Forge Manager (leases + CRDs only)
- **Network Policy**: Optional pod-level network isolation
- **Non-root**: All containers run as non-root user (UID 10001)
- **Read-only**: Forging keys mounted read-only, copied with restricted permissions

## Upgrading

### Upgrade Chart

```bash
# Update values if needed
helm upgrade cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  -f values/single-cluster-producer.yaml

# Or reuse existing values
helm upgrade cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --reuse-values
```

### Upgrade CRDs

```bash
# CRDs must be upgraded separately
helm upgrade cardano-forge-crds ../cardano-forge-crds \
  --namespace cardano-system
```

## Uninstallation

```bash
# Remove chart
helm uninstall cardano-producer -n cardano-mainnet

# Remove CRDs (optional - will delete all custom resources!)
helm uninstall cardano-forge-crds -n cardano-system

# Remove namespace
kubectl delete namespace cardano-mainnet
```

## Contributing

Contributions are welcome! Please submit issues and pull requests to the main repository.

## License

This chart is licensed under the Apache License 2.0.

## Support

For issues and questions:
- GitHub Issues: [cardano-forge-manager](https://github.com/your-org/cardano-forge-manager)
- Cardano Forum: [Stake Pool Operator Category](https://forum.cardano.org/c/staking-delegation/)

## References

- [Cardano Node Documentation](https://docs.cardano.org/)
- [Forge Manager v2.0 Documentation](../../docs/)
- [Kubernetes StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Prometheus Operator](https://prometheus-operator.dev/)
