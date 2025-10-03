# Cardano Node Helm Chart - Installation Guide

## Prerequisites

- Kubernetes 1.29+ (for native sidecar support)
- Helm 3.x
- Storage provisioner capable of creating PersistentVolumes
- `kubectl` configured with cluster access
- (Optional) Prometheus Operator for ServiceMonitor support

## Important: CRD Installation

**⚠️ CRITICAL**: Custom Resource Definitions (CRDs) are cluster-scoped and must be installed **ONCE per cluster** before deploying any cardano-node instances.

### Why Install CRDs Separately?

CRDs are shared across all namespaces and pools. Installing them as part of each Helm release would cause ownership conflicts when deploying:
- Multiple pools in the same cluster (multi-tenant)
- Multiple releases for testing
- Upgrading or reinstalling charts

## Step-by-Step Installation

### Step 1: Install CRDs (Once Per Cluster)

Install the CRDs in a dedicated namespace:

```bash
helm install cardano-forge-crds charts/cardano-forge-crds \
  --namespace cardano-system \
  --create-namespace
```

**Verify CRD Installation:**
```bash
kubectl get crd | grep cardano
# Expected output:
# cardanoforgeclusters.cardano.io
# cardanoleaders.cardano.io
```

**Check CRD Details:**
```bash
kubectl get crd cardanoleaders.cardano.io -o yaml
kubectl get crd cardanoforgeclusters.cardano.io -o yaml
```

### Step 2: Create Namespace for Your Deployment

```bash
# For mainnet block producer
kubectl create namespace cardano-mainnet

# For multi-tenant deployment
kubectl create namespace cardano-multi-tenant

# For testnet
kubectl create namespace cardano-preprod
```

### Step 3: Create Forging Keys Secret (Block Producers Only)

For block producer deployments, create a secret with your forging keys:

```bash
kubectl create secret generic mainnet-forging-keys \
  --from-file=kes.skey=path/to/kes.skey \
  --from-file=vrf.skey=path/to/vrf.skey \
  --from-file=node.cert=path/to/node.cert \
  --namespace cardano-mainnet
```

**Verify Secret:**
```bash
kubectl get secret mainnet-forging-keys -n cardano-mainnet
kubectl describe secret mainnet-forging-keys -n cardano-mainnet
```

### Step 4: Deploy Cardano Node

Choose your deployment scenario:

#### Scenario A: Single-Cluster Block Producer

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set forgeManager.secretName=mainnet-forging-keys \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml
```

#### Scenario B: Multi-Cluster Block Producer (Primary)

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set forgeManager.secretName=mainnet-forging-keys \
  -f charts/cardano-node/values/multi-cluster-us-east-1.yaml
```

Deploy the secondary cluster in another region:

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set forgeManager.secretName=mainnet-forging-keys \
  -f charts/cardano-node/values/multi-cluster-eu-west-1.yaml
```

#### Scenario C: Multi-Tenant (Multiple Pools in Same Cluster)

**Pool 1:**
```bash
# Create secret for Pool 1
kubectl create secret generic pool1-forging-keys \
  --from-file=kes.skey=path/to/pool1/kes.skey \
  --from-file=vrf.skey=path/to/pool1/vrf.skey \
  --from-file=node.cert=path/to/pool1/node.cert \
  --namespace cardano-multi-tenant

# Deploy Pool 1
helm install cardano-pool1 charts/cardano-node \
  --namespace cardano-multi-tenant \
  --set forgeManager.secretName=pool1-forging-keys \
  -f charts/cardano-node/values/multi-tenant-pool1.yaml
```

**Pool 2:**
```bash
# Create secret for Pool 2
kubectl create secret generic pool2-forging-keys \
  --from-file=kes.skey=path/to/pool2/kes.skey \
  --from-file=vrf.skey=path/to/pool2/vrf.skey \
  --from-file=node.cert=path/to/pool2/node.cert \
  --namespace cardano-multi-tenant

# Deploy Pool 2
helm install cardano-pool2 charts/cardano-node \
  --namespace cardano-multi-tenant \
  --set forgeManager.secretName=pool2-forging-keys \
  -f charts/cardano-node/values/multi-tenant-pool2.yaml
```

#### Scenario D: Relay Node

```bash
helm install cardano-relay charts/cardano-node \
  --namespace cardano-mainnet \
  -f charts/cardano-node/values/relay-node.yaml
```

#### Scenario E: Testnet (Preprod)

```bash
# Create secret
kubectl create secret generic preprod-forging-keys \
  --from-file=kes.skey=path/to/preprod/kes.skey \
  --from-file=vrf.skey=path/to/preprod/vrf.skey \
  --from-file=node.cert=path/to/preprod/node.cert \
  --namespace cardano-preprod

# Deploy
helm install cardano-preprod charts/cardano-node \
  --namespace cardano-preprod \
  --set forgeManager.secretName=preprod-forging-keys \
  -f charts/cardano-node/values/testnet-preprod.yaml
```

## Verification

### Check Pod Status

```bash
kubectl get pods -n cardano-mainnet
# Expected: cardano-producer-0, cardano-producer-1, cardano-producer-2 (Running)
```

### Check Leader Election

```bash
# Check CardanoLeader CRD
kubectl get cardanoleaders -n cardano-mainnet
kubectl describe cardanoleader -n cardano-mainnet

# For multi-cluster, check CardanoForgeCluster CRD
kubectl get cardanoforgeclusters
kubectl get cardanoforgeclusters -o wide
```

### Check Services

```bash
kubectl get svc -n cardano-mainnet
```

### Check Logs

```bash
# Cardano node logs
kubectl logs -f cardano-producer-0 -c cardano-node -n cardano-mainnet

# Forge Manager logs
kubectl logs -f cardano-producer-0 -c cardano-forge-manager -n cardano-mainnet

# All containers
kubectl logs -f cardano-producer-0 --all-containers -n cardano-mainnet
```

### Check Metrics

```bash
# Port forward metrics endpoint
kubectl port-forward svc/cardano-producer-forge-metrics 8000:8000 -n cardano-mainnet

# Query metrics (in another terminal)
curl localhost:8000/metrics | grep cardano_forging_enabled
curl localhost:8000/metrics | grep cardano_leader_status
```

## Upgrading

### Upgrade the Chart

```bash
helm upgrade cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --reuse-values
```

### Upgrade CRDs (If Needed)

⚠️ **Warning**: Upgrading CRDs affects all deployments using them.

```bash
helm upgrade cardano-forge-crds charts/cardano-forge-crds \
  --namespace cardano-system
```

## Uninstallation

### Remove a Deployment

```bash
helm uninstall cardano-producer -n cardano-mainnet
```

### Remove CRDs (Optional - Be Careful!)

⚠️ **WARNING**: This will delete ALL CardanoLeader and CardanoForgeCluster resources in the cluster!

```bash
helm uninstall cardano-forge-crds -n cardano-system

# Or manually:
kubectl delete crd cardanoleaders.cardano.io
kubectl delete crd cardanoforgeclusters.cardano.io
```

### Remove Namespace

```bash
kubectl delete namespace cardano-mainnet
```

## Troubleshooting

### Issue: CRD Ownership Conflict

**Error Message:**
```
Error: Unable to continue with install: CustomResourceDefinition "cardanoforgeclusters.cardano.io" 
exists and cannot be imported into the current release: invalid ownership metadata
```

**Solution:**
This happens when CRDs were installed with a previous release. The CRDs should be installed separately:

```bash
# Option 1: Install CRDs separately (recommended)
helm install cardano-forge-crds charts/cardano-forge-crds \
  --namespace cardano-system --create-namespace

# Then deploy without CRD subchart (default behavior)
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml
```

### Issue: CRDs Not Found

**Error Message:**
```
Error: unable to recognize "": no matches for kind "CardanoLeader"
```

**Solution:**
Install the CRDs first:

```bash
helm install cardano-forge-crds charts/cardano-forge-crds \
  --namespace cardano-system --create-namespace
```

### Issue: Pod Not Starting

```bash
# Check pod status
kubectl describe pod cardano-producer-0 -n cardano-mainnet

# Check events
kubectl get events -n cardano-mainnet --sort-by='.lastTimestamp'

# Check init container logs
kubectl logs cardano-producer-0 -c init-cardano-setup -n cardano-mainnet
```

### Issue: Forging Keys Secret Not Found

```bash
# Verify secret exists
kubectl get secret mainnet-forging-keys -n cardano-mainnet

# Create if missing
kubectl create secret generic mainnet-forging-keys \
  --from-file=kes.skey=path/to/kes.skey \
  --from-file=vrf.skey=path/to/vrf.skey \
  --from-file=node.cert=path/to/node.cert \
  --namespace cardano-mainnet
```

### Issue: Leader Election Not Working

```bash
# Check lease
kubectl get lease -n cardano-mainnet
kubectl describe lease cardano-leader-mainnet-... -n cardano-mainnet

# Check RBAC permissions
kubectl auth can-i get leases --as=system:serviceaccount:cardano-mainnet:cardano-producer-cardano-node -n cardano-mainnet
kubectl auth can-i update leases --as=system:serviceaccount:cardano-mainnet:cardano-producer-cardano-node -n cardano-mainnet
```

## Common Configuration Overrides

### Change Resource Limits

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set resources.cardanoNode.requests.cpu=4000m \
  --set resources.cardanoNode.requests.memory=32Gi \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml
```

### Change Storage Size

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set persistence.size=500Gi \
  --set persistence.storageClass=fast-ssd \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml
```

### Enable ServiceMonitor

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set monitoring.serviceMonitor.enabled=true \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml
```

### Enable PodDisruptionBudget

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set podDisruptionBudget.enabled=true \
  --set podDisruptionBudget.minAvailable=2 \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml
```

### Enable NetworkPolicy

```bash
helm install cardano-producer charts/cardano-node \
  --namespace cardano-mainnet \
  --set networkPolicy.enabled=true \
  -f charts/cardano-node/values/single-cluster-block-producer.yaml
```

## Best Practices

1. **CRDs First**: Always install CRDs separately before any cardano-node deployments
2. **Secrets Management**: Use external secret management (Vault, Sealed Secrets, etc.) for production
3. **Resource Limits**: Set appropriate resource limits based on your workload
4. **Storage**: Use fast SSD storage for mainnet (400Gi+ recommended)
5. **High Availability**: Deploy 3+ replicas for block producers
6. **PodDisruptionBudget**: Enable for production to ensure availability during updates
7. **Monitoring**: Enable ServiceMonitor if using Prometheus Operator
8. **NetworkPolicy**: Enable for enhanced security in production
9. **Backup**: Regularly backup your forging keys and operational certificates
10. **Testing**: Test deployments on testnet (preprod/preview) before mainnet

## Quick Reference

### Install Order
1. ✅ Install CRDs (once per cluster)
2. ✅ Create namespace
3. ✅ Create secrets (block producers only)
4. ✅ Deploy cardano-node chart

### Multi-Pool Deployment Order
1. ✅ Install CRDs (once)
2. ✅ Create multi-tenant namespace
3. ✅ Deploy Pool 1
4. ✅ Deploy Pool 2
5. ✅ Verify isolation

### Multi-Cluster Deployment Order
1. ✅ Install CRDs in each cluster
2. ✅ Deploy primary cluster (priority 1)
3. ✅ Deploy secondary cluster (priority 2)
4. ✅ Verify cross-cluster coordination

## Support

For issues and questions:
- **Documentation**: `charts/cardano-node/README.md`
- **Examples**: `charts/cardano-node/values/*.yaml`
- **Project Guide**: Root `WARP.md`
- **GitHub Issues**: [cardano-forge-manager](https://github.com/your-org/cardano-forge-manager)

---

**Last Updated**: 2025-10-02  
**Chart Version**: 0.1.0  
**Tested With**: Kubernetes 1.29+, Helm 3.14+
