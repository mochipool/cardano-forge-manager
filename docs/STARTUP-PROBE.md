# Startup Probe Implementation for Cardano Forge Manager

## Overview

This document explains the startup synchronization mechanism implemented to ensure the cardano-node container starts only after the Cardano Forge Manager has successfully provisioned the required credentials (KES key, VRF key, and operational certificate).

## Problem Statement

The cardano-node requires specific credential files to be present at startup:
- `/opt/cardano/secrets/kes.skey` (KES signing key)
- `/opt/cardano/secrets/vrf.skey` (VRF signing key) 
- `/opt/cardano/secrets/node.cert` (Operational certificate)

Without these files, the cardano-node container will crash and restart continuously, creating a restart loop that prevents the pod from becoming ready.

## Solution Architecture

### Native Sidecar Pattern with Startup Probes

We use Kubernetes native sidecars (available in K8s 1.29+) with startup probes to ensure proper initialization order:

1. **Init Containers** run first (setup directories, download genesis files)
2. **Sidecar Containers** (forge manager) start and must pass their startup probes
3. **Main Containers** (cardano-node) start only after all sidecar startup probes succeed

### Components

#### 1. Forge Manager HTTP Server

The forge manager runs an HTTP server on port 8000 with multiple endpoints:

- `/startup-status` - Returns startup credential status (for startup probe)
- `/metrics` - Prometheus metrics (existing functionality)  
- `/health` - Simple health check

#### 2. Startup Status Endpoint (`/startup-status`)

**Ready State (HTTP 200):**
```json
{
  \"status\": \"ready\",
  \"message\": \"Startup credentials provisioned successfully\",
  \"credentials_provisioned\": true,
  \"timestamp\": \"2025-10-13T01:15:00Z\"
}
```

**Not Ready State (HTTP 503):**
```json
{
  \"status\": \"not_ready\",
  \"message\": \"Startup credentials not yet provisioned\",
  \"credentials_provisioned\": false,
  \"timestamp\": \"2025-10-13T01:15:00Z\"
}
```

#### 3. Startup Readiness Logic

The endpoint returns HTTP 200 (ready) when:
1. The `startup_credentials_provisioned` flag is `True`, OR
2. All required credential files exist and are non-empty:
   - `/opt/cardano/secrets/kes.skey`
   - `/opt/cardano/secrets/vrf.skey`
   - `/opt/cardano/secrets/node.cert`

#### 4. Startup Probe Configuration

The forge manager sidecar has a startup probe configured:

```yaml
startupProbe:
  httpGet:
    path: /startup-status
    port: 8000
  initialDelaySeconds: 5    # Start checking quickly
  periodSeconds: 3          # Check every 3 seconds
  timeoutSeconds: 2         # 2 second timeout
  failureThreshold: 60      # Allow up to 3 minutes (60 * 3s = 180s)
  successThreshold: 1       # Only need one success
```

## Configuration

### Enabling Startup Probes

Startup probes are enabled by default when the forge manager is enabled:

```yaml
# values.yaml
healthChecks:
  forgeManager:
    startupProbe:
      enabled: true  # Enabled by default
      httpGet:
        path: /startup-status
        port: 8000
      initialDelaySeconds: 5
      periodSeconds: 3
      timeoutSeconds: 2
      failureThreshold: 60
      successThreshold: 1
```

### Customizing Startup Probe Timing

You can adjust the timing parameters based on your environment:

```yaml
healthChecks:
  forgeManager:
    startupProbe:
      initialDelaySeconds: 10   # Wait 10s before first check
      periodSeconds: 5          # Check every 5 seconds  
      failureThreshold: 36      # Allow 3 minutes (36 * 5s = 180s)
```

### Disabling Startup Probes

If you need to disable startup probes (not recommended):

```yaml
healthChecks:
  forgeManager:
    startupProbe:
      enabled: false
```

## Benefits

1. **Eliminates Restart Loops**: cardano-node won't start until credentials are ready
2. **Faster Startup**: No wasted time on failed container starts
3. **Clear Status Visibility**: Easy to monitor startup progress via HTTP endpoint
4. **Configurable Timeouts**: Adjustable for different network/storage conditions
5. **Backward Compatible**: Works alongside existing health checks

## Monitoring and Troubleshooting

### Check Startup Status

You can manually check the startup status:

```bash
# Port forward to forge manager
kubectl port-forward pod/cardano-node-0 8000:8000

# Check startup status
curl http://localhost:8000/startup-status

# Check other endpoints
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

### View Startup Probe Events

```bash
# Check pod events for startup probe status
kubectl describe pod cardano-node-0

# Check container status
kubectl get pod cardano-node-0 -o jsonpath='{.status.containerStatuses[?(@.name==\"cardano-forge-manager\")].ready}'
```

### Common Issues

**Startup probe timeout:**
- Increase `failureThreshold` or `periodSeconds`
- Check forge manager logs: `kubectl logs cardano-node-0 -c cardano-forge-manager`
- Verify secret volume is mounted correctly

**Credentials not provisioned:**
- Check that the secret exists: `kubectl get secret cardano-secrets`
- Verify source file paths in forge manager configuration
- Check file permissions on source files

**HTTP endpoint not responding:**
- Verify forge manager container is running
- Check that port 8000 is not blocked
- Review forge manager startup logs

## Testing

Use the provided test script to verify endpoint functionality:

```bash
# Test locally (if running forge manager locally)
python3 test-startup-endpoint.py localhost 8000

# Test in cluster via port-forward
kubectl port-forward pod/cardano-node-0 8000:8000
python3 test-startup-endpoint.py localhost 8000
```

## Implementation Details

### Code Changes

1. **HTTP Server Enhancement** (`forgemanager.py`):
   - Added custom HTTP handler with multiple endpoints
   - Implemented startup status checking logic
   - Added health endpoint for other probes

2. **Helm Chart Updates** (`statefulset.yaml`):
   - Added startup probe configuration to forge manager container
   - Added readiness and liveness probe support

3. **Configuration** (`values.yaml`):
   - Added `healthChecks.forgeManager` section
   - Configurable probe parameters

### Native Sidecar Requirements

- Kubernetes 1.29+ for native sidecar support
- `restartPolicy: Always` on sidecar containers
- Startup probes prevent main container startup until sidecars are ready

## References

- [Kubernetes Startup Probes](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#startup-probes)
- [Kubernetes Native Sidecars](https://kubernetes.io/docs/concepts/workloads/pods/init-containers/#sidecar-containers)
- [Cardano Forge Manager Documentation](./WARP.md)