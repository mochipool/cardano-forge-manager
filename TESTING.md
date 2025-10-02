# Cluster-Wide Forge Management Testing Guide

This document provides comprehensive testing procedures for the cluster-wide forge management features, ensuring both functionality and backward compatibility.

## Table of Contents
1. [Testing Overview](#testing-overview)
2. [Prerequisites](#prerequisites)
3. [Unit Testing](#unit-testing)
4. [Integration Testing](#integration-testing)
5. [End-to-End Testing](#end-to-end-testing)
6. [Performance Testing](#performance-testing)
7. [Backward Compatibility Testing](#backward-compatibility-testing)
8. [Operational Testing](#operational-testing)
9. [Troubleshooting](#troubleshooting)

---

## Testing Overview

The cluster-wide forge management system extends the existing Cardano forge manager with multi-cluster coordination capabilities. Testing covers:

- **Backward Compatibility**: Existing single-cluster deployments must work unchanged
- **New Functionality**: Cluster-wide coordination, priority-based decisions, health checks
- **Edge Cases**: Network partitions, CRD synchronization issues, race conditions
- **Performance**: Minimal overhead for existing functionality

### Test Environments

1. **Development**: Local testing with mocked Kubernetes APIs
2. **Staging**: Single cluster with cluster management enabled
3. **Multi-Cluster Staging**: Multiple clusters for cross-cluster testing
4. **Production**: Gradual rollout with feature flags

---

## Prerequisites

### Software Requirements

```bash
# Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt  # Additional test dependencies
```

### Kubernetes Environment

```bash
# Install CRDs
kubectl apply -f k8s/cardano-forge-cluster-crd.yaml
kubectl apply -f k8s/cardano-forge-cluster-rbac.yaml

# Verify CRD installation
kubectl get crd cardanoforgeclusters.cardano.io
kubectl describe crd cardanoforgeclusters.cardano.io
```

### Test Dependencies

Create `requirements-test.txt`:
```
unittest-xml-reporting>=3.2.0
coverage>=7.0.0
pytest>=7.0.0
pytest-kubernetes>=1.2.0
pytest-timeout>=2.1.0
```

---

## Unit Testing

### Running Unit Tests

```bash
# Run all unit tests
python -m pytest tests/test_cluster_management.py -v

# Run with coverage
coverage run -m pytest tests/test_cluster_management.py
coverage report --show-missing
coverage html  # Generate HTML report

# Run specific test class
python -m pytest tests/test_cluster_management.py::TestClusterForgeManager -v

# Run with XML output for CI
python -m pytest tests/test_cluster_management.py --junitxml=test-results.xml
```

### Test Categories

#### 1. Cluster Manager Core Tests
```bash
python tests/test_cluster_management.py TestClusterForgeManager
```

**Test Coverage:**
- [x] Initialization with different environment configurations
- [x] Leadership decision logic (enabled/disabled/priority-based states)
- [x] CRD creation and status updates
- [x] Health check success/failure scenarios
- [x] Metrics export functionality
- [x] Thread lifecycle management

#### 2. Integration Tests
```bash
python tests/test_cluster_management.py TestClusterManagerIntegration
```

**Test Coverage:**
- [x] Backward compatibility with existing deployments
- [x] Global cluster manager initialization
- [x] Module-level function behavior
- [x] Environment variable handling

#### 3. Scenario Tests
```bash
python tests/test_cluster_management.py TestClusterScenarios
```

**Test Coverage:**
- [x] Multi-cluster priority coordination
- [x] Manual failover with override settings
- [x] Global disable/enable scenarios
- [x] Health check integration

### Adding New Tests

When adding new functionality, ensure tests cover:

```python
def test_new_feature(self):
    """Test description following the pattern."""
    # Arrange
    setup_test_conditions()
    
    # Act
    result = execute_functionality()
    
    # Assert
    self.assertEqual(expected_result, result)
    verify_side_effects()
```

---

## Integration Testing

### Local Integration Testing

Test the integration between cluster management and the main forge manager:

```bash
# Start local test cluster
kind create cluster --name cardano-test

# Install test resources
kubectl apply -f k8s/cardano-forge-cluster-crd.yaml
kubectl apply -f examples/multi-region-forge-clusters.yaml

# Run integration tests
python -m pytest tests/test_integration.py -v
```

### Environment Configuration Testing

Test different environment variable combinations:

```bash
# Test with cluster management disabled (backward compatibility)
export ENABLE_CLUSTER_MANAGEMENT=false
python src/forgemanager.py --test-mode

# Test with cluster management enabled
export ENABLE_CLUSTER_MANAGEMENT=true
export CLUSTER_IDENTIFIER=test-cluster-1
export CLUSTER_REGION=us-test-1
export CLUSTER_PRIORITY=1
python src/forgemanager.py --test-mode

# Test health check integration
export HEALTH_CHECK_ENDPOINT=http://localhost:8080/health
python src/forgemanager.py --test-mode
```

### CRD Validation Testing

```bash
# Test CRD creation and validation
kubectl apply -f examples/multi-region-forge-clusters.yaml

# Verify CRD structure
kubectl get cardanoforgeclusters -o yaml

# Test invalid CRD configurations
kubectl apply -f tests/fixtures/invalid-crd.yaml  # Should fail validation
```

---

## End-to-End Testing

### Single Cluster E2E Testing

Deploy the complete system in a test environment:

```yaml
# test-deployment.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cardano-test
---
# Include your full deployment here with test configuration
```

```bash
# Deploy test environment
kubectl apply -f test-deployment.yaml

# Wait for deployment
kubectl wait --for=condition=Ready pod -l app=cardano-node -n cardano-test --timeout=300s

# Run E2E tests
python tests/test_e2e.py --namespace=cardano-test
```

### Multi-Cluster E2E Testing

For testing cross-cluster coordination:

```bash
# Create multiple test clusters
kind create cluster --name cardano-test-east
kind create cluster --name cardano-test-west

# Deploy to each cluster with different priorities
kubectl --context kind-cardano-test-east apply -f test-east-deployment.yaml
kubectl --context kind-cardano-test-west apply -f test-west-deployment.yaml

# Run multi-cluster tests
python tests/test_multi_cluster.py
```

### Test Scenarios

#### Scenario 1: Normal Operation
1. Deploy primary cluster (priority 1)
2. Deploy secondary cluster (priority 2)
3. Verify only primary cluster is forging
4. Check metrics show correct state

#### Scenario 2: Failover Testing
1. Start with primary cluster forging
2. Disable primary cluster via CRD update
3. Verify secondary cluster takes over
4. Re-enable primary and verify failback

#### Scenario 3: Health Check Integration
1. Configure health check endpoint
2. Simulate health check failures
3. Verify priority adjustments
4. Test recovery scenarios

---

## Performance Testing

### Baseline Performance

Test performance impact of cluster management features:

```bash
# Measure baseline (without cluster management)
export ENABLE_CLUSTER_MANAGEMENT=false
python tests/performance/baseline_test.py

# Measure with cluster management enabled
export ENABLE_CLUSTER_MANAGEMENT=true
python tests/performance/cluster_test.py

# Compare results
python tests/performance/compare.py
```

### Load Testing

Test system behavior under load:

```bash
# Simulate rapid CRD updates
python tests/load/crd_update_load.py

# Test with multiple watchers
python tests/load/multi_watcher_test.py

# Health check load testing
python tests/load/health_check_load.py
```

### Memory and CPU Usage

```bash
# Monitor resource usage during tests
python tests/performance/resource_monitor.py &
MONITOR_PID=$!

# Run test scenarios
python tests/test_cluster_management.py

# Stop monitoring and generate report
kill $MONITOR_PID
python tests/performance/generate_report.py
```

---

## Backward Compatibility Testing

### Existing Deployment Validation

Ensure existing single-cluster deployments continue working:

```bash
# Test with original configuration (no cluster management)
kubectl apply -f tests/fixtures/original-deployment.yaml

# Verify forge manager works as before
kubectl logs -f statefulset/cardano-node -c forge-manager

# Check metrics endpoint
curl http://localhost:8000/metrics | grep cardano_

# Verify no cluster-wide metrics are present when disabled
! curl http://localhost:8000/metrics | grep cardano_cluster_
```

### Migration Testing

Test migration from single-cluster to cluster-aware deployment:

```bash
# Start with original deployment
kubectl apply -f tests/fixtures/original-deployment.yaml
sleep 60

# Apply cluster management configuration
kubectl patch statefulset cardano-node --patch-file tests/fixtures/cluster-management-patch.yaml

# Verify smooth transition
kubectl rollout status statefulset/cardano-node
python tests/migration/verify_transition.py
```

### Configuration Compatibility

Test that all existing environment variables still work:

```python
# tests/test_compatibility.py
def test_existing_env_vars():
    """Test that all existing environment variables are still supported."""
    original_vars = [
        'NAMESPACE', 'POD_NAME', 'NODE_SOCKET', 'LEASE_NAME',
        'CRD_GROUP', 'CRD_VERSION', 'CRD_PLURAL', 'CRD_NAME',
        'METRICS_PORT', 'LOG_LEVEL', 'SLEEP_INTERVAL',
        # ... add all existing variables
    ]
    
    for var in original_vars:
        with self.subTest(var=var):
            # Test that variable is still recognized and functional
            pass
```

---

## Operational Testing

### Manual Failover Testing

Test SPO operational procedures:

```bash
# Scenario: Maintenance on primary cluster
echo "1. Check current active cluster:"
kubectl get cardanoforgeclusters -o wide

echo "2. Disable primary cluster for maintenance:"
kubectl patch cardanoforgeCluster us-east-1-prod \
  --type='merge' -p='{"spec":{"forgeState":"Disabled","override":{"enabled":true,"reason":"Maintenance"}}}'

echo "3. Verify secondary cluster takes over:"
sleep 30
kubectl get cardanoforgeclusters -o wide
curl http://monitoring.example.com/metrics | grep cardano_cluster_forge_enabled

echo "4. Re-enable after maintenance:"
kubectl patch cardanoforgeCluster us-east-1-prod \
  --type='merge' -p='{"spec":{"forgeState":"Priority-based","override":{"enabled":false}}}'

echo "5. Verify primary cluster resumes leadership:"
sleep 30
kubectl get cardanoforgeclusters -o wide
```

### Disaster Recovery Testing

Test disaster recovery scenarios:

```bash
# Scenario: Complete cluster failure
echo "1. Simulate cluster failure:"
kubectl delete cluster us-east-1-cluster  # Or equivalent cluster destruction

echo "2. Verify automatic failover to secondary:"
kubectl --context us-west-2 get cardanoforgeclusters
curl http://us-west-2.monitoring.example.com/metrics | grep cardano_cluster_forge_enabled

echo "3. Test recovery procedures:"
# ... restore primary cluster
# ... verify failback
```

### Monitoring and Alerting Testing

Test monitoring integration:

```bash
# Test Prometheus metrics collection
curl http://localhost:8000/metrics | grep cardano_cluster_

# Test alerting rules
python tests/monitoring/test_alerts.py

# Verify alert conditions trigger correctly
python tests/monitoring/trigger_alerts.py
```

---

## Validation Procedures

### Pre-Deployment Validation

Before deploying cluster management to production:

```bash
# Run complete test suite
python -m pytest tests/ -v --cov=src --cov-report=html

# Validate CRD schemas
kubectl apply --dry-run=server -f k8s/cardano-forge-cluster-crd.yaml

# Test RBAC permissions
kubectl auth can-i create cardanoforgeclusters --as=system:serviceaccount:cardano:forge-manager

# Performance validation
python tests/performance/validate_performance.py
```

### Post-Deployment Validation

After deploying to production:

```bash
# Health check validation
python tests/production/health_check.py

# Metrics validation
python tests/production/metrics_check.py

# Leader election validation
python tests/production/leadership_check.py

# Cross-cluster coordination validation (if applicable)
python tests/production/multi_cluster_check.py
```

---

## Troubleshooting

### Common Issues

#### 1. CRD Not Found Errors
```bash
# Check CRD installation
kubectl get crd cardanoforgeclusters.cardano.io

# Reinstall if missing
kubectl apply -f k8s/cardano-forge-cluster-crd.yaml
```

#### 2. RBAC Permission Errors
```bash
# Check service account permissions
kubectl auth can-i get cardanoforgeclusters --as=system:serviceaccount:cardano:forge-manager

# Update RBAC if needed
kubectl apply -f k8s/cardano-forge-cluster-rbac.yaml
```

#### 3. Health Check Failures
```bash
# Test health check endpoint manually
curl -v http://monitoring.example.com/health

# Check forge manager logs
kubectl logs statefulset/cardano-node -c forge-manager | grep health
```

#### 4. Metrics Not Appearing
```bash
# Check if cluster management is enabled
kubectl exec statefulset/cardano-node -c forge-manager -- \
  env | grep ENABLE_CLUSTER_MANAGEMENT

# Verify metrics endpoint
kubectl port-forward statefulset/cardano-node 8000:8000
curl http://localhost:8000/metrics | grep cluster
```

### Debug Mode

Enable debug logging for troubleshooting:

```bash
# Set debug environment
kubectl patch statefulset cardano-node --type='merge' -p='{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "forge-manager",
            "env": [
              {"name": "LOG_LEVEL", "value": "DEBUG"}
            ]
          }
        ]
      }
    }
  }
}'

# Check debug logs
kubectl logs -f statefulset/cardano-node -c forge-manager
```

### Test Data Cleanup

Clean up test resources:

```bash
# Remove test CRDs
kubectl delete cardanoforgeclusters --all

# Remove test namespaces
kubectl delete namespace cardano-test

# Clean up test clusters
kind delete cluster --name cardano-test-east
kind delete cluster --name cardano-test-west
```

---

## Continuous Integration

### CI Pipeline Configuration

Example GitHub Actions workflow:

```yaml
# .github/workflows/test-cluster-management.yml
name: Test Cluster Management
on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Setup Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-test.txt
    - name: Run unit tests
      run: |
        python -m pytest tests/test_cluster_management.py \
          --junitxml=test-results.xml \
          --cov=src --cov-report=xml
    - name: Upload coverage
      uses: codecov/codecov-action@v3

  integration-tests:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Setup kind cluster
      uses: helm/kind-action@v1.4.0
    - name: Install CRDs
      run: |
        kubectl apply -f k8s/cardano-forge-cluster-crd.yaml
        kubectl apply -f k8s/cardano-forge-cluster-rbac.yaml
    - name: Run integration tests
      run: python -m pytest tests/test_integration.py -v
```

### Quality Gates

Before merging changes:

- [ ] All unit tests pass (100% required)
- [ ] Integration tests pass (100% required)
- [ ] Code coverage >= 90%
- [ ] No performance regression > 5%
- [ ] Backward compatibility tests pass
- [ ] Security scan passes

---

## Test Maintenance

### Regular Testing Schedule

- **Daily**: Unit tests, backward compatibility tests
- **Weekly**: Integration tests, performance tests
- **Monthly**: Full E2E tests, multi-cluster tests
- **Quarterly**: Disaster recovery tests, security audits

### Test Update Procedures

When adding new features:

1. Add unit tests for new functionality
2. Update integration tests if needed
3. Add E2E scenarios for user-facing features
4. Update this documentation
5. Validate backward compatibility

When fixing bugs:

1. Add regression tests
2. Verify fix doesn't break existing functionality
3. Update relevant test categories

---

This testing guide ensures comprehensive validation of the cluster-wide forge management system while maintaining backward compatibility and operational reliability.