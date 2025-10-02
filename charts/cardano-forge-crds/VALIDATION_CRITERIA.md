# Helm Chart Validation Criteria

This document defines the requirements and validation criteria for the Cardano Forge Manager CRDs Helm chart.

## Overview

The Helm chart must provide all Custom Resource Definitions and RBAC resources required by both `forgemanager.py` and `cluster_manager.py` to operate correctly.

## Required CRDs

### 1. CardanoLeader CRD (cardanoleaders.cardano.io)

**Purpose**: Local leader election within a single Kubernetes cluster

**Required By**: `forgemanager.py`

**API Version**: `cardano.io/v1`

**Scope**: Namespaced

#### Environment Variables in forgemanager.py
```python
CRD_GROUP = os.environ.get("CRD_GROUP", "cardano.io")
CRD_VERSION = os.environ.get("CRD_VERSION", "v1")
CRD_PLURAL = os.environ.get("CRD_PLURAL", "cardanoleaders")
CRD_NAME = os.environ.get("CRD_NAME", "cardano-leader")
```

#### Required Spec Fields
- None (status-only resource for tracking local leader)

#### Required Status Fields
- `leaderPod` (string): Name of the current leader pod
- `forgingEnabled` (boolean): Whether forging is currently enabled
- `lastTransitionTime` (string, date-time format): Last leadership transition timestamp

#### Operations Used
- `get_namespaced_custom_object_status` - Read current leader status
- `patch_namespaced_custom_object_status` - Update leader status
- `create_namespaced_custom_object` - Create CardanoLeader instance if not exists

#### Validation Criteria
- ✅ CRD must be namespace-scoped
- ✅ CRD must have status subresource enabled
- ✅ Status fields must be writable without modifying spec
- ✅ Must support multiple instances per namespace (one per pool/network combination)

---

### 2. CardanoForgeCluster CRD (cardanoforgeclusters.cardano.io)

**Purpose**: Cluster-wide forge coordination across multiple regions

**Required By**: `cluster_manager.py`

**API Version**: `cardano.io/v1`

**Scope**: Namespaced (though logically represents cluster-level state)

#### Environment Variables in cluster_manager.py
```python
CRD_GROUP = "cardano.io"
CRD_VERSION = "v1"
CRD_PLURAL = "cardanoforgeclusters"
```

#### Required Spec Fields
```yaml
spec:
  network:
    name: string (enum: mainnet, preprod, preview, custom)
    magic: integer
    era: string (optional, default: "conway")
  pool:
    id: string (pattern: ^pool1[a-z0-9]{51}$)
    idHex: string (pattern: ^[a-f0-9]{56}$)
    name: string (optional, maxLength: 50)
    ticker: string (pattern: ^[A-Z0-9]{1,5}$)
    description: string (optional, maxLength: 255)
  application:
    type: string (optional, enum: block-producer, relay-only, monitoring, custom)
    version: string (optional)
    environment: string (optional, enum: production, staging, development, testing)
  region: string (required, pattern: ^[a-z0-9\-]{2,20}$)
  forgeState: string (enum: Enabled, Disabled, Priority-based, default: Priority-based)
  priority: integer (min: 1, max: 999, default: 100)
  healthCheck:
    enabled: boolean (default: false)
    endpoint: string (format: uri)
    interval: string (pattern: ^[0-9]+[smh]$, default: "30s")
    timeout: string (pattern: ^[0-9]+[smh]$, default: "10s")
    failureThreshold: integer (min: 1, max: 10, default: 3)
    headers: map[string]string (optional)
  override:
    enabled: boolean (default: false)
    reason: string (optional)
    expiresAt: string (format: date-time)
    forcePriority: integer (min: 1, max: 999)
    forceState: string (enum: Enabled, Disabled)
```

#### Required Status Fields
```yaml
status:
  effectiveState: string (enum: Enabled, Disabled, Priority-based)
  effectivePriority: integer
  reason: string
  message: string
  activeLeader: string
  forgingEnabled: boolean
  lastTransition: string (format: date-time)
  observedGeneration: integer
  healthStatus:
    healthy: boolean
    lastProbeTime: string (format: date-time)
    consecutiveFailures: integer
    message: string
    responseTime: string (optional)
  conditions:
    - type: string (enum: Ready, HealthCheckPassing, LeaderElected, Syncing)
      status: string (enum: "True", "False", Unknown)
      lastTransitionTime: string (format: date-time)
      reason: string
      message: string
  networkStatus: (optional)
    network: string
    magic: integer
    syncStatus: string (enum: syncing, synced, behind, unknown)
    tipSlot: integer
    tipHash: string
    epochNo: integer
  poolStatus: (optional)
    poolId: string
    activeStake: string
    delegatorCount: integer
    lastBlockProduced: string (format: date-time)
    blocksProducedEpoch: integer
    blocksExpectedEpoch: integer
```

#### Operations Used
- `get_cluster_custom_object` - Read cluster-wide state (cluster-scoped read)
- `create_cluster_custom_object` - Create CardanoForgeCluster instance
- `patch_cluster_custom_object_status` - Update status fields
- `list_cluster_custom_object` - Watch for changes to all clusters
- `watch.stream` - Watch for CRD changes

#### Validation Criteria
- ✅ CRD must be namespace-scoped (NOT cluster-scoped despite name)
- ✅ CRD must have status subresource enabled
- ✅ Status fields must be independently updatable from spec
- ✅ Must support additionalPrinterColumns for kubectl output
- ✅ Must validate pool ID formats (bech32 and hex)
- ✅ Must validate network magic numbers for known networks
- ✅ Must support health check configuration
- ✅ Must support manual override configuration

---

## Required RBAC Permissions

### For CardanoLeader CRD

```yaml
apiGroups: ["cardano.io"]
resources: ["cardanoleaders"]
verbs: ["get", "list", "watch", "create", "update", "patch"]

apiGroups: ["cardano.io"]
resources: ["cardanoleaders/status"]
verbs: ["get", "update", "patch"]
```

### For CardanoForgeCluster CRD

```yaml
apiGroups: ["cardano.io"]
resources: ["cardanoforgeclusters"]
verbs: ["get", "list", "watch", "create", "update", "patch"]

apiGroups: ["cardano.io"]
resources: ["cardanoforgeclusters/status"]
verbs: ["get", "update", "patch"]
```

### For Coordination/Leases (Leader Election)

```yaml
apiGroups: ["coordination.k8s.io"]
resources: ["leases"]
verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

---

## Helm Chart Requirements

### Chart Structure
```
charts/cardano-forge-crds/
├── Chart.yaml                           # Chart metadata
├── values.yaml                          # Default configuration values
├── README.md                            # User documentation
├── VALIDATION_CRITERIA.md              # This file
├── templates/
│   ├── _helpers.tpl                    # Template helpers
│   ├── cardano-leader-crd.yaml         # CardanoLeader CRD
│   ├── cardano-forge-cluster-crd.yaml  # CardanoForgeCluster CRD
│   ├── rbac.yaml                       # ServiceAccount, ClusterRole, ClusterRoleBinding
│   └── examples.yaml                   # Optional example instances
```

### Values.yaml Requirements

Must support configuration for:
- ✅ Enabling/disabling individual CRDs
- ✅ CRD group and version configuration
- ✅ RBAC resource creation
- ✅ ServiceAccount name customization
- ✅ Common labels and annotations
- ✅ CRD retention policy (keep on delete)
- ✅ Example instance creation (for testing)

### Template Requirements

#### CardanoLeader CRD Template
- ✅ Must be conditionally created based on values
- ✅ Must include proper labels and annotations
- ✅ Must support helm.sh/resource-policy annotation
- ✅ Must define status subresource
- ✅ Must include additionalPrinterColumns
- ✅ Must be namespace-scoped

#### CardanoForgeCluster CRD Template
- ✅ Must be conditionally created based on values
- ✅ Must include proper labels and annotations
- ✅ Must support helm.sh/resource-policy annotation
- ✅ Must define status subresource
- ✅ Must include additionalPrinterColumns showing: Network, Pool, State, Priority, Leader, Healthy, Age
- ✅ Must be namespace-scoped
- ✅ Must validate all spec fields with OpenAPI schema
- ✅ Must define all required and optional status fields

#### RBAC Template
- ✅ Must create ServiceAccount if enabled
- ✅ Must create ClusterRole with all required permissions
- ✅ Must create ClusterRoleBinding linking SA to Role
- ✅ Must support custom names for all resources
- ✅ Must be conditionally created based on values

---

## Validation Tests

### Pre-Installation Tests

1. **Helm Lint**
   ```bash
   helm lint ./charts/cardano-forge-crds
   ```
   Expected: No errors or warnings

2. **Helm Template Rendering**
   ```bash
   helm template test ./charts/cardano-forge-crds --debug
   ```
   Expected: Valid YAML output for all templates

3. **Dry-Run Installation**
   ```bash
   helm install test ./charts/cardano-forge-crds --dry-run
   ```
   Expected: Successful dry-run with all resources rendered

### Post-Installation Tests

1. **CRD Existence**
   ```bash
   kubectl get crd cardanoleaders.cardano.io
   kubectl get crd cardanoforgeclusters.cardano.io
   ```
   Expected: Both CRDs exist

2. **CRD Schema Validation**
   ```bash
   kubectl explain cardanoleader.spec
   kubectl explain cardanoleader.status
   kubectl explain cardanoforgeCluster.spec
   kubectl explain cardanoforgeCluster.status
   ```
   Expected: All fields documented and accessible

3. **RBAC Resources**
   ```bash
   kubectl get sa cardano-forge-crds
   kubectl get clusterrole cardano-forge-crds-cluster-role
   kubectl get clusterrolebinding cardano-forge-crds-cluster-role-binding
   ```
   Expected: All RBAC resources exist

4. **Permission Validation**
   ```bash
   kubectl auth can-i create cardanoleaders --as=system:serviceaccount:default:cardano-forge-crds
   kubectl auth can-i update cardanoleaders/status --as=system:serviceaccount:default:cardano-forge-crds
   kubectl auth can-i create cardanoforgeclusters --as=system:serviceaccount:default:cardano-forge-crds
   kubectl auth can-i update cardanoforgeclusters/status --as=system:serviceaccount:default:cardano-forge-crds
   kubectl auth can-i create leases --as=system:serviceaccount:default:cardano-forge-crds
   ```
   Expected: All return "yes"

### Functional Tests

1. **CardanoLeader Instance Creation**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: cardano.io/v1
   kind: CardanoLeader
   metadata:
     name: test-leader
     namespace: default
   spec: {}
   status:
     leaderPod: ""
     forgingEnabled: false
     lastTransitionTime: "2025-10-02T12:00:00Z"
   EOF
   ```
   Expected: Resource created successfully

2. **CardanoLeader Status Update**
   ```bash
   kubectl patch cardanoleader test-leader --type='merge' --subresource=status -p='{
     "status": {
       "leaderPod": "test-pod-0",
       "forgingEnabled": true,
       "lastTransitionTime": "'$(date --iso-8601=seconds)'"
     }
   }'
   ```
   Expected: Status updated without modifying spec

3. **CardanoForgeCluster Instance Creation**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: cardano.io/v1
   kind: CardanoForgeCluster
   metadata:
     name: test-cluster
     namespace: default
   spec:
     network:
       name: preview
       magic: 2
     pool:
       id: pool1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq
       idHex: "0000000000000000000000000000000000000000000000000000000000"
       ticker: "TEST"
     region: us-test-1
     forgeState: Priority-based
     priority: 100
   EOF
   ```
   Expected: Resource created successfully with validation

4. **CardanoForgeCluster Status Update**
   ```bash
   kubectl patch cardanoforgeCluster test-cluster --type='merge' --subresource=status -p='{
     "status": {
       "effectiveState": "Priority-based",
       "effectivePriority": 100,
       "reason": "healthy_operation",
       "message": "Test cluster operating normally"
     }
   }'
   ```
   Expected: Status updated independently from spec

5. **Invalid Spec Validation**
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: cardano.io/v1
   kind: CardanoForgeCluster
   metadata:
     name: invalid-cluster
   spec:
     network:
       name: mainnet
       magic: 999  # Wrong magic for mainnet
     pool:
       id: invalid_pool_id  # Invalid format
     priority: 1000  # Exceeds maximum
   EOF
   ```
   Expected: Validation errors preventing creation

---

## Success Criteria

The Helm chart is considered complete and valid when:

1. ✅ All CRDs are properly defined with correct schemas
2. ✅ All required RBAC resources are created
3. ✅ All validation tests pass
4. ✅ Documentation is comprehensive and accurate
5. ✅ Chart can be installed and uninstalled cleanly
6. ✅ CRDs are retained on uninstall (if keepOnDelete=true)
7. ✅ Both forgemanager.py and cluster_manager.py can successfully:
   - Create CRD instances
   - Read CRD instances
   - Update CRD status fields
   - Watch for CRD changes
   - Perform leader election via leases

---

## References

- forgemanager.py: Lines 33-36, 355-445 (CardanoLeader usage)
- cluster_manager.py: Lines 51-53, 332-446 (CardanoForgeCluster usage)
- Kubernetes CRD documentation: https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/
- Helm Best Practices: https://helm.sh/docs/chart_best_practices/