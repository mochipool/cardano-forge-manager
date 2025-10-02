# Cluster-Wide Forge Management Operations Guide

This guide provides step-by-step operational procedures for Stake Pool Operators (SPOs) using the cluster-wide forge management system across multiple regions or availability zones.

## Table of Contents
1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Daily Operations](#daily-operations)
4. [Manual Failover Procedures](#manual-failover-procedures)
5. [Monitoring and Alerting](#monitoring-and-alerting)
6. [Maintenance Procedures](#maintenance-procedures)
7. [Troubleshooting](#troubleshooting)
8. [Emergency Procedures](#emergency-procedures)

---

## Overview

### Architecture Summary

The cluster-wide forge management system allows SPOs to:

- **Deploy multiple clusters** across regions/zones for high availability
- **Automatically coordinate** which cluster is actively forging blocks
- **Manually failover** between clusters for maintenance or disaster recovery
- **Monitor forge state** across all clusters from a single dashboard

### Key Components

- **CardanoForgeCluster CRD**: Manages forge state at cluster level
- **Priority System**: Ensures only highest priority cluster forges
- **Health Checks**: Automatic failover based on cluster health
- **Metrics**: Cluster-wide observability for monitoring

---

## Quick Start

### 1. Verify Cluster State

Check the current state of all your clusters:

```bash
# List all forge clusters
kubectl get cardanoforgeclusters -o wide

# Example output:
# NAME              STATE           PRIORITY   REGION      ACTIVE LEADER        HEALTHY   AGE
# us-east-1-prod    Priority-based  1          us-east-1   cardano-bp-0         true      2d
# us-west-2-prod    Priority-based  2          us-west-2                        true      2d
# eu-west-1-prod    Priority-based  3          eu-west-1                        true      1d
```

### 2. Check Active Forging

Verify which cluster is currently forging:

```bash
# Check metrics across all clusters
curl -s http://your-monitoring.example.com/api/v1/query?query=cardano_cluster_forge_enabled | jq

# Expected: Only one cluster should show value "1"
```

### 3. Validate Configuration

Ensure your cluster priorities are correct:

```bash
# Primary cluster should have priority 1
kubectl get cardanoforgeCluster us-east-1-prod -o jsonpath='{.spec.priority}'

# Secondary clusters should have higher numbers (lower priority)
kubectl get cardanoforgeCluster us-west-2-prod -o jsonpath='{.spec.priority}'
```

---

## Daily Operations

### Morning Checklist

1. **Check Cluster Health**
   ```bash
   kubectl get cardanoforgeclusters -o custom-columns='NAME:.metadata.name,STATE:.status.effectiveState,PRIORITY:.status.effectivePriority,LEADER:.status.activeLeader,HEALTHY:.status.healthStatus.healthy'
   ```

2. **Verify Single Active Forger**
   ```bash
   # Should return exactly 1
   curl -s http://monitoring.example.com/api/v1/query?query='sum(cardano_cluster_forge_enabled)' | jq '.data.result[0].value[1]'
   ```

3. **Check Block Production**
   ```bash
   # Check recent blocks from your pool
   curl -s "https://api.koios.rest/api/v1/pool_blocks?_pool_bech32=${POOL_ID}&_limit=10" | jq
   ```

4. **Review Alerts**
   ```bash
   # Check for any active alerts
   curl -s http://alertmanager.example.com/api/v1/alerts | jq '.data[] | select(.state == "firing")'
   ```

### Weekly Tasks

1. **Review Health Check Logs**
   ```bash
   kubectl logs -l app=cardano-node -c forge-manager | grep "health check" | tail -20
   ```

2. **Check Resource Usage**
   ```bash
   # Monitor CPU/Memory usage
   kubectl top pods -l app=cardano-node --containers
   ```

3. **Verify CRD Status**
   ```bash
   # Detailed status of all clusters
   kubectl describe cardanoforgeclusters
   ```

---

## Manual Failover Procedures

### Scenario 1: Planned Maintenance on Primary Cluster

When you need to perform maintenance on your primary cluster:

```bash
#!/bin/bash
# failover-for-maintenance.sh

PRIMARY_CLUSTER="us-east-1-prod"
SECONDARY_CLUSTER="us-west-2-prod"

echo "1. Check current state:"
kubectl get cardanoforgeclusters -o wide

echo "2. Disable primary cluster:"
kubectl patch cardanoforgeCluster $PRIMARY_CLUSTER --type='merge' -p='{
  "spec": {
    "forgeState": "Disabled",
    "override": {
      "enabled": true,
      "reason": "Scheduled maintenance",
      "expiresAt": "'$(date -d "+4 hours" --iso-8601=seconds)'"
    }
  }
}'

echo "3. Wait for secondary to take over (30 seconds):"
sleep 30

echo "4. Verify secondary cluster is now forging:"
kubectl get cardanoforgeCluster $SECONDARY_CLUSTER -o jsonpath='{.status.activeLeader}'

echo "5. Check metrics:"
curl -s http://monitoring.example.com/api/v1/query?query='cardano_cluster_forge_enabled{cluster="'$SECONDARY_CLUSTER'"}'

echo "Failover complete. Perform maintenance on $PRIMARY_CLUSTER"
echo "To restore: run restore-after-maintenance.sh"
```

### Scenario 2: Restore After Maintenance

After completing maintenance on the primary cluster:

```bash
#!/bin/bash
# restore-after-maintenance.sh

PRIMARY_CLUSTER="us-east-1-prod"

echo "1. Re-enable primary cluster:"
kubectl patch cardanoforgeCluster $PRIMARY_CLUSTER --type='merge' -p='{
  "spec": {
    "forgeState": "Priority-based",
    "override": {
      "enabled": false
    }
  }
}'

echo "2. Wait for primary to resume leadership (60 seconds):"
sleep 60

echo "3. Verify primary cluster is forging again:"
kubectl get cardanoforgeCluster $PRIMARY_CLUSTER -o jsonpath='{.status.activeLeader}'

echo "4. Confirm all clusters are healthy:"
kubectl get cardanoforgeclusters -o wide

echo "Restore complete. Primary cluster is active again."
```

### Scenario 3: Emergency Failover

In case of emergency (primary cluster failure):

```bash
#!/bin/bash
# emergency-failover.sh

FAILED_CLUSTER="us-east-1-prod"
BACKUP_CLUSTER="us-west-2-prod"

echo "EMERGENCY FAILOVER INITIATED"

echo "1. Force disable failed cluster:"
kubectl patch cardanoforgeCluster $FAILED_CLUSTER --type='merge' -p='{
  "spec": {
    "forgeState": "Disabled",
    "override": {
      "enabled": true,
      "reason": "Emergency failover - primary cluster failure"
    }
  }
}' || echo "WARNING: Failed to update failed cluster (expected if cluster is down)"

echo "2. Force enable backup cluster with high priority:"
kubectl patch cardanoforgeCluster $BACKUP_CLUSTER --type='merge' -p='{
  "spec": {
    "override": {
      "enabled": true,
      "reason": "Emergency failover",
      "forcePriority": 1
    }
  }
}'

echo "3. Verify backup cluster status:"
sleep 30
kubectl get cardanoforgeCluster $BACKUP_CLUSTER -o wide

echo "EMERGENCY FAILOVER COMPLETE"
echo "Monitor metrics and investigate primary cluster failure"
```

---

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Cluster Forge Status**
   ```promql
   # Should always be exactly 1
   sum(cardano_cluster_forge_enabled)
   ```

2. **Active Cluster Priority**
   ```promql
   # Monitor which cluster is active
   cardano_cluster_forge_enabled * on() cardano_cluster_forge_priority
   ```

3. **Health Check Status**
   ```promql
   # All clusters should be healthy
   cardano_cluster_health_status{healthy="false"}
   ```

4. **Leadership Transitions**
   ```promql
   # Rate of leadership changes
   rate(cardano_leadership_changes_total[5m])
   ```

### Critical Alerts

Set up these alerts in your monitoring system:

```yaml
groups:
- name: cardano-cluster-forge
  rules:
  # Critical: Multiple clusters forging
  - alert: CardanoMultipleClusterForging
    expr: sum(cardano_cluster_forge_enabled) > 1
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Multiple Cardano clusters are forging blocks"
      description: "{{ $value }} clusters are currently forging. This can cause chain forks."

  # Critical: No clusters forging
  - alert: CardanoNoClusterForging
    expr: sum(cardano_cluster_forge_enabled) == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "No Cardano clusters are forging blocks"
      description: "Block production has stopped across all clusters."

  # Warning: Cluster health issues
  - alert: CardanoClusterUnhealthy
    expr: cardano_cluster_health_status{healthy="false"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Cardano cluster {{ $labels.cluster }} is unhealthy"
      description: "Health checks are failing for cluster {{ $labels.cluster }}"

  # Warning: Non-primary cluster forging
  - alert: CardanoSecondaryClusterForging
    expr: cardano_cluster_forge_enabled{priority!="1"} == 1
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Secondary cluster is forging blocks"
      description: "Cluster {{ $labels.cluster }} with priority {{ $labels.priority }} is forging instead of primary"
```

### Monitoring Dashboard

Create a dashboard with these panels:

1. **Cluster Status Table**
   - Cluster name, state, priority, active leader, health status

2. **Active Forger Graph**
   - Time series showing which cluster is forging over time

3. **Health Check Status**
   - Success rate and response time for each cluster

4. **Leadership Transitions**
   - Timeline of leadership changes with reasons

---

## Maintenance Procedures

### Monthly Health Checks

1. **Test Manual Failover**
   ```bash
   # Test failover to each cluster
   ./test-failover.sh us-west-2-prod
   sleep 300  # Let it run for 5 minutes
   ./restore-primary.sh us-east-1-prod
   ```

2. **Update Health Check Endpoints**
   ```bash
   # Verify health check URLs are working
   kubectl get cardanoforgeclusters -o json | jq -r '.items[].spec.healthCheck.endpoint' | xargs -I {} curl -f {}
   ```

3. **Review Priority Configuration**
   ```bash
   # Ensure priority order matches your disaster recovery plan
   kubectl get cardanoforgeclusters -o custom-columns='NAME:.metadata.name,PRIORITY:.spec.priority' --sort-by='{.spec.priority}'
   ```

### Quarterly Reviews

1. **Test Full Disaster Recovery**
   ```bash
   # Simulate complete primary cluster loss
   kubectl delete cardanoforgeCluster us-east-1-prod
   # ... verify secondary takes over ...
   # ... restore primary cluster ...
   ```

2. **Review and Update Procedures**
   - Update this operations guide
   - Review alert thresholds
   - Update failover scripts

3. **Security Audit**
   - Review RBAC permissions
   - Check CRD access controls
   - Validate health check endpoints

---

## Troubleshooting

### Common Issues

#### Issue 1: No Cluster is Forging

**Symptoms:**
```bash
$ kubectl get cardanoforgeclusters
NAME              STATE     PRIORITY   ACTIVE LEADER
us-east-1-prod    Disabled  1         
us-west-2-prod    Disabled  2         
```

**Resolution:**
```bash
# Enable highest priority cluster
kubectl patch cardanoforgeCluster us-east-1-prod --type='merge' -p='{
  "spec": {"forgeState": "Priority-based"}
}'

# Check result
kubectl get cardanoforgeCluster us-east-1-prod -o wide
```

#### Issue 2: Multiple Clusters Forging

**Symptoms:**
```bash
$ curl -s http://monitoring.example.com/api/v1/query?query='sum(cardano_cluster_forge_enabled)'
# Returns value > 1
```

**Resolution:**
```bash
# Immediately disable all secondary clusters
kubectl get cardanoforgeclusters --sort-by='{.spec.priority}' -o name | tail -n +2 | xargs -I {} kubectl patch {} --type='merge' -p='{"spec":{"forgeState":"Disabled"}}'

# Re-enable one by one after investigation
```

#### Issue 3: Health Checks Failing

**Symptoms:**
```bash
$ kubectl get cardanoforgeclusters -o jsonpath='{.items[*].status.healthStatus.healthy}'
false true true
```

**Resolution:**
```bash
# Check health endpoint manually
ENDPOINT=$(kubectl get cardanoforgeCluster us-east-1-prod -o jsonpath='{.spec.healthCheck.endpoint}')
curl -v $ENDPOINT

# If endpoint is down, temporarily disable health checks
kubectl patch cardanoforgeCluster us-east-1-prod --type='merge' -p='{
  "spec": {"healthCheck": {"enabled": false}}
}'
```

#### Issue 4: CRD Status Not Updating

**Symptoms:**
- CRD status shows stale information
- `lastTransition` timestamp is old

**Resolution:**
```bash
# Check forge manager logs
kubectl logs -l app=cardano-node -c forge-manager | tail -50

# Check RBAC permissions
kubectl auth can-i update cardanoforgeclusters/status --as=system:serviceaccount:cardano:forge-manager

# Restart forge manager if needed
kubectl rollout restart statefulset/cardano-node
```

### Debug Commands

```bash
# Get detailed cluster status
kubectl describe cardanoforgeCluster us-east-1-prod

# Check forge manager logs
kubectl logs statefulset/cardano-node -c forge-manager --tail=100

# Test health check endpoint
kubectl exec statefulset/cardano-node -c forge-manager -- curl -v $HEALTH_CHECK_ENDPOINT

# Check metrics from pod
kubectl port-forward statefulset/cardano-node 8000:8000
curl http://localhost:8000/metrics | grep cardano_cluster_
```

---

## Emergency Procedures

### Complete System Recovery

If all clusters become unavailable:

```bash
#!/bin/bash
# emergency-recovery.sh

echo "INITIATING EMERGENCY RECOVERY"

echo "1. Disable cluster management temporarily:"
kubectl patch statefulset cardano-node --type='merge' -p='{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "forge-manager",
            "env": [
              {"name": "ENABLE_CLUSTER_MANAGEMENT", "value": "false"}
            ]
          }
        ]
      }
    }
  }
}'

echo "2. Wait for rollout:"
kubectl rollout status statefulset/cardano-node

echo "3. Verify forge manager is working in single-cluster mode:"
kubectl logs statefulset/cardano-node -c forge-manager | tail -20

echo "4. Check local leadership:"
curl http://localhost:8000/metrics | grep cardano_leader_status

echo "EMERGENCY RECOVERY ACTIVE - INVESTIGATE AND FIX CLUSTER MANAGEMENT"
echo "To restore cluster management, run: restore-cluster-management.sh"
```

### Restore Cluster Management

After resolving the emergency:

```bash
#!/bin/bash
# restore-cluster-management.sh

echo "RESTORING CLUSTER MANAGEMENT"

echo "1. Re-enable cluster management:"
kubectl patch statefulset cardano-node --type='merge' -p='{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "forge-manager",
            "env": [
              {"name": "ENABLE_CLUSTER_MANAGEMENT", "value": "true"}
            ]
          }
        ]
      }
    }
  }
}'

echo "2. Wait for rollout:"
kubectl rollout status statefulset/cardano-node

echo "3. Verify cluster management is active:"
kubectl get cardanoforgeclusters -o wide

echo "4. Check cluster metrics:"
curl http://localhost:8000/metrics | grep cardano_cluster_

echo "CLUSTER MANAGEMENT RESTORED"
```

### Contact Information

Keep these contacts readily available:

- **Primary Infrastructure Team**: [your-team@example.com]
- **Monitoring System**: [monitoring.example.com]
- **Emergency Pager**: [+1-xxx-xxx-xxxx]
- **Cardano Community**: [Discord/Telegram channels]

### Documentation

- [Cluster Management Architecture](./README.md)
- [Testing Procedures](./TESTING.md)
- [Requirements Document](./cardano-k8s-dynamic-forging-requirements.md)

---

This operations guide provides the essential procedures for managing cluster-wide forge operations. Regular practice of these procedures ensures smooth operation during both planned maintenance and emergency situations.