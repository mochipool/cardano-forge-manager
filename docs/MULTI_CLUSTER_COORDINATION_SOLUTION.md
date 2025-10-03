# Multi-Cluster Coordination Solution - Independent Kubernetes Clusters

## Problem Statement

The previous solution (`CLUSTER_PRIORITY_SOLUTION.md`) assumed all clusters are deployed in the same Kubernetes cluster (sharing the same API server). In reality, SPOs run **multiple independent Kubernetes clusters** across:

- Different geographic regions (US-East, EU-West, Asia-Pacific)
- Different cloud providers (AWS, GCP, Azure, on-premises)
- Different availability zones for fault isolation
- Air-gapped or network-isolated environments

**These independent clusters cannot directly query each other's CRDs** because they don't share an API server.

## Real-World Multi-Cluster Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           SPO Infrastructure                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌────────────────────┐  ┌────────────────────┐  ┌──────────────┐  │
│  │  K8s Cluster       │  │  K8s Cluster       │  │  K8s Cluster │  │
│  │  (US-East-1)       │  │  (EU-West-1)       │  │  (AP-South)  │  │
│  │                    │  │                    │  │              │  │
│  │  - Own API Server  │  │  - Own API Server  │  │  - Own API   │  │
│  │  - Own etcd        │  │  - Own etcd        │  │  - Own etcd  │  │
│  │  - Own CRDs        │  │  - Own CRDs        │  │  - Own CRDs  │  │
│  │  - Priority: 1     │  │  - Priority: 2     │  │  - Priority:3│  │
│  └────────────────────┘  └────────────────────┘  └──────────────┘  │
│           ↓                       ↓                      ↓           │
│           └───────────────────────┴──────────────────────┘           │
│                                   ↓                                  │
│                     ┌──────────────────────────┐                     │
│                     │  Shared Coordination     │                     │
│                     │  Mechanism (Required)    │                     │
│                     └──────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Solution Options Analysis

### Option 1: Cluster Federation (Rejected)

**Description**: Use Kubernetes Federation (KubeFed) or multi-cluster tooling to sync CRDs across clusters.

**Pros**:
- Kubernetes-native approach
- Transparent CRD replication

**Cons**:
- ❌ Complex setup and operational overhead
- ❌ Requires network connectivity between clusters
- ❌ Not suitable for air-gapped environments
- ❌ Single point of failure (federation control plane)
- ❌ Overkill for simple priority coordination

**Decision**: **Rejected** - Too complex for the simple coordination problem we're solving.

---

### Option 2: Centralized Coordination Service (Rejected)

**Description**: Deploy a centralized API service that all clusters report to and query for coordination decisions.

**Pros**:
- Simple query model
- Real-time coordination

**Cons**:
- ❌ Single point of failure
- ❌ Requires running and operating additional infrastructure
- ❌ Network dependency (clusters must reach coordination service)
- ❌ Latency issues for global deployments
- ❌ Security concerns (exposing coordination endpoints)

**Decision**: **Rejected** - Violates principle of decentralized, resilient architecture.

---

### Option 3: External State Store (Redis, etcd, Consul) (Rejected)

**Description**: Use a globally-accessible key-value store for cluster state sharing.

**Pros**:
- Fast reads/writes
- Built-in leader election in some (e.g., etcd, Consul)

**Cons**:
- ❌ Requires operating another distributed system
- ❌ Network connectivity requirements
- ❌ Security/access control complexity
- ❌ Additional operational burden

**Decision**: **Rejected** - Adds operational complexity without clear benefits.

---

### Option 4: Cloud Provider Native Services (Partial Solution)

**Description**: Use cloud provider services like AWS DynamoDB, Azure Cosmos DB, or GCP Firestore for state sharing.

**Pros**:
- Managed service (less operational overhead)
- Global replication available
- Good availability guarantees

**Cons**:
- ❌ Vendor lock-in
- ❌ Doesn't work for multi-cloud or on-premises
- ❌ Cost implications
- ⚠️ Still requires network connectivity

**Decision**: **Viable for cloud-only deployments** - but not a universal solution.

---

### Option 5: HTTP Health Check + Status Polling (RECOMMENDED)

**Description**: Each cluster exposes its status via an HTTP endpoint. Clusters poll each other's health/status endpoints to discover peer state.

**Pros**:
- ✅ Simple HTTP - works across any network
- ✅ No shared infrastructure required
- ✅ Works with air-gapped clusters (one-way polling possible)
- ✅ Fail-safe by default (unreachable = unhealthy)
- ✅ Already have health check infrastructure in place
- ✅ Can use existing monitoring/observability tools

**Cons**:
- ⚠️ Eventual consistency (polling interval delay)
- ⚠️ Requires manual configuration of peer endpoints
- ⚠️ Security consideration (endpoint exposure)

**Decision**: **RECOMMENDED** - Best balance of simplicity, reliability, and operational practicality.

---

### Option 6: Git-Based Configuration (Manual Coordination)

**Description**: SPO manually updates priorities in Git, applies via GitOps (ArgoCD/FluxCD).

**Pros**:
- ✅ Extremely simple
- ✅ Full audit trail (Git history)
- ✅ Works everywhere (no runtime dependencies)
- ✅ Declarative and version controlled

**Cons**:
- ⚠️ Manual intervention required for failover
- ⚠️ Slower transition times (human in the loop)
- ⚠️ No automated health-based failover

**Decision**: **FALLBACK/HYBRID** - Use as baseline with Option 5 for automated health failover.

---

## Recommended Solution: HTTP Status Polling with Health Check Integration

### Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Cluster: US-East-1 (Priority 1)                    │
├──────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  CardanoForgeCluster CRD (Local):                                     │
│  ├─ spec.priority: 1                                                  │
│  ├─ spec.forgeState: Priority-based                                   │
│  └─ spec.peerClusters:                                                │
│      ├─ name: eu-west-1                                               │
│      │  url: https://cardano-eu.example.com/cluster-status            │
│      │  priority: 2                                                   │
│      └─ name: ap-south-1                                              │
│         url: https://cardano-ap.example.com/cluster-status            │
│         priority: 3                                                   │
│                                                                        │
│  Forge Manager Sidecar:                                               │
│  ├─ Exposes: /cluster-status (own status)                             │
│  ├─ Polls: peer URLs every 15-30 seconds                              │
│  ├─ Evaluates: own priority vs discovered peer states                 │
│  └─ Decides: Allow/Deny forging based on priority comparison          │
│                                                                        │
└──────────────────────────────────────────────────────────────────────┘
                              ↓ HTTP Polling ↓
┌──────────────────────────────────────────────────────────────────────┐
│                    Cluster: EU-West-1 (Priority 2)                    │
├──────────────────────────────────────────────────────────────────────┤
│  (Same structure, polls US-East-1 and AP-South-1)                     │
└──────────────────────────────────────────────────────────────────────┘
                              ↓ HTTP Polling ↓
┌──────────────────────────────────────────────────────────────────────┐
│                    Cluster: AP-South-1 (Priority 3)                   │
├──────────────────────────────────────────────────────────────────────┤
│  (Same structure, polls US-East-1 and EU-West-1)                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Decentralized Decision Making**: Each cluster independently evaluates priority
2. **Pull-Based Discovery**: Clusters poll configured peer endpoints
3. **Fail-Safe Defaults**: Unreachable peers treated as unhealthy (excluded from comparison)
4. **Stateless Protocol**: Each status request is independent
5. **Security First**: mTLS, authentication tokens, or VPN tunnels recommended
6. **Configuration as Code**: Peer URLs managed via CRD spec (GitOps-friendly)

## Implementation Design

### 1. Enhanced CRD Schema

Add peer cluster configuration to `CardanoForgeCluster` CRD:

```yaml
apiVersion: cardano.io/v1
kind: CardanoForgeCluster
metadata:
  name: mainnet-pool1abcd-us-east-1
  labels:
    cardano.io/network: mainnet
    cardano.io/pool-id: pool1abcd...
    cardano.io/region: us-east-1
spec:
  forgeState: Priority-based
  priority: 1
  
  # NEW: Peer cluster definitions for cross-cluster coordination
  peerClusters:
    - name: eu-west-1
      url: https://cardano-bp-eu.example.com/cluster-status
      priority: 2
      enabled: true
      timeout: 5s
      
    - name: ap-south-1
      url: https://cardano-bp-ap.example.com/cluster-status
      priority: 3
      enabled: true
      timeout: 5s
  
  # Polling configuration
  peerPolling:
    enabled: true
    interval: 15s
    timeout: 5s
    retries: 2
    
  # Authentication for peer polling (optional)
  peerAuth:
    type: bearer  # or: mtls, basic, none
    secretRef:
      name: peer-cluster-auth
      key: token

status:
  # ... existing fields ...
  
  # NEW: Peer cluster status tracking
  peerStatus:
    - name: eu-west-1
      priority: 2
      reachable: true
      healthy: true
      lastPollTime: "2025-10-03T19:30:00Z"
      lastPollDuration: "120ms"
      effectiveState: "Priority-based"
      activeLeader: "cardano-bp-eu-0"
      forgingEnabled: false
      
    - name: ap-south-1
      priority: 3
      reachable: false  # Network unreachable
      healthy: false
      lastPollTime: "2025-10-03T19:30:00Z"
      lastPollError: "connection timeout"
      effectiveState: "unknown"
```

### 2. Cluster Status HTTP Endpoint

Each cluster exposes its current state via HTTP endpoint:

**Endpoint**: `GET /cluster-status`

**Response Format** (JSON):
```json
{
  "cluster": {
    "name": "mainnet-pool1abcd-us-east-1",
    "network": "mainnet",
    "poolId": "pool1abcd...",
    "region": "us-east-1",
    "priority": 1,
    "createdAt": "2025-09-01T10:00:00Z"
  },
  "status": {
    "forgeState": "Priority-based",
    "effectiveState": "Priority-based",
    "effectivePriority": 1,
    "forgingEnabled": true,
    "activeLeader": "cardano-bp-0",
    "lastTransitionTime": "2025-10-03T19:25:00Z"
  },
  "health": {
    "healthy": true,
    "consecutiveFailures": 0,
    "lastHealthCheck": "2025-10-03T19:29:45Z",
    "checks": {
      "nodeSync": "ok",
      "blockHeight": 12345678,
      "peerConnections": 15
    }
  },
  "timestamp": "2025-10-03T19:30:00Z",
  "version": "1.0.0"
}
```

**Authentication**: 
- Support Bearer token authentication
- Support mTLS for production
- Support IP allowlisting

**Endpoint Implementation** (add to existing metrics server):

```python
from flask import Flask, jsonify, request
from datetime import datetime, timezone

app = Flask(__name__)

@app.route('/cluster-status', methods=['GET'])
def cluster_status():
    """Expose cluster status for peer polling."""
    # Authenticate request
    if not authenticate_peer_request(request):
        return jsonify({"error": "unauthorized"}), 401
    
    cluster_manager = get_cluster_manager()  # Singleton instance
    
    if not cluster_manager.enabled:
        return jsonify({"error": "cluster management disabled"}), 503
    
    crd = cluster_manager._current_cluster_crd
    if not crd:
        return jsonify({"error": "cluster CRD not initialized"}), 503
    
    spec = crd.get("spec", {})
    status = crd.get("status", {})
    metadata = crd.get("metadata", {})
    
    response = {
        "cluster": {
            "name": cluster_manager.cluster_id,
            "network": cluster_manager.network,
            "poolId": cluster_manager.pool_id,
            "region": cluster_manager.region,
            "priority": spec.get("priority", cluster_manager.priority),
            "createdAt": metadata.get("creationTimestamp", ""),
        },
        "status": {
            "forgeState": spec.get("forgeState", "Priority-based"),
            "effectiveState": status.get("effectiveState", "unknown"),
            "effectivePriority": status.get("effectivePriority", 100),
            "forgingEnabled": cluster_manager._cluster_forge_enabled,
            "activeLeader": status.get("activeLeader", ""),
            "lastTransitionTime": status.get("lastTransition", ""),
        },
        "health": {
            "healthy": cluster_manager._consecutive_health_failures == 0,
            "consecutiveFailures": cluster_manager._consecutive_health_failures,
            "lastHealthCheck": (
                cluster_manager._last_health_check.isoformat()
                if cluster_manager._last_health_check
                else None
            ),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }
    
    return jsonify(response), 200


def authenticate_peer_request(request):
    """Authenticate peer cluster request."""
    auth_type = os.environ.get("PEER_AUTH_TYPE", "none")
    
    if auth_type == "none":
        return True
    
    if auth_type == "bearer":
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        
        token = auth_header[7:]  # Strip "Bearer "
        expected_token = os.environ.get("PEER_AUTH_TOKEN", "")
        return token == expected_token
    
    # Add mTLS validation here if needed
    return False
```

### 3. Peer Cluster Polling Logic

Add peer polling to `ClusterForgeManager`:

```python
def _poll_peer_clusters(self) -> List[Dict[str, Any]]:
    """
    Poll configured peer cluster status endpoints.
    
    Returns:
        List of peer cluster status responses.
    """
    if not self._current_cluster_crd:
        return []
    
    spec = self._current_cluster_crd.get("spec", {})
    peer_configs = spec.get("peerClusters", [])
    polling_config = spec.get("peerPolling", {})
    
    if not polling_config.get("enabled", True):
        logger.debug("Peer polling disabled in CRD spec")
        return []
    
    timeout = self._parse_duration(polling_config.get("timeout", "5s"))
    retries = polling_config.get("retries", 2)
    
    peer_statuses = []
    
    for peer_config in peer_configs:
        if not peer_config.get("enabled", True):
            continue
        
        peer_name = peer_config.get("name", "unknown")
        peer_url = peer_config.get("url", "")
        
        if not peer_url:
            logger.warning(f"Peer {peer_name} has no URL configured, skipping")
            continue
        
        peer_status = self._poll_single_peer(
            peer_name=peer_name,
            peer_url=peer_url,
            timeout=timeout,
            retries=retries,
        )
        
        if peer_status:
            peer_statuses.append(peer_status)
    
    return peer_statuses


def _poll_single_peer(
    self, 
    peer_name: str, 
    peer_url: str, 
    timeout: int, 
    retries: int
) -> Optional[Dict[str, Any]]:
    """
    Poll a single peer cluster status endpoint.
    
    Returns:
        Peer status dict if successful, None if unreachable.
    """
    headers = {"User-Agent": "cardano-forge-manager/1.0"}
    
    # Add authentication if configured
    auth_type = os.environ.get("PEER_AUTH_TYPE", "none")
    if auth_type == "bearer":
        token = os.environ.get("PEER_AUTH_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    
    for attempt in range(retries + 1):
        try:
            start_time = time.time()
            response = requests.get(
                peer_url,
                headers=headers,
                timeout=timeout,
                verify=True,  # Verify TLS certificates
            )
            duration_ms = int((time.time() - start_time) * 1000)
            
            if response.status_code == 200:
                peer_data = response.json()
                
                # Validate response structure
                if not self._validate_peer_response(peer_data):
                    logger.warning(f"Invalid response from peer {peer_name}")
                    continue
                
                logger.debug(
                    f"Successfully polled peer {peer_name} in {duration_ms}ms"
                )
                
                # Return normalized peer status
                return {
                    "name": peer_name,
                    "url": peer_url,
                    "reachable": True,
                    "data": peer_data,
                    "pollTime": datetime.now(timezone.utc).isoformat(),
                    "pollDuration": f"{duration_ms}ms",
                }
            else:
                logger.warning(
                    f"Peer {peer_name} returned status {response.status_code}"
                )
                
        except requests.RequestException as e:
            if attempt < retries:
                logger.debug(
                    f"Peer {peer_name} poll failed (attempt {attempt+1}/{retries+1}): {e}"
                )
                time.sleep(1)  # Brief backoff before retry
            else:
                logger.warning(
                    f"Peer {peer_name} unreachable after {retries+1} attempts: {e}"
                )
        
        except Exception as e:
            logger.error(f"Unexpected error polling peer {peer_name}: {e}")
            break
    
    # All retries failed - peer unreachable
    return {
        "name": peer_name,
        "url": peer_url,
        "reachable": False,
        "pollTime": datetime.now(timezone.utc).isoformat(),
        "error": "connection failed after retries",
    }


def _validate_peer_response(self, response: Dict[str, Any]) -> bool:
    """Validate peer status response structure."""
    required_fields = ["cluster", "status", "health", "timestamp"]
    return all(field in response for field in required_fields)


def _parse_duration(self, duration_str: str) -> int:
    """Parse duration string like '5s' to seconds."""
    import re
    match = re.match(r"(\d+)s", duration_str)
    if match:
        return int(match.group(1))
    return 5  # Default
```

### 4. Updated Priority Comparison Logic

Modify `should_allow_forging()` to use polled peer data:

```python
def should_allow_forging(self) -> Tuple[bool, str]:
    """
    Determine if forging should be enabled based on cluster-wide priority.
    
    Uses HTTP polling of peer clusters for cross-cluster coordination.
    """
    if not self.enabled:
        return True, "cluster_management_disabled"

    if not self._current_cluster_crd:
        return True, "no_cluster_crd"

    try:
        spec = self._current_cluster_crd.get("spec", {})
        forge_state = spec.get("forgeState", "Priority-based")
        
        effective_state, effective_priority, _, _ = \
            self._calculate_effective_state_and_priority(
                forge_state, spec.get("priority", self.priority)
            )

        if effective_state == "Disabled":
            return False, "cluster_forge_disabled"

        if effective_state == "Enabled":
            return True, "cluster_forge_enabled"

        # Priority-based decision making
        if effective_state == "Priority-based":
            # Check if peer polling is configured
            peer_configs = spec.get("peerClusters", [])
            
            if not peer_configs:
                # No peers configured - single cluster mode
                logger.debug("No peer clusters configured, allowing forging")
                return True, f"single_cluster_priority_{effective_priority}"
            
            # Poll peer cluster statuses
            peer_statuses = self._poll_peer_clusters()
            
            # Filter to reachable, healthy, enabled peers
            eligible_peers = []
            
            for peer_status in peer_statuses:
                if not peer_status.get("reachable", False):
                    logger.debug(
                        f"Peer {peer_status['name']} unreachable, excluding from priority comparison"
                    )
                    continue
                
                peer_data = peer_status.get("data", {})
                peer_health = peer_data.get("health", {})
                peer_state = peer_data.get("status", {})
                
                # Check if peer is healthy and enabled
                if not peer_health.get("healthy", False):
                    logger.debug(
                        f"Peer {peer_status['name']} unhealthy, excluding"
                    )
                    continue
                
                if peer_state.get("effectiveState") == "Disabled":
                    logger.debug(
                        f"Peer {peer_status['name']} disabled, excluding"
                    )
                    continue
                
                eligible_peers.append(peer_status)
            
            if not eligible_peers:
                # No eligible peers - we can forge
                logger.info(
                    f"No eligible peer clusters (polled {len(peer_statuses)}), allowing forging"
                )
                return True, f"no_eligible_peers_priority_{effective_priority}"
            
            # Compare priorities
            our_priority = effective_priority
            our_created_at = self._current_cluster_crd.get("metadata", {}).get(
                "creationTimestamp", ""
            )
            
            for peer_status in eligible_peers:
                peer_data = peer_status.get("data", {})
                peer_name = peer_status.get("name")
                peer_priority = peer_data.get("status", {}).get(
                    "effectivePriority", 100
                )
                peer_created_at = peer_data.get("cluster", {}).get(
                    "createdAt", ""
                )
                
                if peer_priority < our_priority:
                    # Peer has higher priority (lower number)
                    logger.info(
                        f"Denying forging: peer {peer_name} has higher priority "
                        f"({peer_priority} < {our_priority})"
                    )
                    return False, f"lower_priority_{our_priority}_vs_{peer_name}"
                
                elif peer_priority == our_priority:
                    # Priority tie - use creation timestamp
                    if peer_created_at < our_created_at:
                        logger.info(
                            f"Denying forging: lost timestamp tiebreak to peer {peer_name}"
                        )
                        return False, f"tiebreak_lost_to_{peer_name}"
            
            # We have highest priority
            logger.info(
                f"Allowing forging: highest priority ({our_priority}) among "
                f"{len(eligible_peers)} eligible peer clusters"
            )
            return True, f"highest_priority_{our_priority}"

        return True, "default_allow"

    except Exception as e:
        logger.error(f"Error evaluating forging policy: {e}")
        # Fail-safe: if we can't determine priority, deny forging
        return False, "evaluation_error"
```

### 5. Periodic Peer Status Updates

Add background thread for peer polling and CRD status updates:

```python
def _peer_polling_loop(self):
    """Background thread for periodic peer status polling."""
    logger.info("Starting peer cluster polling loop")
    
    while not self._shutdown_event.is_set():
        try:
            if not self._current_cluster_crd:
                time.sleep(5)
                continue
            
            spec = self._current_cluster_crd.get("spec", {})
            polling_config = spec.get("peerPolling", {})
            
            if not polling_config.get("enabled", True):
                time.sleep(30)
                continue
            
            interval = self._parse_duration(polling_config.get("interval", "15s"))
            
            # Poll all peers
            peer_statuses = self._poll_peer_clusters()
            
            # Update CRD status with peer information
            if peer_statuses:
                self._update_peer_status_in_crd(peer_statuses)
            
            # Wait for next poll interval
            if self._shutdown_event.wait(interval):
                break
        
        except Exception as e:
            logger.error(f"Error in peer polling loop: {e}")
            time.sleep(5)
    
    logger.info("Peer cluster polling loop stopped")


def _update_peer_status_in_crd(self, peer_statuses: List[Dict[str, Any]]):
    """Update CRD status with latest peer polling results."""
    try:
        # Build peer status array for CRD
        peer_status_array = []
        
        for peer_status in peer_statuses:
            peer_name = peer_status.get("name")
            reachable = peer_status.get("reachable", False)
            
            status_entry = {
                "name": peer_name,
                "reachable": reachable,
                "lastPollTime": peer_status.get("pollTime"),
            }
            
            if reachable:
                peer_data = peer_status.get("data", {})
                status_entry.update({
                    "priority": peer_data.get("status", {}).get("effectivePriority"),
                    "healthy": peer_data.get("health", {}).get("healthy"),
                    "effectiveState": peer_data.get("status", {}).get("effectiveState"),
                    "activeLeader": peer_data.get("status", {}).get("activeLeader"),
                    "forgingEnabled": peer_data.get("status", {}).get("forgingEnabled"),
                    "lastPollDuration": peer_status.get("pollDuration"),
                })
            else:
                status_entry.update({
                    "healthy": False,
                    "lastPollError": peer_status.get("error"),
                })
            
            peer_status_array.append(status_entry)
        
        # Patch CRD status
        status_patch = {
            "status": {
                "peerStatus": peer_status_array,
            }
        }
        
        self.api.patch_namespaced_custom_object_status(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=self._namespace,
            plural=CRD_PLURAL,
            name=self.cluster_id,
            body=status_patch,
        )
        
        logger.debug(f"Updated peer status in CRD: {len(peer_status_array)} peers")
    
    except Exception as e:
        logger.warning(f"Failed to update peer status in CRD: {e}")
```

### 6. Start Peer Polling Thread

Update `ClusterForgeManager.start()`:

```python
def start(self):
    """Start cluster management threads if enabled."""
    if not self.enabled:
        return
    
    try:
        self._ensure_cluster_crd()
        
        # Start CRD watch thread (existing)
        self._watch_thread = threading.Thread(
            target=self._watch_cluster_crd,
            daemon=True,
            name="crd-watch"
        )
        self._watch_thread.start()
        
        # Start health check thread (existing, if configured)
        if HEALTH_CHECK_ENDPOINT:
            self._health_thread = threading.Thread(
                target=self._health_check_loop,
                daemon=True,
                name="health-check"
            )
            self._health_thread.start()
        
        # NEW: Start peer polling thread
        spec = self._current_cluster_crd.get("spec", {})
        if spec.get("peerClusters"):
            self._peer_thread = threading.Thread(
                target=self._peer_polling_loop,
                daemon=True,
                name="peer-polling"
            )
            self._peer_thread.start()
            logger.info(f"Started peer cluster polling thread")
    
    except Exception as e:
        logger.error(f"Failed to start cluster management: {e}")
        self.enabled = False
```

## Configuration Examples

### Example 1: Three-Region Setup (AWS)

```yaml
# us-east-1 cluster (Primary)
apiVersion: cardano.io/v1
kind: CardanoForgeCluster
metadata:
  name: mainnet-pool1abcd-us-east-1
spec:
  forgeState: Priority-based
  priority: 1
  peerClusters:
    - name: eu-west-1
      url: https://34.250.123.45:8000/cluster-status  # Public IP or domain
      priority: 2
      enabled: true
    - name: ap-south-1
      url: https://13.234.56.78:8000/cluster-status
      priority: 3
      enabled: true
  peerPolling:
    enabled: true
    interval: 15s
    timeout: 5s
  peerAuth:
    type: bearer
    secretRef:
      name: peer-auth-token
      key: token
```

### Example 2: Multi-Cloud Setup (AWS + GCP + Azure)

```yaml
# AWS us-east-1 (Priority 1)
apiVersion: cardano.io/v1
kind: CardanoForgeCluster
metadata:
  name: mainnet-pool1abcd-aws-us-east-1
spec:
  priority: 1
  peerClusters:
    - name: gcp-us-central1
      url: https://cardano-gcp.example.com/cluster-status
      priority: 2
    - name: azure-westeurope
      url: https://cardano-azure.example.com/cluster-status
      priority: 3
```

### Example 3: Air-Gapped Environment (One-Way Polling)

```yaml
# Public cloud cluster (can poll on-prem)
apiVersion: cardano.io/v1
kind: CardanoForgeCluster
metadata:
  name: mainnet-pool1abcd-cloud
spec:
  priority: 2  # Lower priority than on-prem
  peerClusters:
    - name: on-premises-dc
      url: https://cardano-onprem.internal.vpn/cluster-status  # Via VPN
      priority: 1  # On-prem is primary
      enabled: true
```

## Security Considerations

### 1. Authentication

**Bearer Token (Simple)**:
```bash
# Generate shared secret
openssl rand -base64 32 > peer-auth-token.txt

# Create Kubernetes secret in each cluster
kubectl create secret generic peer-auth-token \
  --from-file=token=peer-auth-token.txt
```

**mTLS (Production)**:
```yaml
spec:
  peerAuth:
    type: mtls
    tlsSecretRef:
      name: peer-cluster-mtls
      certKey: tls.crt
      keyKey: tls.key
      caKey: ca.crt
```

### 2. Network Security

- **Option A**: Expose endpoint via LoadBalancer with IP allowlisting
- **Option B**: Use Cloudflare Tunnel or similar secure ingress
- **Option C**: VPN/WireGuard tunnel between clusters
- **Option D**: Private peering (cloud provider native)

### 3. Rate Limiting

Implement rate limiting on status endpoint:
```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=lambda: request.remote_addr)

@app.route('/cluster-status')
@limiter.limit("30 per minute")  # Max 30 requests/min per IP
def cluster_status():
    # ... implementation ...
```

## Edge Cases and Failure Modes

### 1. Network Partition (Split-Brain Risk)

**Scenario**: Network failure prevents clusters from reaching each other.

**Behavior**:
- Each cluster thinks peers are unreachable
- Each cluster excludes unreachable peers from priority comparison
- **Multiple clusters might forge simultaneously**

**Mitigation**:
- Accept brief split-brain as trade-off (better than no forging)
- Alert on `sum(cardano_cluster_forge_enabled) > 1` (requires external monitoring)
- Consider manual intervention for extended partitions

### 2. Polling Lag / Stale Data

**Scenario**: Peer status changes but not detected until next poll cycle.

**Behavior**:
- Up to `interval` seconds delay (default 15s)
- Brief period where stale priority used

**Mitigation**:
- Acceptable delay (15s is reasonable)
- Lower interval if needed (trade-off: more network traffic)
- CRD status shows last poll time for debugging

### 3. Peer Endpoint Misconfiguration

**Scenario**: Wrong URL configured in peer list.

**Behavior**:
- Peer marked unreachable
- Excluded from priority comparison
- Logged as warning

**Mitigation**:
- Clear error logs
- CRD status shows connection errors
- Validate peer configuration in CI/CD

### 4. Clock Skew Between Clusters

**Scenario**: System clocks differ significantly between regions.

**Impact**: Minimal - timestamps only used for tiebreaking (rare).

**Mitigation**:
- Ensure NTP configured on all nodes
- Timestamp tiebreaker is tertiary (after priority and creation time)

### 5. Bootstrap Problem (All Clusters Start Simultaneously)

**Scenario**: All clusters start at once, all think they're alone.

**Behavior**:
- First poll cycle: each cluster thinks it's sole cluster
- Second poll cycle: peers discovered, priority comparison works
- Brief period of potential dual-forging

**Mitigation**:
- Add startup delay (random jitter 0-30s)
- First forging decision delayed until after initial peer poll

## Monitoring and Observability

### New Metrics

```python
# Peer cluster reachability
cardano_peer_cluster_reachable{peer="eu-west-1"} 1

# Peer poll latency
cardano_peer_poll_duration_seconds{peer="eu-west-1"} 0.120

# Peer poll errors
cardano_peer_poll_errors_total{peer="eu-west-1", error="timeout"} 0

# Priority comparison decisions
cardano_priority_decision{result="allow", reason="highest_priority"} 1
cardano_priority_decision{result="deny", reason="lower_priority"} 0
```

### Alerts

```yaml
# Peer unreachable for extended period
- alert: CardanoPeerClusterUnreachable
  expr: cardano_peer_cluster_reachable == 0
  for: 5m
  severity: warning
  annotations:
    summary: "Peer cluster {{ $labels.peer }} unreachable for 5+ minutes"

# Multiple clusters forging (split-brain detection)
# NOTE: Requires centralized monitoring
- alert: CardanoMultiClusterForging
  expr: sum(cardano_cluster_forge_enabled{network="mainnet", pool_id="pool1abcd"}) > 1
  for: 30s
  severity: critical

# Priority comparison errors
- alert: CardanoPriorityEvaluationErrors
  expr: rate(cardano_priority_decision{result="error"}[5m]) > 0
  for: 5m
  severity: warning
```

### Logging

```python
# Key log messages
logger.info(f"Polled {len(peer_statuses)} peers: {reachable_count} reachable")
logger.info(f"Priority decision: {decision} (reason: {reason})")
logger.warning(f"Peer {peer_name} unreachable: {error}")
logger.error(f"Failed to poll peers: {exception}")
```

## Operational Procedures

### Manual Failover (Primary to Secondary)

```bash
# Step 1: Update primary cluster to lower priority
kubectl --context=us-east-1 patch cardanoforgeCluster \
  mainnet-pool1abcd-us-east-1 \
  --type=merge -p '{"spec":{"priority":2}}'

# Step 2: Update secondary cluster to higher priority  
kubectl --context=eu-west-1 patch cardanoforgeCluster \
  mainnet-pool1abcd-eu-west-1 \
  --type=merge -p '{"spec":{"priority":1}}'

# Step 3: Verify transition (check logs/metrics in both clusters)
# US-East should show: "Denying forging: lower priority"
# EU-West should show: "Allowing forging: highest priority"
```

### Emergency Disable All Clusters

```bash
# Disable forging in all clusters
for context in us-east-1 eu-west-1 ap-south-1; do
  kubectl --context=$context patch cardanoforgeCluster \
    mainnet-pool1abcd-$context \
    --type=merge -p '{"spec":{"forgeState":"Disabled"}}'
done
```

### Add New Cluster to Existing Setup

```bash
# 1. Deploy new cluster with lowest priority
# 2. Update existing clusters to add new peer
kubectl patch cardanoforgeCluster mainnet-pool1abcd-us-east-1 \
  --type=json -p '[{
    "op": "add",
    "path": "/spec/peerClusters/-",
    "value": {
      "name": "new-region",
      "url": "https://new-region.example.com/cluster-status",
      "priority": 4,
      "enabled": true
    }
  }]'
```

## Migration Path from Single-Cluster

### Phase 1: Add Status Endpoint (No Breaking Changes)
1. Deploy updated forge manager with `/cluster-status` endpoint
2. Verify endpoint responds correctly
3. No functional changes - still single cluster

### Phase 2: Deploy Secondary Cluster
1. Deploy second cluster with lower priority
2. No peer polling configured yet
3. Both clusters forge independently (acceptable for testing)

### Phase 3: Enable Cross-Cluster Coordination
1. Update CRDs to add peer configuration
2. Primary cluster polls secondary, starts priority comparison
3. Secondary cluster stops forging (lower priority)
4. Monitor for 48 hours

### Phase 4: Add Additional Regions
1. Deploy tertiary cluster
2. Update all cluster CRDs with new peer
3. Verify priority ordering works correctly

## Acceptance Criteria

This solution satisfies:

- ✅ **FR9.3** - Cross-Cluster Priority System (independent K8s clusters)
- ✅ **EC12** - Cross-Cluster Communication Failure (HTTP polling with fail-safe)
- ✅ **EC14** - Priority Conflict Resolution (timestamp tiebreaker)
- ✅ **EC15** - Cluster Health vs Priority (health integrated into eligibility)

Additional criteria:

- ✅ Works across independent Kubernetes clusters
- ✅ Works across cloud providers and on-premises
- ✅ Works in air-gapped environments (one-way polling)
- ✅ No shared infrastructure required (no etcd, Redis, etc.)
- ✅ Simple HTTP-based protocol
- ✅ Fail-safe defaults (unreachable = excluded)
- ✅ Configurable via CRD (GitOps-friendly)
- ✅ Security-aware (auth, TLS, rate limiting)
- ✅ Observable (metrics, logs, CRD status)

## Implementation Checklist

- [ ] Add `peerClusters` to CardanoForgeCluster CRD schema
- [ ] Add `peerStatus` to CRD status schema
- [ ] Implement `/cluster-status` HTTP endpoint
- [ ] Implement peer authentication (bearer token, mTLS)
- [ ] Add `_poll_peer_clusters()` method
- [ ] Add `_poll_single_peer()` method with retries
- [ ] Add `_peer_polling_loop()` background thread
- [ ] Update `should_allow_forging()` to use peer data
- [ ] Add peer status metrics (reachability, latency, errors)
- [ ] Add priority decision metrics
- [ ] Update helm charts with peer configuration examples
- [ ] Write unit tests for polling logic
- [ ] Write integration tests (mock HTTP servers)
- [ ] Document security best practices
- [ ] Create operational runbooks (failover procedures)

## Summary

This solution enables **true multi-cluster coordination** for independently deployed Kubernetes clusters across any infrastructure:

- **Decentralized**: No shared infrastructure or single points of failure
- **Simple**: Standard HTTP polling, works everywhere
- **Secure**: Multiple auth options, TLS support
- **Resilient**: Fail-safe defaults, graceful degradation
- **Observable**: Full metrics, logs, and status visibility
- **Practical**: Works with existing network security patterns

The key insight: **Pull-based status polling** is simple, reliable, and works across any network topology - from cloud-native to air-gapped environments.
