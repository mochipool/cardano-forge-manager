# Cardano Forge Manager CRDs

This Helm chart installs the Custom Resource Definitions (CRDs) required for the Cardano Forge Manager cluster-wide forging system.

## Overview

The Cardano Forge Manager CRDs provide:

- **CardanoLeader CRD**: Tracks local leader election state within a single Kubernetes cluster
- **CardanoForgeCluster CRD**: Manages forge state at the cluster level for cross-cluster deployments
- **RBAC Resources**: ServiceAccount, ClusterRole, and ClusterRoleBinding for proper permissions
- **Multi-tenant Support**: Network and pool identification for managing multiple Cardano pools
- **Health Check Integration**: Automatic failover based on cluster health monitoring
- **Priority-based Coordination**: Ensures only the highest priority cluster forges blocks

## Installation

### Install CRDs Only

```bash
# Install CRDs with default configuration
helm install cardano-forge-crds ./charts/cardano-forge-crds \
  --namespace cardano-system \
  --create-namespace
```

```bash
# Install with custom values (only useful for testing, use defaults otherwise)
helm install cardano-forge-crds ./charts/cardano-forge-crds -f custom-values.yaml
```

### Install as Dependency

Add to your `Chart.yaml`:

```yaml
dependencies:
- name: cardano-forge-crds
  version: "2.0.0"
  repository: "file://./charts/cardano-forge-crds"
  condition: cardano-forge-crds.enabled
```

Then in your `values.yaml`:

```yaml
cardano-forge-crds:
  enabled: true
  crds:
    create: true
  rbac:
    create: true
```

## Configuration

### Global Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.commonLabels` | Labels to add to all resources | `{}` |
| `global.commonAnnotations` | Annotations to add to all resources | `{}` |

### CRD Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `crds.create` | Whether to install CRDs | `true` |
| `crds.group` | CRD API group | `cardano.io` |
| `crds.version` | CRD API version | `v1` |
| `crds.cardanoLeader.enabled` | Create CardanoLeader CRD | `true` |
| `crds.cardanoLeader.keepOnDelete` | Keep CardanoLeader CRD when chart is uninstalled | `true` |
| `crds.cardanoForgeCluster.enabled` | Create CardanoForgeCluster CRD | `true` |
| `crds.cardanoForgeCluster.keepOnDelete` | Keep CardanoForgeCluster CRD when chart is uninstalled | `true` |

### RBAC Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rbac.create` | Create RBAC resources | `true` |
| `rbac.serviceAccount.create` | Create ServiceAccount | `true` |
| `rbac.serviceAccount.name` | ServiceAccount name (auto-generated if empty) | `""` |
| `rbac.clusterRole.create` | Create ClusterRole | `true` |
| `rbac.clusterRole.name` | ClusterRole name (auto-generated if empty) | `""` |
| `rbac.clusterRoleBinding.create` | Create ClusterRoleBinding | `true` |
| `rbac.clusterRoleBinding.name` | ClusterRoleBinding name (auto-generated if empty) | `""` |

### Example Instances

| Parameter | Description | Default |
|-----------|-------------|---------|
| `examples.create` | Create example CardanoForgeCluster instances | `false` |
| `examples.clusters` | List of example cluster configurations | `[]` |

## Custom Resource Definitions

### CardanoLeader Resource

**Purpose**: Tracks local leader election state within a single Kubernetes cluster.

**Used By**: `forgemanager.py` for pod-level leadership within a namespace.

#### Example Configuration

```yaml
apiVersion: cardano.io/v1
kind: CardanoLeader
metadata:
  name: cardano-leader
  namespace: cardano-mainnet
spec:
  description: "Leader tracking for mainnet block producer"
status:
  leaderPod: "cardano-producer-0"
  forgingEnabled: true
  lastTransitionTime: "2025-10-02T12:00:00Z"
  reason: "LeaderElected"
  message: "Pod cardano-producer-0 elected as leader"
```

#### Status Fields

```yaml
status:
  leaderPod: "cardano-producer-0"          # Current leader pod name
  forgingEnabled: true                      # Whether forging is active
  lastTransitionTime: "2025-10-02T12:00:00Z"  # Last leadership change
  reason: "LeaderElected"                   # Machine-readable reason
  message: "Pod elected as leader"          # Human-readable message
```

### CardanoForgeCluster Resource

**Purpose**: Manages cluster-wide forge state and coordination across multiple regions.

**Used By**: `cluster_manager.py` for cross-cluster coordination.

#### Example Configuration

```yaml
apiVersion: cardano.io/v1
kind: CardanoForgeCluster
metadata:
  name: mainnet-mypool-us-east-1
  namespace: cardano-mainnet
spec:
  network:
    name: mainnet
    magic: 764824073
    era: conway
  pool:
    id: pool1abcd1234567890abcd1234567890abcd1234567890abcd1234
    idHex: "a1b2c3d4e5f6789012345678901234567890123456789012345678901234"
    name: "My Cardano Stake Pool"
    ticker: "MYPOOL"
    description: "A high-performance Cardano stake pool"
  application:
    type: block-producer
    environment: production
    version: "8.9.0"
  region: us-east-1
  forgeState: Priority-based
  priority: 1
  healthCheck:
    enabled: true
    endpoint: "https://monitoring.example.com/health/cluster/us-east-1"
    interval: "30s"
    timeout: "10s"
    failureThreshold: 3
    headers:
      Authorization: "Bearer token123"
  override:
    enabled: false
```

### Status Fields

The CRD automatically populates status fields:

```yaml
status:
  effectiveState: Priority-based
  effectivePriority: 1
  reason: healthy_operation
  message: "Healthy operation: state=Priority-based, priority=1"
  activeLeader: "cardano-producer-0"
  forgingEnabled: true
  lastTransition: "2025-10-02T12:00:00Z"
  healthStatus:
    healthy: true
    lastProbeTime: "2025-10-02T12:00:00Z"
    consecutiveFailures: 0
    message: "All health checks passing"
  conditions:
  - type: Ready
    status: "True"
    lastTransitionTime: "2025-10-02T12:00:00Z"
    reason: ClusterInitialized
    message: "Cluster CRD created successfully"
```

## Usage

### Check CRD Installation

```bash
# Verify both CRDs exist
kubectl get crd cardanoleaders.cardano.io
kubectl get crd cardanoforgeclusters.cardano.io

# View CRD definitions
kubectl describe crd cardanoleaders.cardano.io
kubectl describe crd cardanoforgeclusters.cardano.io
```

### Create Resources

```bash
# Create CardanoLeader instance
kubectl apply -f - <<EOF
apiVersion: cardano.io/v1
kind: CardanoLeader
metadata:
  name: cardano-leader
  namespace: default
spec: {}
EOF

# Create CardanoForgeCluster instance
kubectl apply -f cluster-config.yaml

# View resources
kubectl get cardanoleaders
kubectl get cardanoforgeclusters

# View detailed status
kubectl describe cardanoleader cardano-leader
kubectl describe cardanoforgeCluster mainnet-mypool-us-east-1
```

### Monitor Cluster State

```bash
# Watch cluster status changes
kubectl get cardanoforgeclusters -w

# View detailed status with custom columns
kubectl get cardanoforgeclusters -o custom-columns='NAME:.metadata.name,STATE:.status.effectiveState,PRIORITY:.status.effectivePriority,LEADER:.status.activeLeader,HEALTHY:.status.healthStatus.healthy'
```

## Permissions

The chart creates the following RBAC permissions:

### CardanoLeader Permissions
- `get`, `list`, `watch`, `create`, `update`, `patch` on `cardanoleaders`
- `get`, `update`, `patch` on `cardanoleaders/status`

### CardanoForgeCluster Permissions
- `get`, `list`, `watch`, `create`, `update`, `patch` on `cardanoforgeclusters`
- `get`, `update`, `patch` on `cardanoforgeclusters/status`

### Leader Election Permissions
- `get`, `list`, `watch`, `create`, `update`, `patch`, `delete` on `coordination.k8s.io/leases`

## Uninstallation

### Remove Chart

```bash
# Remove the chart (keeps CRDs by default)
helm uninstall cardano-forge-crds
```

### Remove CRDs (Caution!)

**Warning**: This will delete all CardanoForgeCluster resources and their data!

```bash
# Remove CRDs and all instances
kubectl delete crd cardanoforgeclusters.cardano.io

# Or disable protection first
helm upgrade cardano-forge-crds ./charts/cardano-forge-crds --set crds.cardanoForgeCluster.keepOnDelete=false
helm uninstall cardano-forge-crds
```

## Troubleshooting

### CRD Installation Issues

```bash
# Check CRD status
kubectl get crd cardanoforgeclusters.cardano.io -o yaml

# View installation events
kubectl get events --field-selector involvedObject.kind=CustomResourceDefinition
```

### Permission Issues

```bash
# Check ServiceAccount
kubectl get sa cardano-forge-crds -o yaml

# Check ClusterRole permissions
kubectl describe clusterrole cardano-forge-crds-cluster-role

# Test permissions
kubectl auth can-i create cardanoforgeclusters --as=system:serviceaccount:default:cardano-forge-crds
```

### Validation Errors

```bash
# Validate cluster configuration before applying
kubectl apply --dry-run=client -f cluster-config.yaml

# Check OpenAPI schema
kubectl explain cardanoforgecluster.spec
kubectl explain cardanoforgecluster.status
```

## Contributing

This chart is part of the Cardano Forge Manager project. See the main repository for contribution guidelines:

- **Repository**: https://github.com/mochipool/cardano-forge-manager
- **Issues**: https://github.com/mochipool/cardano-forge-manager/issues
- **Documentation**: https://github.com/mochipool/cardano-forge-manager/tree/main/docs

## License

This chart is licensed under the MIT License. See the main repository for license details.
