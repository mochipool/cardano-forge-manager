# Multi-Tenant Implementation Summary: Network and Pool Isolation

## Overview

This document summarizes the implementation of multi-tenant support for the Cardano Forge Manager, enabling SPOs to run multiple stake pools across different Cardano networks (mainnet, preprod, preview) within the same Kubernetes cluster while maintaining complete isolation.

## ✨ Key Features Added

### 🔐 **Complete Isolation**
- **Network Isolation**: Pools on different networks operate independently
- **Pool Isolation**: Multiple pools on the same network cannot interfere with each other
- **Credential Isolation**: Each pool has its own secret management
- **Lease Isolation**: Leader election scoped to `network + pool`

### 🏷️ **Advanced Identification System**
- **Pool-Based Primary ID**: Each deployment uniquely identified by pool ID
- **Network Classification**: Support for mainnet, preprod, preview, custom networks
- **Application Typing**: Block producer, relay, monitoring classifications
- **Hierarchical Naming**: CRD names follow `{network}-{pool-short}-{region}` pattern

### 📊 **Enhanced Observability**
- **Multi-Dimensional Metrics**: All metrics labeled with network, pool, application
- **Pool-Specific Dashboards**: Grafana filtering by network and pool
- **Isolated Health Checks**: Health endpoints scoped per pool
- **Comprehensive Status**: CRD status includes network and pool information

### 🔄 **Backward Compatibility**
- **Legacy Support**: Existing single-cluster deployments work unchanged
- **Gradual Migration**: Can migrate from single-pool to multi-pool incrementally
- **Default Fallback**: Missing multi-tenant config falls back to legacy behavior

## 🏗️ Implementation Components

### 1. Enhanced CRD Schema (`cardano-forge-cluster-multi-tenant-crd.yaml`)

```yaml
spec:
  network:
    name: mainnet    # Network classification
    magic: 764824073 # Network magic validation
  pool:
    id: pool1abcd...xyz      # Pool bech32 ID
    idHex: abcd...xyz        # Pool hex ID
    ticker: PRIME            # Pool ticker
  application:
    type: block-producer     # Application type
    environment: production  # Environment classification
```

**Key Features:**
- Comprehensive validation for pool IDs and network magic
- Multi-dimensional status tracking
- Rich metadata labeling for Kubernetes operations

### 2. Updated Cluster Manager (`src/cluster_manager.py`)

**New Capabilities:**
- Pool ID validation (bech32 and hex formats)
- Network magic validation for known networks
- Multi-tenant cluster name generation
- Pool-scoped lease names
- Enhanced CRD creation with multi-tenant metadata

**Example Usage:**
```python
# Environment variables enable multi-tenant mode
CARDANO_NETWORK=mainnet
POOL_ID=pool1abcd...xyz
POOL_TICKER=PRIME

# Results in:
cluster_name = "mainnet-pool1abcd-us-east-1"
lease_name = "cardano-leader-mainnet-pool1abcd"
```

### 3. Enhanced Forge Manager (`src/forgemanager.py`)

**Multi-Tenant Metrics:**
```prometheus
cardano_forging_enabled{pod="cardano-bp-0", network="mainnet", pool_id="pool1abcd", application="block-producer"} 1
cardano_cluster_forge_enabled{cluster="mainnet-pool1abcd-us-east-1", network="mainnet", pool_id="pool1abcd"} 1
```

**Enhanced Info Metric:**
```prometheus
cardano_forge_manager_info{pod_name="cardano-bp-0", network="mainnet", pool_id="pool1abcd", pool_ticker="PRIME", application_type="block-producer", version="2.0.0"} 1
```

## 📋 Deployment Patterns

### Pattern 1: Multi-Network Single Pool
Run the same pool across different networks for testing:
- `mainnet-pool1abcd-us-east-1` (production)
- `preprod-pool1abcd-us-east-1` (testing)
- `preview-pool1abcd-us-east-1` (development)

### Pattern 2: Multi-Pool Single Network
Run multiple pools on the same network:
- `mainnet-pool1abcd-us-east-1` (primary pool)
- `mainnet-pool1efgh-us-east-1` (secondary pool)
- `mainnet-pool1ijkl-us-east-1` (tertiary pool)

### Pattern 3: Mixed Multi-Tenant
Combined approach with multiple pools and networks:
- `mainnet-pool1abcd-us-east-1` (primary production)
- `mainnet-pool1efgh-us-east-1` (secondary production)
- `preprod-pool1abcd-us-east-1` (testing)

## 🛠️ Configuration Examples

### Environment Variables (Multi-Tenant)
```bash
# Network identification
CARDANO_NETWORK=mainnet
NETWORK_MAGIC=764824073

# Pool identification
POOL_ID=pool1abcd...xyz
POOL_ID_HEX=abcd...xyz
POOL_NAME="My Stake Pool"
POOL_TICKER=MYPOOL

# Application classification
APPLICATION_TYPE=block-producer

# Cluster management (enables multi-tenant mode)
ENABLE_CLUSTER_MANAGEMENT=true
CLUSTER_REGION=us-east-1
CLUSTER_PRIORITY=1

# Pool-specific secrets
SOURCE_KES_KEY=/secrets/mainnet-pool1abcd/kes.skey
SOURCE_VRF_KEY=/secrets/mainnet-pool1abcd/vrf.skey
SOURCE_OP_CERT=/secrets/mainnet-pool1abcd/node.cert

# Pool-scoped lease
LEASE_NAME=cardano-leader-mainnet-pool1abcd
```

### StatefulSet Labels (Multi-Tenant)
```yaml
labels:
  app: cardano-bp
  cardano.io/network: mainnet
  cardano.io/pool-id: pool1abcd...xyz
  cardano.io/pool-ticker: PRIME
  cardano.io/application: block-producer
```

## 🚀 Migration Guide

### Step 1: Assess Current Deployment
```bash
# Check existing deployment
kubectl get statefulsets -l app=cardano-bp
kubectl get secrets -l app=cardano-bp
kubectl get configmaps -l app=cardano-bp
```

### Step 2: Prepare Multi-Tenant Secrets
```bash
# Create pool-specific secrets
kubectl create secret generic mainnet-pool1abcd-credentials \
  --from-file=kes.skey=/path/to/pool1abcd/kes.skey \
  --from-file=vrf.skey=/path/to/pool1abcd/vrf.skey \
  --from-file=node.cert=/path/to/pool1abcd/node.cert
```

### Step 3: Install Multi-Tenant CRD
```bash
# Install enhanced CRD
kubectl apply -f k8s/cardano-forge-cluster-multi-tenant-crd.yaml
```

### Step 4: Deploy Multi-Tenant Configuration
```bash
# Deploy with multi-tenant configuration
helm install my-pools ./cardano-forge-manager \
  --namespace spo-operations \
  --create-namespace \
  --values examples/multi-tenant-helm-values.yaml
```

### Step 5: Verify Multi-Tenant Operation
```bash
# Check CRDs
kubectl get cardanoforgeclusters -o wide

# Check metrics
curl http://prometheus:9090/api/v1/query?query=cardano_forging_enabled

# Check logs
kubectl logs -l app=cardano-bp -c forge-manager
```

## 📊 Operational Commands

### Query Multi-Tenant CRDs
```bash
# List all forge clusters
kubectl get cfc

# Filter by network
kubectl get cfc -l cardano.io/network=mainnet

# Filter by pool
kubectl get cfc -l cardano.io/pool-ticker=PRIME

# Get detailed status
kubectl describe cfc mainnet-pool1abcd-us-east-1
```

### Multi-Tenant Metrics Queries
```promql
# Forging status by network
sum by (network) (cardano_forging_enabled)

# Forging status by pool
cardano_forging_enabled{pool_id="pool1abcd"}

# Cluster-wide forge status
cardano_cluster_forge_enabled

# Leadership changes by pool
rate(cardano_leadership_changes_total[5m])
```

### Debugging Multi-Tenant Issues
```bash
# Check pool ID validation
kubectl logs -l cardano.io/pool-id=pool1abcd -c forge-manager | grep -i "pool.*validation"

# Check network magic validation
kubectl logs -l cardano.io/network=mainnet -c forge-manager | grep -i "network.*magic"

# Check lease conflicts
kubectl get leases | grep cardano-leader

# Check CRD creation
kubectl get events | grep CardanoForgeCluster
```

## ⚠️ Important Considerations

### Security Isolation
- **Secret Separation**: Each pool MUST have its own Kubernetes secrets
- **Network Policies**: Consider implementing network policies for additional isolation
- **RBAC Scoping**: Service accounts should have minimal required permissions

### Resource Management
- **Resource Quotas**: Set appropriate resource quotas per namespace/pool
- **Storage Classes**: Use appropriate storage classes for different environments
- **Node Affinity**: Consider node affinity to separate production and testing workloads

### Monitoring and Alerting
- **Pool-Specific Alerts**: Create alerts scoped to specific pools and networks
- **Cross-Pool Correlation**: Monitor for unexpected correlations between isolated pools
- **Health Check Endpoints**: Ensure health checks are properly scoped per pool

### Operational Procedures
- **Failover Testing**: Test failover procedures for each pool independently
- **Backup Strategy**: Implement pool-specific backup strategies
- **Credential Rotation**: Plan for pool-specific credential rotation procedures

## 🎯 Validation Checklist

### Multi-Tenant Isolation ✅
- [ ] Pools on the same network operate independently
- [ ] Cross-network deployments do not interfere
- [ ] Pool ID validation prevents invalid configurations
- [ ] CRD names include network and pool identifiers
- [ ] Metrics include proper network and pool labels

### Configuration Management ✅
- [ ] Environment variables support network and pool specification
- [ ] Secrets are properly scoped per pool
- [ ] Health check endpoints are pool-specific
- [ ] Resource conflicts are prevented automatically

### Operational Safety ✅
- [ ] Leadership election is scoped to network + pool
- [ ] Cross-pool leader election is impossible
- [ ] Network magic validation prevents misconfigurations
- [ ] Pool ID changes trigger appropriate warnings/errors

### Backward Compatibility ✅
- [ ] Existing single-pool deployments continue to work
- [ ] Migration path from single-pool to multi-pool is clear
- [ ] Default values maintain current behavior
- [ ] Breaking changes are clearly documented

---

## 🎉 Summary

The multi-tenant implementation provides SPOs with:

- **Complete Isolation**: Run multiple pools and networks safely in the same cluster
- **Operational Flexibility**: Independent management of different pools and environments
- **Enhanced Observability**: Detailed metrics and monitoring per pool and network
- **Seamless Migration**: Backward compatibility with existing deployments
- **Production Ready**: Comprehensive validation, error handling, and operational procedures

This implementation enables SPOs to consolidate their infrastructure while maintaining the isolation and safety required for production block producer operations across multiple Cardano networks and stake pools.