# Cardano Node Helm Chart - Development Status

## ✅ Completed Components

### Core Templates (100% Complete)

#### Kubernetes Resources
- [x] **StatefulSet** (`templates/statefulset.yaml`)
  - Cardano node container with configurable command-line arguments
  - Forge Manager v2.0 sidecar (native sidecar pattern, K8s 1.29+)
  - Init container for setup and configuration
  - Mithril snapshot restore support (optional)
  - Submit API sidecar (optional)
  - Mithril signer sidecar (optional)
  - Proper volume mounts and configuration management
  - Health checks (liveness and readiness probes)
  - Pod-level process namespace sharing for SIGHUP signaling

- [x] **Services** (`templates/service.yaml`)
  - P2P service (LoadBalancer/ClusterIP/NodePort)
  - Headless service for StatefulSet
  - Forge Manager metrics service (ClusterIP)
  - Submit API service (optional)
  - Proper port configurations and annotations

- [x] **ConfigMap** (`templates/configmap.yaml`)
  - Cardano node configuration (config.json)
  - Topology configuration (topology.json)
  - Network-specific configurations (mainnet, preprod, preview)
  - P2P and genesis file references

- [x] **RBAC** (`templates/rbac.yaml`)
  - ClusterRole for Forge Manager
  - Permissions for leases (leader election)
  - Permissions for CardanoLeader CRD (legacy)
  - Permissions for CardanoForgeCluster CRD (multi-cluster)

- [x] **ServiceAccount** (`templates/serviceaccount.yaml`)
  - Service account for pods
  - Proper RBAC binding

- [x] **PersistentVolumeClaim** (`templates/pvc.yaml`)
  - Optional standalone PVC template
  - Support for existing claims
  - VolumeClaimTemplates in StatefulSet

#### Custom Resource Definitions
- [x] **CardanoLeader CRD** (`templates/cardanoleader.yaml`)
  - Local leader status tracking (legacy)
  - Conditional creation based on Forge Manager config

- [x] **CardanoForgeCluster CRD** (`templates/cardanoforgecluster.yaml`)
  - Multi-cluster coordination
  - Priority-based forge management
  - Health check integration
  - Override support for maintenance

#### Monitoring & Observability
- [x] **ServiceMonitor** (`templates/servicemonitor.yaml`)
  - Prometheus Operator integration
  - Cardano node metrics endpoint
  - Forge Manager metrics endpoint
  - Configurable scrape intervals and relabelings

- [x] **PodDisruptionBudget** (`templates/poddisruptionbudget.yaml`)
  - High availability support
  - Controlled pod disruptions
  - Configurable min/max unavailable

- [x] **NetworkPolicy** (`templates/networkpolicy.yaml`)
  - Pod-level network security
  - P2P traffic rules
  - Metrics scraping rules
  - Kubernetes API access for Forge Manager
  - Health check endpoint access

- [x] **HorizontalPodAutoscaler** (`templates/hpa.yaml`)
  - Automatic scaling for relay nodes only
  - CPU and memory-based metrics
  - Custom metrics support
  - Safety check to prevent use with block producers

#### Helpers
- [x] **Helper Functions** (`templates/_helpers.tpl`)
  - Chart name and labels
  - Selector labels
  - Service account name
  - Multi-tenant helpers
  - Cluster management helpers
  - Network magic lookup
  - Byron genesis URL generation
  - Validation functions

### Example Values Files (100% Complete)

- [x] **Single-Cluster Block Producer** (`values/single-cluster-producer.yaml`)
  - Basic HA deployment with 3 replicas
  - Local leader election only
  - No cluster management
  - Production-ready resource requests

- [x] **Multi-Cluster Primary** (`values/multi-cluster-primary.yaml`)
  - Primary region (priority 1)
  - Cluster management enabled
  - Health check integration
  - Multi-tenant configuration
  - Full monitoring stack

- [x] **Multi-Cluster Secondary** (`values/multi-cluster-secondary.yaml`)
  - Secondary/failover region (priority 2)
  - Same pool configuration as primary
  - Automatic takeover on primary failure
  - Moderate resource allocation

- [x] **Relay Node** (`values/relay-node.yaml`)
  - No Forge Manager
  - No forging credentials
  - Mithril snapshot enabled
  - Lower resource requirements
  - Single replica (scalable)

- [x] **Multi-Tenant Pool 1** (`values/multi-tenant-pool1.yaml`)
  - First pool in multi-tenant setup
  - Unique pool identifier
  - Isolated leader election
  - Complete deployment instructions

- [x] **Multi-Tenant Pool 2** (`values/multi-tenant-pool2.yaml`)
  - Second pool demonstrating isolation
  - Different pool ID and ticker
  - Independent operation
  - Notes on combining with cluster management

- [x] **Testnet Preprod** (`values/testnet-preprod.yaml`)
  - Reduced resource requirements
  - Mithril fast sync
  - Debug logging
  - 2 replicas for cost efficiency
  - Development-friendly settings

### Documentation (100% Complete)

- [x] **Chart README** (`README.md`)
  - Comprehensive feature list
  - Installation instructions
  - Configuration examples
  - Architecture diagrams
  - Deployment scenarios
  - Monitoring guide
  - Operational tasks
  - Troubleshooting guide
  - Security considerations
  - Upgrade procedures

- [x] **Main values.yaml**
  - Extensive inline documentation
  - All configuration options
  - Sensible defaults
  - Multi-tenant support
  - Cluster management support

## 📊 Feature Matrix

| Feature | Status | Notes |
|---------|--------|-------|
| Block Producer Mode | ✅ | Fully supported with Forge Manager |
| Relay Mode | ✅ | Simplified deployment without credentials |
| Single-Cluster HA | ✅ | Kubernetes Lease-based leader election |
| Multi-Cluster Coordination | ✅ | Priority-based with health checks |
| Multi-Tenant Support | ✅ | Multiple pools per cluster |
| Mithril Integration | ✅ | Fast snapshot restore |
| Prometheus Metrics | ✅ | Both node and Forge Manager |
| ServiceMonitor | ✅ | Prometheus Operator support |
| NetworkPolicy | ✅ | Pod-level network security |
| PodDisruptionBudget | ✅ | Controlled disruptions |
| HorizontalPodAutoscaler | ✅ | For relay nodes only |
| Submit API | ✅ | Optional sidecar |
| Mithril Signer | ✅ | Optional sidecar |
| Health Checks | ✅ | Liveness and readiness probes |
| Resource Limits | ✅ | Configurable per container |
| Affinity Rules | ✅ | Pod anti-affinity support |
| Topology Spread | ✅ | Multi-zone distribution |

## 🎯 Architecture Highlights

### Two-Tier Leadership
1. **Local**: Kubernetes Lease within cluster
2. **Global**: CardanoForgeCluster CRD across regions

### Multi-Tenant Isolation
- Separate leases per pool: `cardano-leader-{network}-{pool_short_id}`
- Separate CRDs per pool: `{network}-{pool_short_id}-{region}`
- Metrics labeled with pool_id
- Complete operational independence

### Security Features
- Non-root containers (UID 10001)
- Minimal RBAC permissions
- Secrets mounted read-only
- Credentials copied with 0600 permissions
- Optional NetworkPolicy enforcement
- Process namespace isolation

### High Availability
- StatefulSet with configurable replicas
- PodDisruptionBudget for controlled updates
- Pod anti-affinity rules
- Health-based failover
- Automatic credential distribution

## 📁 File Structure

```
charts/cardano-node/
├── Chart.yaml                           # Chart metadata
├── values.yaml                          # Default configuration
├── README.md                            # Comprehensive documentation
├── CHART_STATUS.md                      # This file
├── templates/
│   ├── _helpers.tpl                     # Helper functions
│   ├── statefulset.yaml                 # Main workload
│   ├── service.yaml                     # Services
│   ├── configmap.yaml                   # Configuration
│   ├── serviceaccount.yaml              # Service account
│   ├── rbac.yaml                        # RBAC rules
│   ├── pvc.yaml                         # Optional PVC
│   ├── cardanoleader.yaml               # Legacy CRD instance
│   ├── cardanoforgecluster.yaml         # Cluster CRD instance
│   ├── servicemonitor.yaml              # Prometheus Operator
│   ├── poddisruptionbudget.yaml         # HA configuration
│   ├── networkpolicy.yaml               # Network security
│   └── hpa.yaml                         # Autoscaling (relay only)
└── values/
    ├── single-cluster-producer.yaml     # Single-cluster HA
    ├── multi-cluster-primary.yaml       # Multi-cluster primary
    ├── multi-cluster-secondary.yaml     # Multi-cluster secondary
    ├── relay-node.yaml                  # Relay deployment
    ├── multi-tenant-pool1.yaml          # Multi-tenant pool 1
    ├── multi-tenant-pool2.yaml          # Multi-tenant pool 2
    └── testnet-preprod.yaml             # Testnet deployment
```

## 🚀 Deployment Examples

### Quick Start: Single-Cluster Producer
```bash
# 1. Install CRDs
helm install cardano-forge-crds ../cardano-forge-crds --create-namespace -n cardano-system

# 2. Create secret
kubectl create secret generic forging-keys \
  --from-file=kes.skey --from-file=vrf.skey --from-file=node.cert \
  -n cardano-mainnet

# 3. Deploy
helm install cardano-producer . -n cardano-mainnet \
  -f values/single-cluster-producer.yaml
```

### Multi-Region Deployment
```bash
# Primary (US-East-1)
helm install cardano-producer . -n cardano-mainnet \
  -f values/multi-cluster-primary.yaml

# Secondary (EU-West-1)
helm install cardano-producer . -n cardano-mainnet \
  -f values/multi-cluster-secondary.yaml
```

### Multi-Tenant Deployment
```bash
# Pool 1
helm install cardano-pool1 . -n cardano-multi-tenant \
  -f values/multi-tenant-pool1.yaml

# Pool 2
helm install cardano-pool2 . -n cardano-multi-tenant \
  -f values/multi-tenant-pool2.yaml
```

## 🔍 Verification

### Check Deployment
```bash
# Pods
kubectl get pods -n cardano-mainnet

# Leader status
kubectl get cardanoleaders -n cardano-mainnet

# Cluster status (multi-cluster)
kubectl get cardanoforgeclusters

# Metrics
kubectl port-forward svc/cardano-producer-forge-metrics 8000:8000
curl localhost:8000/metrics | grep cardano_forging_enabled
```

## 📈 Next Steps (Optional Enhancements)

### Future Improvements
- [ ] Ingress template for Submit API
- [ ] Grafana dashboard ConfigMaps
- [ ] PrometheusRule for alerting
- [ ] Advanced topology management (dynamic peer discovery)
- [ ] Backup/restore automation
- [ ] Cost analysis tooling
- [ ] Multi-network support in single deployment
- [ ] Advanced health check implementations

### Integration Opportunities
- [ ] ArgoCD ApplicationSet examples
- [ ] Flux HelmRelease examples
- [ ] Terraform module for infrastructure
- [ ] Ansible playbooks for key management
- [ ] CI/CD pipeline examples

## 🎉 Summary

The **Cardano Node Helm Chart** is **production-ready** with comprehensive support for:
- ✅ High-availability block producers
- ✅ Multi-region failover
- ✅ Multi-tenant deployments
- ✅ Relay nodes
- ✅ Testnet environments
- ✅ Complete monitoring stack
- ✅ Security best practices
- ✅ Operational tooling

All core templates, examples, and documentation are complete and tested against the Forge Manager v2.0 architecture.

## 📞 Support

For questions or issues:
- Review the [README.md](./README.md)
- Check the [Forge Manager Documentation](../../docs/)
- Review example values files in `values/`
- Consult the WARP.md project guide

---

**Chart Version**: 0.1.0  
**App Version**: 10.1.3 (cardano-node) + latest (Forge Manager v2.0)  
**Last Updated**: 2025-10-02
