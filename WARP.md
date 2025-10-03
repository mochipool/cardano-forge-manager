# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Cardano Forge Manager v2.0 is a Kubernetes sidecar container that implements **cluster-aware leader election** and **dynamic credential management** for Cardano block producer nodes. It ensures exactly one node forges blocks globally across multiple geographic regions while maintaining hot standby replicas.

### Key Features
- **Multi-Cluster Coordination**: Cross-region forge management with priority-based failover
- **Multi-Tenant Support**: Run multiple Cardano pools in the same Kubernetes cluster with complete isolation
- **Health-Based Failover**: Automatic failover based on cluster health monitoring
- **Dual Architecture**: Two-tier leadership (local Kubernetes Lease + global CRD-based coordination)

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
make install
# Or manually:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Testing
```bash
# Run all tests
make test

# Run with coverage report (minimum 25%)
make test-coverage

# Run specific test suites
make test-cluster            # Cluster management tests
make test-forgemanager       # Forge manager tests
make test-multi-tenant       # Multi-tenant isolation tests

# Run a single test by name
make test-specific TEST=test_pool_isolation

# Quick test (minimal output)
make quick-test

# Full CI pipeline locally
make ci
```

### Code Quality
```bash
# Lint Python code with flake8
make lint

# Format code with black
make format

# Run all quality checks
make check

# Syntax check only
python -m py_compile src/forgemanager.py src/cluster_manager.py
```

### Local Development
```bash
# Run forge manager locally (requires K8s context and RBAC)
export POD_NAME=test-pod
export NAMESPACE=default
export DISABLE_SOCKET_CHECK=true
export ENABLE_CLUSTER_MANAGEMENT=false
python src/forgemanager.py

# Test with cluster management enabled
export ENABLE_CLUSTER_MANAGEMENT=true
export CLUSTER_REGION=us-test-1
export CLUSTER_PRIORITY=1
export CARDANO_NETWORK=mainnet
export POOL_ID=pool1test123
python src/forgemanager.py
```

### Helm Chart Management
```bash
# Install CRDs
helm install cardano-forge-crds ./charts/cardano-forge-crds \
  --namespace cardano-system --create-namespace

# Verify CRD installation
kubectl get crd cardanoleaders.cardano.io
kubectl get crd cardanoforgeclusters.cardano.io

# View CRD instances
kubectl get cardanoleaders
kubectl get cardanoforgeclusters
kubectl get cardanoforgeclusters -o custom-columns='NAME:.metadata.name,STATE:.status.effectiveState,PRIORITY:.status.effectivePriority,LEADER:.status.activeLeader'
```

### Utilities
```bash
# Show project status
make status

# Show environment information
make env

# List available documentation
make docs

# List deployment examples
make examples

# Clean all generated files and venv
make clean

# Reset environment (clean + install)
make reset
```

## Architecture

### Two-Tier Leadership Model

The system implements hierarchical leadership:

1. **Local Leadership** (within cluster): Kubernetes Lease-based election among pods in a StatefulSet
2. **Global Leadership** (cross-cluster): Priority and health-based coordination via `CardanoForgeCluster` CRD

### Core Components

#### `src/forgemanager.py` - Main Sidecar Application
- Runs as sidecar alongside cardano-node in shared process namespace
- Implements local leader election using Kubernetes coordination leases
- Manages credential distribution (KES, VRF, operational certificates)
- Sends SIGHUP signals to cardano-node for credential reload
- Publishes Prometheus metrics on port 8000
- Updates `CardanoLeader` CRD status

#### `src/cluster_manager.py` - Multi-Cluster Coordination
- Manages `CardanoForgeCluster` CRD for cross-cluster coordination
- Implements priority-based forge enablement decisions
- Performs health check integration (optional HTTP endpoint polling)
- Calculates effective priority based on base priority + health penalties
- Watches all cluster CRDs for state changes (background thread)
- Provides multi-tenant isolation (network + pool scoped resources)

### Custom Resource Definitions

#### CardanoLeader CRD (Legacy, Local Scope)
- Tracks local leader election state within a single cluster
- Updated by `forgemanager.py`
- Status fields: `leaderPod`, `forgingEnabled`, `lastTransitionTime`

#### CardanoForgeCluster CRD (New, Global Scope)
- Manages cluster-wide forge state and coordination
- Updated by `cluster_manager.py`
- Spec fields: `network`, `pool`, `region`, `forgeState`, `priority`, `healthCheck`, `override`
- Status fields: `effectiveState`, `effectivePriority`, `activeLeader`, `forgingEnabled`, `healthStatus`
- Naming convention: `{network}-{pool_short_id}-{region}` (e.g., `mainnet-pool1abc-us-east-1`)

### Multi-Tenant Architecture

Multi-tenant support allows multiple Cardano pools in the same Kubernetes cluster:

**Tenant Identification**:
- `CARDANO_NETWORK`: Network name (mainnet, preprod, preview, or custom)
- `NETWORK_MAGIC`: Network magic number for validation
- `POOL_ID`: Unique pool identifier (bech32 pool ID or any unique string)
- `POOL_ID_HEX`: Optional hex pool ID
- `POOL_TICKER`: Human-readable pool ticker

**Resource Isolation**:
- Lease names: `cardano-leader-{network}-{pool_short_id}`
- CRD names: `{network}-{pool_short_id}-{region}`
- Separate RBAC per pool (optional)
- Metrics labeled with network and pool_id

### Key Mechanisms

#### Cluster-Wide Coordination
1. Each cluster creates/updates its `CardanoForgeCluster` CRD
2. All forge managers watch all cluster CRDs in the namespace
3. Priority calculation: `effective_priority = base_priority + health_penalty`
4. Only the lowest `effective_priority` (highest priority) healthy cluster forges
5. Within that cluster, local Kubernetes Lease election determines which pod

#### Health Check Integration
- Optional HTTP endpoint monitoring (GET request)
- Configurable interval, timeout, failure threshold
- Consecutive failures increase effective priority (demote cluster)
- Health recovery automatically restores original priority
- Manual override support for maintenance windows

#### Forge State Values
- `Enabled`: Always forge (override all conditions)
- `Disabled`: Never forge (maintenance/emergency)
- `Priority-based`: Follow priority and health logic (default)

#### Credential Lifecycle
1. **Startup Phase**: Provision credentials regardless of leadership (prevents restart loops)
2. **Normal Operation**: Only elected leader maintains credentials
3. **Credential Distribution**: Copy from `/secrets/*` to `/ipc/*` or `/opt/cardano/secrets/*`
4. **File Permissions**: Set to 0600 (owner read/write only)
5. **Cleanup**: Remove credentials from non-leader nodes
6. **Signal**: SIGHUP to cardano-node PID for reload

#### Process Discovery and Signaling
- Uses `psutil` to find cardano-node process by name or cmdline
- Falls back to socket-based detection if process not visible (multi-container pods)
- Sends SIGHUP only after node startup phase completes
- Tracks signal delivery with metrics

### Environment Variables

#### Core Configuration
- `NAMESPACE`, `POD_NAME`: Auto-injected via Kubernetes downward API
- `NODE_SOCKET`: Path to cardano-node socket (default: `/ipc/node.socket`)
- `LEASE_NAME`: Coordination lease name (auto-generated in multi-tenant mode)
- `LEASE_DURATION`: Lease hold duration in seconds (default: `15`)
- `SLEEP_INTERVAL`: Main loop interval in seconds (default: `5`)
- `METRICS_PORT`: Prometheus metrics port (default: `8000`)

#### Credential Paths
- `SOURCE_KES_KEY`, `SOURCE_VRF_KEY`, `SOURCE_OP_CERT`: Source paths in secret volume
- `TARGET_KES_KEY`, `TARGET_VRF_KEY`, `TARGET_OP_CERT`: Target paths for cardano-node

#### Multi-Tenant Configuration
- `CARDANO_NETWORK`: Network name (required for multi-tenant)
- `NETWORK_MAGIC`: Network magic number (validated for known networks)
- `POOL_ID`: Unique pool identifier (required for multi-tenant)
- `POOL_ID_HEX`, `POOL_NAME`, `POOL_TICKER`: Optional metadata
- `APPLICATION_TYPE`: Application type (default: `block-producer`)

#### Cluster Management
- `ENABLE_CLUSTER_MANAGEMENT`: Enable cross-cluster coordination (default: `false`)
- `CLUSTER_REGION`: Geographic region identifier (e.g., `us-east-1`)
- `CLUSTER_PRIORITY`: Base priority, 1=highest (default: `100`)
- `CLUSTER_ENVIRONMENT`: Environment classification (default: `production`)
- `HEALTH_CHECK_ENDPOINT`: Optional HTTP health check URL
- `HEALTH_CHECK_INTERVAL`: Health check interval in seconds (default: `30`)

### Prometheus Metrics

#### Local Metrics (forgemanager.py)
- `cardano_forging_enabled{pod,network,pool_id,application}`: Whether pod is forging (0 or 1)
- `cardano_leader_status{pod,network,pool_id,application}`: Whether pod is elected leader (0 or 1)
- `cardano_leadership_changes_total`: Total leadership transitions
- `cardano_sighup_signals_total{reason}`: SIGHUP signals sent to cardano-node
- `cardano_credential_operations_total{operation,file}`: Credential file operations

#### Cluster-Wide Metrics (cluster_manager.py)
- `cardano_cluster_forge_enabled{cluster,region,network,pool_id}`: Whether cluster is forging
- `cardano_cluster_forge_priority{cluster,region,network,pool_id}`: Effective priority
- `cardano_cluster_health_check_success{cluster}`: Health check success status
- `cardano_cluster_health_check_consecutive_failures{cluster}`: Consecutive failures

### Testing Architecture

#### Unit Tests (`tests/`)
- `test_forgemanager.py`: Core forge manager logic, lease management, credential operations
- `test_cluster_management.py`: Cluster coordination, priority logic, health checks, multi-tenant isolation
- `test_cnode_socket_pid.py`: Process discovery and socket monitoring

#### Test Fixtures and Mocking
- Mock Kubernetes API client responses (leases, CRDs)
- Mock file system operations for credential management
- Mock psutil for process discovery
- Mock HTTP requests for health checks
- Isolated test namespaces for multi-tenant scenarios

#### CI/CD Pipeline (`.github/workflows/build.yml`)
1. **Test**: Syntax check, flake8 linting
2. **Build**: Multi-arch container build (linux/amd64, linux/arm64) with Docker Buildx
3. **Security**: Trivy vulnerability scanning, SARIF upload to GitHub Security
4. **Release**: GitHub release creation for version tags
5. **SBOM**: Software Bill of Materials generation

### Security Model

- **Non-root**: Runs as UID 10001 with dropped capabilities
- **RBAC**: Minimal permissions (leases + CRDs only)
- **Secrets**: Read-only mounts with 0600 file permissions on copied credentials
- **Network**: No external network required (except optional health checks)
- **Audit**: All secret operations logged (without content)
- **Multi-Tenant**: Namespace-scoped leases and CRDs prevent cross-pool interference

## Common Workflows

### Adding New Features
1. Write tests first in `tests/test_*.py`
2. Implement feature in `src/forgemanager.py` or `src/cluster_manager.py`
3. Run `make check` for linting and formatting
4. Run `make test-coverage` to ensure coverage >= 25%
5. Update relevant documentation in `docs/`
6. Test locally with mocked Kubernetes API

### Debugging Issues
```bash
# Check pod logs
kubectl logs -f -l app=cardano-producer -c forge-manager -n cardano-mainnet

# Check current leader
kubectl get cardanoleader cardano-leader -n cardano-mainnet -o yaml

# Check cluster coordination status
kubectl get cardanoforgeclusters -o wide

# View metrics
kubectl port-forward svc/cardano-producer 8000:8000 -n cardano-mainnet
curl localhost:8000/metrics | grep cardano_

# Check lease status
kubectl get leases -n cardano-mainnet
```

### Manual Failover
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
