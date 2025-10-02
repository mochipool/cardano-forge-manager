# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Cardano Forge Manager is a Kubernetes sidecar container that manages Cardano block producer leadership election and secret distribution. It implements a leader election mechanism using Kubernetes coordination leases and manages the secure distribution of forging keys (KES, VRF, and operational certificates) to the active leader node.

## Development Commands

### Container Management
```bash
# Build container image (defaults to linux/amd64, uses podman)
make build

# Build with custom platform and tag
make build PLATFORM=linux/arm64 TAG=my-custom-tag

# Build with Docker instead of Podman
make build IMAGE_TOOL=docker

# Build and push image
make push

# Clean up container images
make clean

# Use sudo for container operations (if needed for Podman/QEMU)
make build USE_SUDO=true
```

### Development and Testing
```bash
# Syntax check Python code
python -m py_compile src/forgemanager.py

# Install dependencies
pip install -r requirements.txt

# Run locally (requires proper Kubernetes context and RBAC)
python src/forgemanager.py

# Deploy test resources to Kubernetes
kubectl apply -f dummy.yaml
```

## Architecture

### Core Components

**Main Module**: `src/forgemanager.py`
- Single-file Python application that runs as a Kubernetes sidecar
- Implements leader election using Kubernetes coordination leases
- Manages secret distribution for Cardano block producer nodes
- Updates Custom Resource status to reflect current leadership

### Key Mechanisms

**Leader Election**:
- Uses Kubernetes coordination.k8s.io/v1 Lease resources for distributed locking
- Implements lease renewal with configurable duration and intervals
- Handles lease expiration and acquisition race conditions
- Updates custom CardanoLeader CRD with current leader status

**Secret Management**:
- Copies forging secrets (KES, VRF, operational certificates) from mounted secret volumes to target locations
- Provisions startup credentials for node bootstrap regardless of leadership (prevents restart loops)
- Only the elected leader maintains credentials during normal operation
- Automatically removes secrets from non-leader nodes after startup
- Sets proper file permissions (owner read/write only)

**Process Signaling**:
- Discovers cardano-node process PID using psutil
- Sends SIGHUP signals to cardano-node for credential reload
- Tracks signal delivery with comprehensive error handling
- Avoids signaling during node startup phase

**Socket Monitoring**:
- Waits for Cardano node socket before proceeding with operations
- Detects node startup vs running phases
- Configurable timeout and check intervals
- Can be disabled for testing scenarios

**Startup Phase Handling**:
- Detects when cardano-node is in startup/restart phase
- Provisions credentials before node startup to prevent bootstrap failures
- Transitions to normal leader election after node stabilization
- Supports START_AS_NON_PRODUCING environment variable

### Environment Configuration

Critical environment variables (defined in Dockerfile with defaults):
- `NAMESPACE`: Kubernetes namespace for operations
- `POD_NAME`: Current pod identifier for leader election
- `LEASE_NAME`: Name of the coordination lease resource
- `NODE_SOCKET`: Path to Cardano node socket file
- `CRD_*`: Custom Resource Definition configuration for status updates
- `SOURCE_*_KEY`/`TARGET_*_KEY`: Full paths to credential files (KES, VRF, OpCert)
- `SLEEP_INTERVAL`: Main loop iteration interval
- `START_AS_NON_PRODUCING`: Controls startup credential provisioning
- `METRICS_PORT`: Prometheus metrics server port

### Kubernetes Resources

The `dummy.yaml` file provides a complete test deployment including:
- RBAC configuration for lease and CRD management
- CardanoLeader custom resource for status tracking
- Multi-replica deployment for leader election testing
- Security contexts and resource constraints
- Service for metrics exposure

## Key Implementation Details

### Lease Management
- Implements exponential backoff and conflict resolution for concurrent lease attempts
- Parses Kubernetes timestamp formats and handles timezone conversion
- Automatically creates leases if they don't exist
- Graceful handling of API conflicts (409 responses)

### Error Handling
- Comprehensive logging at INFO level with structured messages
- Graceful degradation when secrets or sockets are unavailable
- Kubernetes API exception handling with appropriate retries
- File system operation error recovery

### Security Considerations
- Runs as non-root user (UID 10001) with minimal privileges
- Drops all Linux capabilities in container security context
- Uses read-only secret mounts with proper file permissions
- Implements secure secret copying with restricted access modes

## Container Notes

- Based on Python 3.13-slim with minimal dependencies
- Exposes metrics port 8000 with full Prometheus metrics implementation
- Uses multi-stage build pattern for optimization
- Follows 12-factor app principles with environment-based configuration
- Includes psutil for process management and prometheus_client for metrics
- Entry point: `python -m src.sidecar` (note: actual file is forgemanager.py)
