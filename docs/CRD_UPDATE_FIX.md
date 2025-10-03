# CRD Update Logic Fix - Multi-Replica Support

## Problem Statement

In StatefulSet deployments with multiple replicas, the CardanoLeader CRD was not being updated correctly. The CRD would show `leaderPod: ""` and `forgingEnabled: false` even when a pod successfully held the lease and was actively forging.

## Root Cause

The previous implementation used an in-memory cache (`last_crd_leader_state`, `last_crd_forging_state`) to track "what we last wrote" to the CRD. This optimization aimed to reduce unnecessary API calls by skipping updates when "nothing changed."

**The fatal flaw**: The cache was initialized to `None` on startup and was never synchronized with the actual live CRD state. This caused the following scenario:

1. Pod-0 starts, acquires lease
2. Pod-0 checks: `last_crd_leader_state (None) != "cardano-bp-0"` → State changed
3. Pod-0 **would** update CRD... but the logic was more complex
4. Pod-1 starts, doesn't acquire lease
5. Both pods think "no change needed" and skip CRD updates
6. CRD remains empty/stale

## The Core Design Flaw

The optimization logic violated a fundamental principle from the requirements document (mermaid diagram, line 311):

```
Sidecar-New->>CRD: Update status: leaderPod=pod-name, forgingEnabled=true
```

**The rule is simple**: If you hold the lease, write your pod name to the CRD. No caching, no optimization, no "skip if unchanged."

## The Solution

Completely redesigned the `update_leader_status()` function with crystal-clear logic:

### New Logic

```python
if is_leader:
    # ALWAYS update when we hold the lease - this is the source of truth
    should_update = True
else:
    # Non-leader: Only update if CRD incorrectly shows us as leader (cleanup stale data)
    current_crd = read_live_crd()
    if current_crd.leaderPod == POD_NAME:
        should_update = True  # Clear stale entry
    else:
        should_update = False  # Don't interfere with actual leader
```

### Key Changes

1. **Removed all state tracking variables**:
   - Deleted `last_crd_leader_state`
   - Deleted `last_crd_forging_state`
   - Deleted `crd_status_initialized`

2. **Leader behavior**:
   - If you hold the lease → ALWAYS write to CRD
   - No caching, no "skip if unchanged"
   - Every iteration writes the leader pod name

3. **Non-leader behavior**:
   - Check live CRD state
   - Only write if CRD incorrectly shows this pod as leader
   - Otherwise, don't touch the CRD (let the actual leader maintain it)

## Benefits

1. **Correctness**: CRD always reflects the current lease holder
2. **Simplicity**: No complex state tracking or synchronization
3. **Robustness**: Works correctly even if pods restart or CRD is manually modified
4. **Multi-replica safe**: Each pod knows its role and acts accordingly

## Trade-offs

- **More API calls**: Leader writes CRD every iteration (every SLEEP_INTERVAL seconds)
- **Acceptable**: Kubernetes API can easily handle this load
- **Worth it**: Correctness > Performance for critical leadership state

## Testing

All 108 unit tests pass, including:
- Multi-replica scenarios
- Leadership transitions
- Race conditions
- API failures
- Cluster management integration

## Deployment Verification

After deploying this fix:

1. Single replica: CRD should show that pod as leader with forging enabled
2. Multiple replicas: CRD should show exactly one pod as leader
3. Leader failover: CRD should immediately update to show new leader
4. No more empty/stale CRD states

## Related Documentation

- `docs/cardano-k8s-dynamic-forging-requirements.md` - Sequence diagram (lines 262-314)
- Requirements FR2, FR4, FR7 - CRD status management
- Edge Case EC11 - Leadership forfeiture race conditions
