# Cardano Node Helm Chart - Implementation TODO

## Completed ✅

1. **Directory Structure** - Created charts/cardano-node with templates/, values/, examples/ directories
2. **Chart.yaml** - Complete chart metadata with dependencies on cardano-forge-crds
3. **values.yaml** - Comprehensive configuration file with:
   - Cardano node configuration
   - Forge Manager v2.0 settings (cluster management, multi-tenant)
   - Mithril signer configuration
   - Submit API configuration  
   - Storage, resources, networking
   - Full parameterization of all features

## Remaining Work 🚧

### Critical Templates (Required for Chart to Function)

1. **templates/_helpers.tpl** - Template helper functions
   - Standard Helm helpers (name, fullname, labels, etc.)
   - Forge manager naming conventions (multi-tenant aware)
   - Pool ID short form function
   - Lease name generation
   - CRD name generation

2. **templates/statefulset.yaml** - Main StatefulSet resource
   - Cardano node container configuration
   - Forge manager v2.0 sidecar with all environment variables:
     - Multi-tenant config (CARDANO_NETWORK, POOL_ID, etc.)
     - Cluster management (ENABLE_CLUSTER_MANAGEMENT, CLUSTER_REGION, etc.)
     - Health check configuration
   - Init containers for setup
   - Optional Mithril signer sidecar
   - Optional Submit API sidecar
   - Volume mounts (data, config, secrets, socket)
   - Health probes

3. **templates/configmap.yaml** - Cardano node configuration
   - config.json template
   - Topology JSON template  
   - Genesis file URLs/content

4. **templates/service.yaml** - Kubernetes Services
   - P2P service (LoadBalancer)
   - Metrics service
   - Forge manager metrics service
   - Submit API service (if enabled)
   - Mithril service (if enabled)

5. **templates/serviceaccount.yaml** - Service Account
   - Basic service account for cardano-node pods

6. **templates/rbac.yaml** - RBAC Resources
   - Role with permissions for:
     - coordination.k8s.io/leases (get, list, watch, create, update, patch, delete)
     - cardano.io/cardanoleaders (get, list, watch, create, update, patch)
     - cardano.io/cardanoforgeclusters (get, list, watch, create, update, patch)
   - RoleBinding

7. **templates/cardanoleader.yaml** - CardanoLeader CR instance
   - Only created if forgeManager.enabled: true
   - Respects legacy.crd.cardanoLeader settings

8. **templates/cardanoforgeCluster.yaml** - CardanoForgeCluster CR instance
   - Only created if clusterManagement.enabled: true
   - Includes all spec fields (network, pool, region, priority, healthCheck, override)

9. **templates/pvc.yaml** - PersistentVolumeClaim
   - Data volume for cardano-node
   - Respects persistence settings

### Optional Templates (Nice to Have)

10. **templates/secret.yaml** - Secrets template
    - Only if secrets.create: true (for testing)
    - Base64 decode and mount keys

11. **templates/servicemonitor.yaml** - Prometheus ServiceMonitor
    - For Prometheus Operator integration
    - Only if monitoring.serviceMonitor.enabled

12. **templates/ingress.yaml** - Ingress resource
    - For Submit API external access
    - Only if ingress.enabled

13. **templates/networkpolicy.yaml** - Network Policy
    - Only if networkPolicy.enabled

### Example Values Files

14. **values/single-cluster-block-producer.yaml**
    - Single cluster BP with forge manager
    - No cluster management
    - 3 replicas for HA

15. **values/multi-cluster-us-east-1.yaml**
    - Multi-cluster deployment example
    - Priority 1 (primary)
    - Health check enabled
    - Full cluster management config

16. **values/multi-cluster-eu-west-1.yaml**
    - Multi-cluster deployment example
    - Priority 2 (secondary)
    - Health check enabled

17. **values/multi-tenant-pool1.yaml**
    - Multi-tenant example (pool 1)
    - Separate namespace/lease/CRD names

18. **values/multi-tenant-pool2.yaml**
    - Multi-tenant example (pool 2)
    - Demonstrates isolation

19. **values/relay-node.yaml**
    - Simple relay node
    - No forge manager
    - Public topology

20. **values/preview-testnet.yaml**
    - Preview testnet configuration
    - Updated genesis files
    - Different network magic

### Documentation

21. **README.md** - Comprehensive chart documentation
    - Overview and features
    - Quick start guide
    - Installation instructions
    - Configuration reference
    - Multi-cluster setup guide
    - Multi-tenant setup guide
    - Upgrade guide
    - Troubleshooting
    - Examples

22. **examples/README.md** - Examples documentation
    - Links to example values
    - Explanation of each scenario

### Testing

23. **Test chart installation**
    ```bash
    helm dependency build charts/cardano-node
    helm template test charts/cardano-node
    helm lint charts/cardano-node
    ```

24. **Test with example values**
    ```bash
    helm template test charts/cardano-node -f values/single-cluster-block-producer.yaml
    helm template test charts/cardano-node -f values/multi-cluster-us-east-1.yaml
    ```

## Implementation Priority

### Phase 1: Core Functionality (MVP)
- [ ] _helpers.tpl
- [ ] statefulset.yaml
- [ ] configmap.yaml
- [ ] service.yaml
- [ ] serviceaccount.yaml
- [ ] rbac.yaml
- [ ] pvc.yaml
- [ ] Basic README.md

### Phase 2: CR Instances
- [ ] cardanoleader.yaml
- [ ] cardanoforgeCluster.yaml

### Phase 3: Example Values
- [ ] single-cluster-block-producer.yaml
- [ ] multi-cluster-us-east-1.yaml
- [ ] relay-node.yaml

### Phase 4: Optional Features
- [ ] secret.yaml
- [ ] servicemonitor.yaml
- [ ] ingress.yaml
- [ ] networkpolicy.yaml

### Phase 5: Complete Documentation
- [ ] Full README.md
- [ ] All example values files
- [ ] examples/README.md

## Key Template Considerations

### Helper Functions Needed

```yaml
{{- define "cardano-node.name" -}}
{{- define "cardano-node.fullname" -}}
{{- define "cardano-node.chart" -}}
{{- define "cardano-node.labels" -}}
{{- define "cardano-node.selectorLabels" -}}
{{- define "cardano-node.serviceAccountName" -}}
{{- define "cardano-node.forgingKeysSecretName" -}}

# Multi-tenant aware helpers
{{- define "cardano-node.poolShortId" -}}
{{- define "cardano-node.leaseName" -}}
{{- define "cardano-node.cardanoLeaderName" -}}
{{- define "cardano-node.cardanoForgeClusterName" -}}
```

### Environment Variables for Forge Manager v2.0

Must include in StatefulSet:
- Basic: NAMESPACE, POD_NAME, NODE_SOCKET, METRICS_PORT
- Credentials: SOURCE_*, TARGET_* keys
- Lease: LEASE_NAME, LEASE_DURATION
- CRD: CRD_GROUP, CRD_VERSION, CRD_PLURAL, CRD_NAME
- Multi-tenant: CARDANO_NETWORK, NETWORK_MAGIC, POOL_ID, POOL_TICKER
- Cluster mgmt: ENABLE_CLUSTER_MANAGEMENT, CLUSTER_REGION, CLUSTER_PRIORITY
- Health check: HEALTH_CHECK_ENDPOINT, HEALTH_CHECK_INTERVAL

## Notes

- The chart should work with or without forge manager
- Backward compatibility with legacy CardanoLeader CRD
- Forward compatibility with new CardanoForgeCluster CRD
- Multi-tenant mode should be opt-in
- Cluster management should be opt-in
- All CRDs should be managed by the dependency chart
- Genesis files should be downloaded in init container (like original chart)

## References

- Original chart: ~/git/mainline/kubernetes/deploy/cardano-node/helm/cardano-node
- Forge manager docs: /home/cascadura/git/cardano-forge-manager/helm-charts/docs/
- CRD chart: /home/cascadura/git/cardano-forge-manager/helm-charts/charts/cardano-forge-crds/
