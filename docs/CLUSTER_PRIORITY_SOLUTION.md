# Cross-Cluster Priority Comparison - Implementation Solution

## Problem Statement

Currently, on lines 311-315 of `src/cluster_manager.py`, the `should_allow_forging()` method contains a TODO for implementing full cluster-wide checking. The current implementation only evaluates the local cluster's priority without comparing against other clusters in the same network/pool scope.

```python
# Priority-based decision making
if effective_state == "Priority-based":
    # TODO: Implement cross-cluster priority comparison
    # For now, allow if this cluster has reasonable priority
    if effective_priority <= 10:  # High priority clusters
        return True, f"high_priority_{effective_priority}"
    else:
        return True, f"priority_based_{effective_priority}"
```

This incomplete implementation violates **Functional Requirement FR9.3** from the requirements document:
- **FR9.3 - Cross-Cluster Priority System**: Only the highest priority "enabled" cluster should have active forging.

## Current System Architecture

### Multi-Tenant Isolation Model

The system implements multi-tenant support where each deployment is uniquely identified by:
- **Network**: `mainnet`, `preprod`, `preview`, or custom networks
- **Pool ID**: Unique identifier for the stake pool (e.g., `pool1abcd...`)
- **Region**: Geographic/cluster location (e.g., `us-east-1`, `eu-west-1`)

**Cluster Name Format**: `{network}-{pool-short-id}-{region}`
- Example: `mainnet-pool1abcd-us-east-1`

**Leadership Scope**: Leader election (Kubernetes Lease) is scoped to **network + pool**, ensuring complete isolation between different pools and networks.

### Current CRD Structure

Each cluster has its own `CardanoForgeCluster` CRD with:

**Spec Fields:**
- `forgeState`: `Enabled`, `Disabled`, or `Priority-based`
- `priority`: Integer (1=highest, 999=lowest)
- `region`, `environment`, `clusterIdentifier`
- `healthCheck`: Optional health monitoring configuration
- `override`: Optional manual failover settings

**Status Fields:**
- `effectiveState`: Computed state based on spec and health
- `effectivePriority`: Computed priority considering health and overrides
- `activeLeader`: Current leader pod name
- `lastTransition`: Timestamp of last state change
- `conditions`: Array of status conditions
- `healthStatus`: Health check results

## Solution Design

### Overview

Implement **declarative priority-based coordination** where each cluster independently determines if it should forge by:
1. Discovering all clusters in the same network/pool scope
2. Comparing its effective priority against discovered clusters
3. Allowing forging only if it has the highest priority among healthy, enabled clusters

This is **not active coordination** (clusters don't communicate directly), but rather **convergent decision-making** based on shared CRD state.

### Key Design Principles

1. **Kubernetes-Native**: Use CRD label selectors for cluster discovery
2. **Eventual Consistency**: Accept temporary split-brain during state transitions
3. **Safety First**: Default to disabling forging when uncertain
4. **Health-Aware**: Unhealthy clusters automatically reduce their effective priority
5. **Graceful Degradation**: Single cluster deployments work without changes
6. **Network/Pool Scoped**: Cross-cluster comparison only within same network and pool

### Implementation Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cluster Discovery Phase                      │
│                                                                   │
│  1. List all CardanoForgeCluster CRDs with labels:              │
│     - cardano.io/network={CARDANO_NETWORK}                       │
│     - cardano.io/pool-id={POOL_ID}                               │
│                                                                   │
│  2. Filter by forgeState: Include only "Enabled" or              │
│     "Priority-based" clusters                                    │
│                                                                   │
│  3. Filter by health: Exclude clusters with failing health       │
│     checks (consecutive failures > threshold)                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Priority Comparison Phase                     │
│                                                                   │
│  1. Extract effectivePriority from each cluster CRD status       │
│                                                                   │
│  2. Find minimum priority value (1 = highest priority)           │
│                                                                   │
│  3. Check if THIS cluster has the minimum priority:              │
│     - If yes → Allow forging                                     │
│     - If no  → Deny forging                                      │
│                                                                   │
│  4. Tiebreaker: If multiple clusters have same priority,         │
│     use cluster creation timestamp (metadata.creationTimestamp)  │
└─────────────────────────────────────────────────────────────────┘
```

## Detailed Implementation Plan

### Phase 1: Cluster Discovery Method

Add a new method to `ClusterForgeManager`:

```python
def _discover_peer_clusters(self) -> List[Dict[str, Any]]:
    """
    Discover all CardanoForgeCluster CRDs in the same network/pool scope.
    
    Returns:
        List of CRD objects for peer clusters (excluding self).
    """
    if not self.pool_id or not self.network:
        logger.warning("Cannot discover peer clusters: pool_id or network not configured")
        return []
    
    try:
        # Query CRDs with network and pool labels
        label_selector = f"cardano.io/network={self.network},cardano.io/pool-id={self.pool_id}"
        
        crd_list = self.api.list_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=self._namespace,
            plural=CRD_PLURAL,
            label_selector=label_selector,
        )
        
        # Filter out self and extract items
        peer_clusters = [
            item for item in crd_list.get("items", [])
            if item.get("metadata", {}).get("name") != self.cluster_id
        ]
        
        logger.debug(
            f"Discovered {len(peer_clusters)} peer clusters for network={self.network}, "
            f"pool={self.pool_id}"
        )
        
        return peer_clusters
        
    except ApiException as e:
        logger.error(f"Failed to discover peer clusters: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error discovering peer clusters: {e}")
        return []
```

### Phase 2: Priority Comparison Logic

Add helper methods for priority evaluation:

```python
def _is_cluster_eligible_for_forging(self, cluster_crd: Dict[str, Any]) -> bool:
    """
    Check if a cluster CRD represents an eligible forging cluster.
    
    A cluster is eligible if:
    - forgeState is Enabled or Priority-based (not Disabled)
    - Health checks are passing (if enabled)
    
    Args:
        cluster_crd: The CRD object to evaluate
        
    Returns:
        True if cluster is eligible for forging consideration
    """
    spec = cluster_crd.get("spec", {})
    status = cluster_crd.get("status", {})
    
    # Check forge state
    forge_state = spec.get("forgeState", "Priority-based")
    if forge_state == "Disabled":
        return False
    
    # Check health status
    health_status = status.get("healthStatus", {})
    if health_status.get("enabled", False):
        consecutive_failures = health_status.get("consecutiveFailures", 0)
        failure_threshold = spec.get("healthCheck", {}).get("failureThreshold", 3)
        
        if consecutive_failures >= failure_threshold:
            logger.debug(
                f"Cluster {cluster_crd.get('metadata', {}).get('name')} "
                f"excluded due to health failures: {consecutive_failures}/{failure_threshold}"
            )
            return False
    
    return True


def _get_effective_priority_from_crd(self, cluster_crd: Dict[str, Any]) -> int:
    """
    Extract effective priority from a cluster CRD.
    
    Reads from status.effectivePriority if available, otherwise falls back
    to spec.priority or a default value.
    
    Args:
        cluster_crd: The CRD object
        
    Returns:
        Effective priority as integer (1=highest, 999=lowest)
    """
    status = cluster_crd.get("status", {})
    spec = cluster_crd.get("spec", {})
    
    # Prefer effectivePriority from status (accounts for health and overrides)
    effective_priority = status.get("effectivePriority")
    if effective_priority is not None:
        return int(effective_priority)
    
    # Fallback to spec priority
    spec_priority = spec.get("priority")
    if spec_priority is not None:
        return int(spec_priority)
    
    # Ultimate fallback
    return 100


def _resolve_priority_tie(
    self, 
    this_priority: int, 
    peer_cluster: Dict[str, Any]
) -> bool:
    """
    Resolve priority tie using cluster creation timestamp.
    
    If this cluster and a peer have the same effective priority, the older
    cluster (earlier creationTimestamp) wins.
    
    Args:
        this_priority: This cluster's effective priority
        peer_cluster: Peer cluster CRD object
        
    Returns:
        True if this cluster should win the tiebreak
    """
    peer_priority = self._get_effective_priority_from_crd(peer_cluster)
    
    if this_priority != peer_priority:
        return False  # Not a tie
    
    # Compare creation timestamps
    this_timestamp = self._current_cluster_crd.get("metadata", {}).get("creationTimestamp", "")
    peer_timestamp = peer_cluster.get("metadata", {}).get("creationTimestamp", "")
    
    # Older cluster (earlier timestamp) wins
    # ISO8601 timestamps can be compared lexicographically
    if this_timestamp and peer_timestamp:
        result = this_timestamp < peer_timestamp
        logger.debug(
            f"Priority tie ({this_priority}) resolved by timestamp: "
            f"this={this_timestamp}, peer={peer_timestamp}, winner={'this' if result else 'peer'}"
        )
        return result
    
    # If timestamps unavailable, fall back to cluster ID comparison (deterministic)
    this_name = self.cluster_id
    peer_name = peer_cluster.get("metadata", {}).get("name", "")
    return this_name < peer_name
```

### Phase 3: Updated `should_allow_forging()` Method

Replace the TODO section with full implementation:

```python
def should_allow_forging(self) -> Tuple[bool, str]:
    """
    Determine if forging should be enabled for the current leader.
    
    This method evaluates the cluster-wide forging policy and returns
    whether the current leader should actually forge blocks.
    
    Returns:
        Tuple[bool, str]: (forging_allowed, reason)
    """
    if not self.enabled:
        return True, "cluster_management_disabled"

    if not self._current_cluster_crd:
        # If CRD doesn't exist, default to allowing forging (backward compatibility)
        return True, "no_cluster_crd"

    try:
        spec = self._current_cluster_crd.get("spec", {})
        forge_state = spec.get("forgeState", "Priority-based")
        base_priority = spec.get("priority", self.priority)
        
        # Calculate effective state using the same logic as status updates
        effective_state, effective_priority, calc_reason, calc_message = self._calculate_effective_state_and_priority(
            forge_state, base_priority
        )

        if effective_state == "Disabled":
            return False, "cluster_forge_disabled"

        if effective_state == "Enabled":
            # Explicit enable - forge regardless of priority
            return True, "cluster_forge_enabled"

        # Priority-based decision making - NEW IMPLEMENTATION
        if effective_state == "Priority-based":
            # Single-tenant backward compatibility: if no pool ID, allow forging
            if not self.pool_id or not self.network:
                logger.debug("Legacy single-tenant mode: allowing forging without cross-cluster check")
                return True, "legacy_single_tenant"
            
            # Discover peer clusters in the same network/pool scope
            peer_clusters = self._discover_peer_clusters()
            
            if not peer_clusters:
                # No other clusters found - we're the only one
                logger.debug("No peer clusters discovered, allowing forging as sole cluster")
                return True, f"sole_cluster_priority_{effective_priority}"
            
            # Filter eligible peers (not disabled, healthy)
            eligible_peers = [
                peer for peer in peer_clusters
                if self._is_cluster_eligible_for_forging(peer)
            ]
            
            if not eligible_peers:
                # No eligible competitors - we can forge
                logger.debug(f"All {len(peer_clusters)} peer clusters ineligible, allowing forging")
                return True, f"all_peers_ineligible_priority_{effective_priority}"
            
            # Compare our priority against all eligible peers
            our_priority = effective_priority
            higher_priority_found = False
            
            for peer in eligible_peers:
                peer_name = peer.get("metadata", {}).get("name", "unknown")
                peer_priority = self._get_effective_priority_from_crd(peer)
                
                if peer_priority < our_priority:
                    # Peer has better (lower) priority - we should not forge
                    logger.info(
                        f"Denying forging: peer cluster {peer_name} has higher priority "
                        f"({peer_priority} < {our_priority})"
                    )
                    higher_priority_found = True
                    break
                elif peer_priority == our_priority:
                    # Priority tie - use tiebreaker
                    if not self._resolve_priority_tie(our_priority, peer):
                        logger.info(
                            f"Denying forging: lost priority tiebreak to peer {peer_name} "
                            f"(both priority {our_priority})"
                        )
                        higher_priority_found = True
                        break
            
            if higher_priority_found:
                return False, f"lower_priority_{our_priority}_vs_peers"
            
            # We have the highest priority among all eligible clusters
            logger.info(
                f"Allowing forging: highest priority ({our_priority}) among "
                f"{len(eligible_peers)} eligible peer clusters"
            )
            return True, f"highest_priority_{our_priority}"

        return True, "default_allow"

    except Exception as e:
        logger.error(f"Error evaluating cluster forging policy: {e}")
        # Fail-safe: deny forging on error to prevent split-brain
        return False, "evaluation_error"
```

## Edge Cases and Safety Considerations

### 1. Split-Brain During State Transitions

**Problem**: When priority changes propagate, two clusters might temporarily believe they're highest priority.

**Mitigation**:
- CRD watch detects changes within seconds (typical watch latency: 1-3 seconds)
- Each cluster re-evaluates priority every `SLEEP_INTERVAL` (configurable)
- Metrics alert on `sum(cardano_cluster_forge_enabled) > 1`
- Brief dual-forging (seconds) is acceptable vs. no forging

### 2. Network Partition / API Server Unavailability

**Problem**: Cannot discover peer clusters if API calls fail.

**Mitigation**:
- Return `False` (deny forging) on API errors when in Priority-based mode
- Log errors at ERROR level for alerting
- Retry with exponential backoff in watch loop
- Single cluster deployments unaffected (no peers to discover)

### 3. Stale CRD Data

**Problem**: A peer cluster's CRD shows healthy/enabled, but actually crashed.

**Mitigation**:
- Health check failures automatically increase effective priority
- After `failureThreshold` consecutive failures, cluster becomes ineligible
- Watch updates propagate health status changes within seconds
- Kubernetes lease timeout handles complete pod failures

### 4. Priority Conflicts (Equal Priority)

**Problem**: Multiple clusters configured with same priority.

**Mitigation**:
- Tiebreaker logic: older cluster (by `creationTimestamp`) wins
- Deterministic fallback: lexicographic cluster name comparison
- Log priority conflicts at INFO level
- Document best practice: assign unique priorities

### 5. Clock Skew / Timestamp Issues

**Problem**: Cluster creation timestamps might be unreliable.

**Mitigation**:
- Timestamps managed by Kubernetes API server (single source of truth)
- ISO8601 format ensures lexicographic comparison works
- Fallback to cluster name comparison if timestamps missing
- Tiebreaker only used for equal priorities (rare)

### 6. New Cluster Joining

**Problem**: New cluster joins mid-operation, should it take over?

**Mitigation**:
- New cluster only forges if it has better priority than current forger
- CRD watch ensures existing clusters detect new cluster within seconds
- Priority-based system naturally handles this (no special logic needed)
- Status updates reflect the current state accurately

### 7. Single Cluster Operation (Backward Compatibility)

**Problem**: Existing single-cluster deployments shouldn't break.

**Mitigation**:
- If no `POOL_ID` or `CARDANO_NETWORK`, skip cross-cluster check (legacy mode)
- If no peer clusters discovered, allow forging (sole cluster)
- Default behavior unchanged for non-multi-tenant setups

## Configuration and Deployment

### Environment Variables

**No new environment variables required**. Uses existing configuration:
- `ENABLE_CLUSTER_MANAGEMENT=true` - Enable cluster coordination
- `CARDANO_NETWORK` - Network scope for peer discovery
- `POOL_ID` - Pool scope for peer discovery
- `CLUSTER_PRIORITY` - This cluster's base priority

### CRD Label Requirements

CRDs **must** include these labels for discovery:
```yaml
metadata:
  labels:
    cardano.io/network: mainnet  # or preprod, preview, custom
    cardano.io/pool-id: pool1abcd...  # Full pool ID
```

These labels are already added by `_create_cluster_crd()` in the current implementation.

### RBAC Permissions

The existing RBAC is sufficient. The sidecar already has:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
rules:
- apiGroups: ["cardano.io"]
  resources: ["cardanoforgeclusters"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
```

The `list` verb with `label_selector` is what enables peer discovery.

## Testing Strategy

### Unit Tests

1. **Test `_discover_peer_clusters()`**:
   - Returns empty list when no peers exist
   - Filters out self from results
   - Applies label selector correctly
   - Handles API exceptions gracefully

2. **Test `_is_cluster_eligible_for_forging()`**:
   - Excludes disabled clusters
   - Excludes unhealthy clusters (failures > threshold)
   - Includes healthy enabled/priority-based clusters

3. **Test `_resolve_priority_tie()`**:
   - Older cluster wins by timestamp
   - Fallback to name comparison
   - Returns false when not a tie

4. **Test `should_allow_forging()` scenarios**:
   - Single cluster: allow forging
   - Highest priority among peers: allow
   - Lower priority than peer: deny
   - Equal priority, older timestamp: allow
   - Equal priority, newer timestamp: deny
   - All peers unhealthy: allow
   - All peers disabled: allow
   - API error: deny (fail-safe)

### Integration Tests

1. **Multi-cluster coordination**:
   - Deploy 3 clusters with priorities 1, 2, 3
   - Verify only priority-1 cluster forges
   - Disable priority-1, verify priority-2 takes over
   - Re-enable priority-1, verify it reclaims leadership

2. **Health-based failover**:
   - Deploy 2 clusters with priorities 1, 2
   - Simulate health failures on priority-1
   - Verify priority-2 takes over automatically

3. **Network partition simulation**:
   - Block API access temporarily
   - Verify clusters stop forging (fail-safe)
   - Restore access, verify normal operation resumes

## Metrics and Observability

### New Metrics

Add to Prometheus exporter:

```python
# Number of eligible peer clusters discovered
cardano_peer_clusters_total{network="mainnet", pool_id="pool1abcd"} 2

# Our effective priority ranking (1=best)
cardano_cluster_priority_rank{network="mainnet", pool_id="pool1abcd", cluster="us-east-1"} 1

# Cross-cluster comparison result
cardano_priority_comparison_result{result="highest_priority"} 1
cardano_priority_comparison_result{result="lower_priority"} 0
cardano_priority_comparison_result{result="evaluation_error"} 0
```

### Enhanced Logging

Log messages for debugging:
- `INFO`: Priority comparison result (allow/deny with reason)
- `DEBUG`: Discovered peer clusters count and details
- `DEBUG`: Per-peer priority comparison
- `INFO`: Priority tie resolution
- `ERROR`: API failures during discovery
- `WARNING`: Configuration issues (missing pool ID, etc.)

### Alerts

```yaml
# Multiple clusters forging simultaneously (split-brain)
- alert: CardanoMultiClusterForging
  expr: sum(cardano_cluster_forge_enabled{network="mainnet", pool_id="pool1abcd"}) > 1
  for: 30s
  severity: critical

# No cluster forging (total outage)
- alert: CardanoNoClusterForging
  expr: sum(cardano_cluster_forge_enabled{network="mainnet", pool_id="pool1abcd"}) == 0
  for: 60s
  severity: warning

# Priority comparison errors
- alert: CardanoPriorityComparisonErrors
  expr: rate(cardano_priority_comparison_result{result="evaluation_error"}[5m]) > 0.1
  for: 5m
  severity: warning
```

## Operational Procedures

### Manual Failover

To manually failover from region A to region B:

```bash
# 1. Increase priority of target cluster (lower number = higher priority)
kubectl patch cardanoforgeCluster mainnet-pool1abcd-us-west-2 \
  --type=merge -p '{"spec":{"priority":1}}'

# 2. Decrease priority of current cluster
kubectl patch cardanoforgeCluster mainnet-pool1abcd-us-east-1 \
  --type=merge -p '{"spec":{"priority":2}}'

# 3. Monitor transition (should happen within 10-15 seconds)
watch kubectl get cardanoforgeCluster -l cardano.io/network=mainnet,cardano.io/pool-id=pool1abcd
```

### Emergency Global Disable

Disable forging across all clusters immediately:

```bash
# Disable all clusters in a network/pool scope
for cluster in $(kubectl get cardanoforgeCluster \
  -l cardano.io/network=mainnet,cardano.io/pool-id=pool1abcd \
  -o jsonpath='{.items[*].metadata.name}'); do
  kubectl patch cardanoforgeCluster $cluster \
    --type=merge -p '{"spec":{"forgeState":"Disabled"}}'
done
```

### Verify Cross-Cluster State

Check which cluster should be forging:

```bash
# Show all clusters with priorities and effective states
kubectl get cardanoforgeCluster \
  -l cardano.io/network=mainnet,cardano.io/pool-id=pool1abcd \
  -o custom-columns=\
NAME:.metadata.name,\
PRIORITY:.spec.priority,\
EFFECTIVE_PRIORITY:.status.effectivePriority,\
FORGE_STATE:.spec.forgeState,\
EFFECTIVE_STATE:.status.effectiveState,\
HEALTHY:.status.healthStatus.healthy,\
LEADER:.status.activeLeader
```

## Acceptance Criteria

Implementing this solution will satisfy:

- ✅ **FR9.3** - Cross-Cluster Priority System
- ✅ **EC12** - Cross-Cluster Communication Failure handling
- ✅ **EC14** - Priority Conflict Resolution
- ✅ **EC15** - Cluster Health vs Priority Mismatch

From the acceptance criteria checklist:

- ✅ Priority system prevents multiple clusters from forging simultaneously
- ✅ Priority-based decision making works across multiple clusters
- ✅ Cluster creation timestamp used as tiebreaker for equal priorities
- ✅ Clusters make independent decisions based on local CRD state
- ✅ Default behavior during communication failure is safe (no dual forging)
- ✅ Health checks influence effective priority calculation

## Implementation Checklist

- [ ] Add `_discover_peer_clusters()` method
- [ ] Add `_is_cluster_eligible_for_forging()` method
- [ ] Add `_get_effective_priority_from_crd()` method
- [ ] Add `_resolve_priority_tie()` method
- [ ] Update `should_allow_forging()` with full implementation
- [ ] Add new Prometheus metrics for peer discovery and comparison
- [ ] Write unit tests for all new methods
- [ ] Write integration tests for multi-cluster scenarios
- [ ] Update documentation with operational procedures
- [ ] Add Prometheus alert rules for split-brain detection
- [ ] Test backward compatibility (single-cluster deployments)
- [ ] Test failover scenarios (manual and health-based)
- [ ] Update helm chart examples with multi-cluster configs

## Rollout Plan

### Phase 1: Implementation (1-2 days)
- Implement all methods
- Write comprehensive unit tests
- Local testing with mock CRDs

### Phase 2: Integration Testing (2-3 days)
- Deploy to test cluster with 3 regions
- Verify priority-based coordination
- Test health-based failover
- Test network partition scenarios
- Verify metrics and logging

### Phase 3: Staging Validation (3-5 days)
- Deploy to preprod network
- Monitor for 48+ hours
- Validate alert rules
- Test manual failover procedures
- Document any issues

### Phase 4: Production Rollout (Gradual)
- Week 1: Single mainnet pool (non-critical)
- Week 2: Additional pools if successful
- Week 3+: Full fleet rollout

## Success Criteria

The implementation is successful when:

1. ✅ Only one cluster forges at a time (verified by metrics)
2. ✅ Priority changes trigger failover within 15 seconds
3. ✅ Health failures trigger automatic failover
4. ✅ Split-brain conditions are rare (<1% of transitions) and brief (<30s)
5. ✅ No forging gaps during normal failover
6. ✅ Single-cluster deployments continue to work unchanged
7. ✅ Alerts fire correctly for split-brain and outage conditions

## References

- Requirements: `docs/cardano-k8s-dynamic-forging-requirements.md`
  - FR9.3 (lines 83-87): Cross-Cluster Priority System
  - EC12 (lines 103-107): Cross-Cluster Communication Failure
  - EC14 (lines 115-119): Priority Conflict Resolution
  - Section 5 (lines 638-878): Multi-Tenant Support

- Current Implementation: `src/cluster_manager.py`
  - Line 311-315: TODO location
  - Line 276-322: `should_allow_forging()` method
  - Line 145-190: `ClusterForgeManager` initialization

- CRD Examples: `examples/multi-region-forge-clusters.yaml`
  - Multi-region priority configurations
  - Health check integration examples
