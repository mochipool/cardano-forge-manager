# Cardano Node Helm Chart - Implementation Progress

## ✅ Completed (Ready to Use)

### Core Chart Files
1. **Chart.yaml** ✅
   - Complete metadata with Forge Manager v2.0 features
   - Dependency on cardano-forge-crds chart
   - Artifact Hub annotations
   - Location: `Chart.yaml`

2. **values.yaml** ✅
   - 599 lines of comprehensive configuration
   - All Forge Manager v2.0 features parameterized
   - Multi-tenant support
   - Cluster management configuration
   - Health check settings
   - Location: `values.yaml`

3. **_helpers.tpl** ✅ 
   - 305 lines of template functions
   - Multi-tenant aware naming
   - Pool ID short form generation
   - Lease and CRD name generation
   - Validation functions
   - Location: `templates/_helpers.tpl`

### RBAC and Security
4. **ServiceAccount** ✅
   - Basic service account template
   - Supports custom annotations
   - Location: `templates/serviceaccount.yaml`

5. **RBAC (Role + RoleBinding)** ✅
   - Permissions for coordination leases
   - CardanoLeader CRD access
   - CardanoForgeCluster CRD access (when cluster management enabled)
   - Location: `templates/rbac.yaml`

### Storage
6. **PersistentVolumeClaim** ✅
   - Dynamic or existing claim support
   - Configurable storage class and size
   - Location: `templates/pvc.yaml`

### Documentation
7. **TODO.md** ✅
   - Complete implementation checklist
   - Priority phases defined
   - Technical considerations documented
   - Location: `TODO.md`

## 🚧 In Progress / Needed

### Critical Templates (Required for MVP)

#### 1. StatefulSet Template (HIGHEST PRIORITY)
**File**: `templates/statefulset.yaml`

**What's Needed**:
- Main cardano-node container with:
  - Command-line arguments for network, config, data dir
  - Environment variables
  - Volume mounts (data, config, secrets, socket)
  - Resource limits
  - Health probes

- Forge Manager v2.0 sidecar (init container with restartPolicy: Always):
  - **Environment Variables** (must include ALL of these):
    ```yaml
    # Basic
    - NAMESPACE (from fieldRef)
    - POD_NAME (from fieldRef)
    - NODE_SOCKET
    - METRICS_PORT
    - LOG_LEVEL
    - SLEEP_INTERVAL
    - SOCKET_WAIT_TIMEOUT
    - DISABLE_SOCKET_CHECK
    
    # Credentials
    - SOURCE_KES_KEY
    - SOURCE_VRF_KEY
    - SOURCE_OP_CERT
    - TARGET_KES_KEY
    - TARGET_VRF_KEY
    - TARGET_OP_CERT
    
    # Lease
    - LEASE_NAME (from helper)
    - LEASE_DURATION
    
    # CRD
    - CRD_GROUP
    - CRD_VERSION
    - CRD_PLURAL
    - CRD_NAME (from helper)
    
    # Multi-tenant (if enabled)
    - CARDANO_NETWORK
    - NETWORK_MAGIC
    - POOL_ID
    - POOL_ID_HEX
    - POOL_NAME
    - POOL_TICKER
    - APPLICATION_TYPE
    
    # Cluster management (if enabled)
    - ENABLE_CLUSTER_MANAGEMENT
    - CLUSTER_REGION
    - CLUSTER_PRIORITY
    - CLUSTER_ENVIRONMENT
    - HEALTH_CHECK_ENDPOINT
    - HEALTH_CHECK_INTERVAL
    ```
  
  - Volume mounts (secrets, socket dir, target keys dir)
  - Metrics port exposure
  - Resource limits

- Init container for setup:
  - Directory creation
  - Config file copying
  - Byron genesis download
  
- Volumes:
  - PVC for data
  - ConfigMap for config
  - Secret for forging keys
  - emptyDir for socket
  - emptyDir for target keys

- Pod configuration:
  - shareProcessNamespace: true (for SIGHUP signaling)
  - Security contexts
  - Service account

**Reference**: Original chart at `~/git/mainline/kubernetes/deploy/cardano-node/helm/cardano-node/templates/statefulset.yaml`

#### 2. ConfigMap Templates
**Files**: `templates/configmap.yaml`

**What's Needed**:
- **config.json**: Cardano node configuration
  - All settings from values.cardanoNode.config
  - Proper JSON structure
  - Genesis file paths
  - Protocol settings
  - Trace options
  
- **topology.json**: P2P topology
  - Bootstrap peers
  - Local roots
  - Public roots
  - useLedgerAfterSlot

- **Genesis URL file**: byron-genesis.url
  - URL for downloading Byron genesis
  - Based on network

**Reference**: Original chart configmap template

#### 3. Service Templates
**File**: `templates/service.yaml`

**What's Needed**:
Multiple services:

```yaml
# 1. P2P Service (LoadBalancer)
- Port 3001 for cardano-node P2P
- Type: LoadBalancer (configurable)
- Annotations for cloud provider

# 2. Metrics Service (ClusterIP)
- Port 12798 for cardano-node metrics
- Type: ClusterIP

# 3. Forge Manager Metrics Service (ClusterIP)
- Port 8000 for forge manager metrics
- Only if forgeManager.enabled
- Type: ClusterIP

# 4. Submit API Service (ClusterIP) - Optional
- Port 8090 for transaction submission
- Only if submitApi.enabled

# 5. Mithril Service (ClusterIP) - Optional
- Port 9092 for mithril signer
- Only if mithrilSigner.enabled
```

### CR Instance Templates

#### 4. CardanoLeader CR
**File**: `templates/cardanoleader.yaml`

**When Created**: If `forgeManager.enabled: true` AND `legacy.crd.cardanoLeader.enabled: true`

**What's Needed**:
```yaml
apiVersion: cardano.io/v1
kind: CardanoLeader
metadata:
  name: {{ include "cardano-node.cardanoLeaderName" . }}
spec:
  # Optional spec fields if any
status: {}  # Will be updated by forge manager
```

#### 5. CardanoForgeCluster CR
**File**: `templates/cardanoforgeCluster.yaml`

**When Created**: If `clusterManagement.enabled: true`

**What's Needed**:
```yaml
apiVersion: cardano.io/v1
kind: CardanoForgeCluster
metadata:
  name: {{ include "cardano-node.cardanoForgeClusterName" . }}
spec:
  network:
    name: {{ .Values.cardanoNode.network }}
    magic: {{ include "cardano-node.networkMagic" . }}
  pool:
    {{ include "cardano-node.poolMetadata" . | nindent 4 }}
  region: {{ .Values.forgeManager.clusterManagement.region }}
  forgeState: {{ .Values.forgeManager.clusterManagement.forgeState }}
  priority: {{ .Values.forgeManager.clusterManagement.priority }}
  
  {{- if .Values.forgeManager.clusterManagement.healthCheck.enabled }}
  healthCheck:
    enabled: true
    endpoint: {{ .Values.forgeManager.clusterManagement.healthCheck.endpoint }}
    interval: {{ .Values.forgeManager.clusterManagement.healthCheck.interval }}s
    timeout: {{ .Values.forgeManager.clusterManagement.healthCheck.timeout }}s
    failureThreshold: {{ .Values.forgeManager.clusterManagement.healthCheck.failureThreshold }}
    {{- with .Values.forgeManager.clusterManagement.healthCheck.headers }}
    headers:
      {{- toYaml . | nindent 6 }}
    {{- end }}
  {{- end }}
  
  {{- if .Values.forgeManager.clusterManagement.override.enabled }}
  override:
    enabled: true
    reason: {{ .Values.forgeManager.clusterManagement.override.reason }}
    {{- if .Values.forgeManager.clusterManagement.override.expiresAt }}
    expiresAt: {{ .Values.forgeManager.clusterManagement.override.expiresAt }}
    {{- end }}
    {{- if .Values.forgeManager.clusterManagement.override.forcePriority }}
    forcePriority: {{ .Values.forgeManager.clusterManagement.override.forcePriority }}
    {{- end }}
    {{- if .Values.forgeManager.clusterManagement.override.forceState }}
    forceState: {{ .Values.forgeManager.clusterManagement.override.forceState }}
    {{- end }}
  {{- end }}
status: {}  # Will be updated by forge manager
```

### Example Values Files

#### 6. Single-Cluster Block Producer
**File**: `values/single-cluster-block-producer.yaml`

```yaml
replicaCount: 3  # HA within single cluster

cardanoNode:
  network: mainnet
  blockProducer: true
  startAsNonProducing: true

forgeManager:
  enabled: true
  # No cluster management (single cluster)
  clusterManagement:
    enabled: false

persistence:
  size: 400Gi

resources:
  cardanoNode:
    limits:
      cpu: 4000m
      memory: 24Gi
```

#### 7. Multi-Cluster Primary (US-East-1)
**File**: `values/multi-cluster-us-east-1.yaml`

```yaml
replicaCount: 3

cardanoNode:
  network: mainnet
  blockProducer: true
  startAsNonProducing: true

forgeManager:
  enabled: true
  
  multiTenant:
    enabled: true
    pool:
      id: "pool1abcd..."
      ticker: "MYPOOL"
  
  clusterManagement:
    enabled: true
    region: "us-east-1"
    priority: 1  # Highest
    forgeState: "Priority-based"
    
    healthCheck:
      enabled: true
      endpoint: "https://monitoring.example.com/health/us-east-1"
      interval: 30
```

#### 8. Multi-Cluster Secondary (EU-West-1)
**File**: `values/multi-cluster-eu-west-1.yaml`

Same as above but with:
```yaml
forgeManager:
  clusterManagement:
    region: "eu-west-1"
    priority: 2  # Secondary
    healthCheck:
      endpoint: "https://monitoring.example.com/health/eu-west-1"
```

#### 9. Relay Node
**File**: `values/relay-node.yaml`

```yaml
cardanoNode:
  network: mainnet
  blockProducer: false  # Relay

forgeManager:
  enabled: false  # No forge manager needed

# Public topology with more peers
cardanoNode:
  topology:
    bootstrapPeers: [...]
    localRoots:
      - accessPoints: [many public relays]
```

### Documentation

#### 10. README.md
**File**: `README.md`

**Sections Needed**:
1. Overview and Features
2. Prerequisites
3. Quick Start
4. Installation
   - Install CRDs
   - Install chart
5. Configuration Reference
   - All major values
   - Network configurations
   - Multi-tenant setup
   - Cluster management
6. Deployment Scenarios
   - Single-cluster BP
   - Multi-cluster coordination
   - Multi-tenant
   - Relay node
7. Upgrade Guide
8. Troubleshooting
9. Examples

## Testing Commands

Once templates are complete:

```bash
# Build dependencies
cd /home/cascadura/git/cardano-forge-manager/helm-charts
helm dependency build charts/cardano-node

# Lint chart
helm lint charts/cardano-node

# Template test (dry-run)
helm template test charts/cardano-node

# Template with example values
helm template test charts/cardano-node \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml

# Install to cluster (test namespace)
helm install cardano-bp-test charts/cardano-node \
  --namespace cardano-test \
  --create-namespace \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml \
  --dry-run

# Actual install
helm install cardano-bp charts/cardano-node \
  --namespace cardano-mainnet \
  --create-namespace \
  -f my-custom-values.yaml
```

## Key Implementation Notes

### StatefulSet - Forge Manager Sidecar Pattern

Use Kubernetes 1.29+ native sidecar feature:
```yaml
initContainers:
  - name: cardano-forge-manager
    restartPolicy: Always  # This makes it a sidecar!
    image: "{{ .Values.image.forgeManager.repository }}:{{ .Values.image.forgeManager.tag }}"
    env: [all the environment variables listed above]
```

### Environment Variable Conditionals

Use helpers to conditionally include env vars:
```yaml
{{- if eq (include "cardano-node.multiTenantEnabled" .) "true" }}
- name: POOL_ID
  value: {{ .Values.forgeManager.multiTenant.pool.id | quote }}
{{- end }}
```

### Volume Mounts

The forge manager needs access to:
1. `/secrets` - Read-only mount of forging keys secret
2. `/ipc` - Shared emptyDir for node socket
3. `/opt/cardano/secrets` - emptyDir where it copies keys for node

### Validation

At the top of statefulset.yaml:
```yaml
{{- include "cardano-node.validateMultiTenant" . -}}
{{- include "cardano-node.validateClusterManagement" . -}}
```

## Next Steps

1. **Create StatefulSet template** - Most complex, highest priority
2. **Create ConfigMap templates** - Config and topology
3. **Create Service templates** - Multiple services
4. **Create CR templates** - CardanoLeader and CardanoForgeCluster
5. **Create example values** - At least 3-4 scenarios
6. **Create README.md** - Full documentation
7. **Test installation** - Verify all scenarios work

## File Size Estimates

- StatefulSet: ~500-700 lines (complex with all sidecars and conditionals)
- ConfigMap: ~200-300 lines (JSON configs)
- Services: ~150-200 lines (multiple services)
- CR templates: ~50-100 lines each
- Example values: ~50-150 lines each
- README: ~500-1000 lines

Total remaining: ~2000-3000 lines of Helm templates

## Resources

- Original chart reference: `~/git/mainline/kubernetes/deploy/cardano-node/helm/cardano-node`
- Forge Manager docs: `/home/cascadura/git/cardano-forge-manager/helm-charts/docs/`
- CRD definitions: `/home/cascadura/git/cardano-forge-manager/helm-charts/charts/cardano-forge-crds/`
