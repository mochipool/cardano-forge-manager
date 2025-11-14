# Cardano Forge Manager Helm Charts

This repository contains Helm charts for deploying Cardano Forge Manager and related components.

## Charts

- **cardano-forge-crds** - Custom Resource Definitions for cluster-wide forge coordination
- **cardano-node** - Cardano block producer node with integrated Forge Manager sidecar

## ⚠️ Important: Installation Order

**The CRDs MUST be installed before deploying any cardano-node instances!**

The `cardano-forge-crds` chart contains cluster-scoped Custom Resource Definitions that the Forge Manager requires. If you attempt to install `cardano-node` without the CRDs, the deployment will fail.

### Installation Order:
1. ✅ Install `cardano-forge-crds` first
2. ✅ Then install `cardano-node`

### Uninstallation Order:
1. ✅ Uninstall all `cardano-node` deployments first
2. ✅ Then uninstall `cardano-forge-crds` last

⚠️ **Warning**: Uninstalling the CRDs chart will delete all `CardanoForgeCluster` and `CardanoLeader` resources in your cluster!

## Installation

### Add the Helm Repository

```bash
helm repo add cardano-forge https://mochipool.github.io/cardano-forge-manager
helm repo update
```

### Step 1: Install CRDs (Required First)

⚠️ **This step is mandatory and must be completed before installing any cardano-node instances!**

```bash
helm install cardano-forge-crds cardano-forge/cardano-forge-crds \
  --namespace cardano-system \
  --create-namespace
```

Verify the CRDs are installed:

```bash
kubectl get crd | grep cardano
# Should show:
# cardanoforgeclusters.cardano.io
# cardanoleaders.cardano.io
```

### Step 2: Install Cardano Node

```bash
# Create a values file with your configuration
cat > my-pool-values.yaml <<EOF
cardanoNode:
  network: mainnet
  
pool:
  id: pool1your_pool_id_here
  ticker: POOL
  
forgeManager:
  clusterManagement:
    enabled: true
    region: us-east-1
    priority: 1

# Add your secrets configuration here
secrets:
  kesKey: |
    <your-kes-key>
  vrfKey: |
    <your-vrf-key>
  opCert: |
    <your-op-cert>
EOF

# Install the chart
helm install my-pool cardano-forge/cardano-node \
  --namespace cardano-mainnet \
  --create-namespace \
  -f my-pool-values.yaml
```

## Upgrading

```bash
helm repo update
helm upgrade cardano-forge-crds cardano-forge/cardano-forge-crds \
  --namespace cardano-system

helm upgrade my-pool cardano-forge/cardano-node \
  --namespace cardano-mainnet \
  -f my-pool-values.yaml
```

## Uninstallation

⚠️ **Important**: Uninstall in the reverse order of installation!

### Step 1: Remove All Cardano Node Deployments First

Remove all cardano-node deployments from all namespaces before removing the CRDs:

```bash
# List all cardano-node releases
helm list -A | grep cardano-node

# Uninstall each one
helm uninstall my-pool --namespace cardano-mainnet
helm uninstall my-other-pool --namespace cardano-preprod
# ... repeat for all pools
```

### Step 2: Verify All Cardano Resources Are Removed

```bash
# Check that no CardanoForgeCluster resources remain
kubectl get cardanoforgeclusters -A

# Check that no CardanoLeader resources remain  
kubectl get cardanoleaders -A
```

### Step 3: Remove the CRDs (Last Step)

⚠️ **Warning**: This will permanently delete all `CardanoForgeCluster` and `CardanoLeader` custom resources in your cluster!

```bash
helm uninstall cardano-forge-crds --namespace cardano-system
```

If you have orphaned resources that won't delete, you may need to manually remove finalizers:

```bash
# Remove any stuck resources (use with caution)
kubectl patch cardanoforgeCluster <resource-name> -p '{"metadata":{"finalizers":[]}}' --type=merge
kubectl patch cardanoleader <resource-name> -p '{"metadata":{"finalizers":[]}}' --type=merge
```

## Development

### Local Testing

To test charts locally without publishing:

```bash
# Install CRDs from local chart
helm install cardano-forge-crds ./charts/cardano-forge-crds \
  --namespace cardano-system \
  --create-namespace

# Update dependencies for cardano-node chart
helm dependency update ./charts/cardano-node

# Install cardano-node from local chart
helm install my-pool ./charts/cardano-node \
  --namespace cardano-mainnet \
  --create-namespace \
  -f my-values.yaml
```

### Linting

```bash
helm lint charts/cardano-forge-crds
helm lint charts/cardano-node
```

## Documentation

For detailed documentation, see:
- [Main Documentation](../docs/)
- [WARP.md](../WARP.md) - Development guide
- [Chart Values](./cardano-node/README.md) - Configuration options

## Support

- Issues: https://github.com/mochipool/cardano-forge-manager/issues
- Source: https://github.com/mochipool/cardano-forge-manager
