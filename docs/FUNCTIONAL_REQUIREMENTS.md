# Cardano Forge Manager - Functional Requirements

## Overview

The Cardano Forge Manager provides intelligent, cluster-aware block production management for Cardano Stake Pool Operators (SPOs). The system supports both single-tenant (legacy) and multi-tenant deployments, enabling efficient resource utilization while maintaining strict isolation between different networks, pools, and applications.

## Core Functional Requirements

### FR-001: Cluster-Aware Leadership Election
- **Description**: The system SHALL implement hierarchical leadership election with local StatefulSet leadership and cluster-wide coordination
- **Priority**: Critical
- **Implementation**: Local leader election within StatefulSet pods, with cluster-wide coordination via CardanoForgeCluster CRD

### FR-002: Dynamic Forge State Management
- **Description**: The system SHALL support dynamic enable/disable of block production without pod restarts
- **Priority**: Critical
- **Implementation**: Real-time CRD watching with immediate forge state updates

### FR-003: Health-Based Decision Making
- **Description**: The system SHALL integrate health check results into leadership and forge decisions
- **Priority**: High
- **Implementation**: Configurable health check endpoints with failure threshold management

## Multi-Tenant Functional Requirements

### FR-100: Multi-Tenant Pool Isolation
- **Description**: The system SHALL support multiple independent stake pools within a single Kubernetes cluster
- **Requirements**:
  - Each pool MUST have a unique identifier (POOL_ID)
  - Pool identifiers MAY be Cardano pool IDs or any unique string
  - Pools MUST be completely isolated in terms of leadership and configuration
- **Acceptance Criteria**:
  - Different pools can operate independently on the same cluster
  - Leadership decisions for one pool do not affect others
  - Configuration changes are scoped to individual pools

### FR-101: Network Isolation
- **Description**: The system SHALL support multiple Cardano networks simultaneously
- **Requirements**:
  - Support for mainnet, preprod, preview networks
  - Support for custom/private networks with any network magic
  - Network magic validation for known networks
  - Same pool ID allowed across different networks
- **Acceptance Criteria**:
  - Pools can operate on multiple networks simultaneously
  - Network-specific configuration is properly isolated
  - Cross-network leadership conflicts are prevented

### FR-102: Application Type Support
- **Description**: The system SHALL support different application types within the same pool
- **Requirements**:
  - Support for block-producer, relay, monitoring applications
  - Application-specific configuration and behavior
  - Independent health checks per application type
- **Acceptance Criteria**:
  - Multiple application types can coexist in the same pool
  - Application-specific metrics and monitoring
  - Independent forge decisions per application

### FR-103: Multi-Tenant Resource Naming
- **Description**: The system SHALL generate unique resource names incorporating tenant information
- **Requirements**:
  - Cluster names: `{network}-{pool_short}-{region}`
  - Lease names: `cardano-leader-{network}-{pool_short}`
  - Pool short names: First 8 characters of pool ID
- **Acceptance Criteria**:
  - Resource names are unique across tenants
  - Legacy single-tenant naming is preserved for backward compatibility
  - Resource names are valid Kubernetes identifiers

### FR-104: Multi-Dimensional Metrics
- **Description**: The system SHALL export metrics with multi-tenant labels
- **Requirements**:
  - Network label: `cardano_network`
  - Pool label: `pool_id`
  - Application label: `application_type`
  - All existing metrics maintain backward compatibility
- **Acceptance Criteria**:
  - Metrics can be filtered by network, pool, and application
  - Multi-tenant deployments provide proper observability
  - Single-tenant deployments continue to work unchanged

## Configuration Requirements

### FR-200: Environment Variable Configuration
- **Description**: The system SHALL support configuration via environment variables
- **Multi-Tenant Variables**:
  - `CARDANO_NETWORK`: Network name (mainnet, preprod, preview, custom)
  - `POOL_ID`: Unique pool identifier (required for multi-tenant)
  - `POOL_ID_HEX`: Optional hex representation of pool ID
  - `POOL_NAME`: Human-readable pool name
  - `POOL_TICKER`: Pool ticker symbol
  - `NETWORK_MAGIC`: Network magic number
  - `APPLICATION_TYPE`: Application type (block-producer, relay, monitoring)
- **Legacy Variables** (maintained for backward compatibility):
  - `CLUSTER_IDENTIFIER`: Legacy cluster name
  - `CLUSTER_REGION`: Geographic region
  - `CLUSTER_ENVIRONMENT`: Environment (production, staging, development)
  - `CLUSTER_PRIORITY`: Priority for leadership decisions

### FR-201: Configuration Validation
- **Description**: The system SHALL validate configuration on startup
- **Validation Rules**:
  - Pool ID must be non-empty when provided
  - Network name cannot be empty
  - Network magic must match known networks (mainnet=764824073, preprod=1, preview=2)
  - Custom networks may use any network magic
  - Pool ID hex must contain only valid hex characters when provided
- **Error Handling**:
  - Clear error messages for validation failures
  - System fails fast on invalid configuration
  - Validation errors logged with specific details

## Backward Compatibility Requirements

### FR-300: Legacy Single-Tenant Support
- **Description**: The system SHALL maintain full backward compatibility with existing single-tenant deployments
- **Requirements**:
  - Deployments without POOL_ID operate in legacy mode
  - Legacy cluster and lease naming preserved
  - Existing environment variables continue to work
  - No breaking changes to existing deployments

### FR-301: Migration Support
- **Description**: The system SHALL support gradual migration from single-tenant to multi-tenant
- **Requirements**:
  - Single-tenant clusters can be converted to multi-tenant by adding POOL_ID
  - Migration requires no downtime for properly configured systems
  - Clear documentation for migration procedures

## Operational Requirements

### FR-400: Health Check Integration
- **Description**: The system SHALL support configurable health checks
- **Configuration**:
  - `HEALTH_CHECK_ENDPOINT`: HTTP endpoint for health checks
  - `HEALTH_CHECK_INTERVAL`: Check interval in seconds (default: 30)
  - Health check timeout: 10 seconds
  - Failure threshold: 3 consecutive failures
- **Behavior**:
  - Health failures affect leadership eligibility
  - Health status included in metrics
  - Health checks are optional (system works without them)

### FR-401: Kubernetes CRD Management
- **Description**: The system SHALL manage CardanoForgeCluster Custom Resource Definitions
- **CRD Schema**:
  - Multi-tenant metadata in labels and annotations
  - Network configuration (name, magic, era)
  - Pool configuration (id, name, ticker)
  - Application configuration (type, environment)
  - Health check configuration
  - Regional configuration
- **Operations**:
  - Automatic CRD creation if not exists
  - CRD updates for status changes
  - Leader status tracking in CRD

### FR-402: Observability and Monitoring
- **Description**: The system SHALL provide comprehensive observability
- **Metrics**:
  - Cluster management status
  - Leadership state
  - Health check results
  - Multi-tenant labels for filtering
  - Performance metrics
- **Logging**:
  - Structured logging with multi-tenant context
  - Debug-level logging for troubleshooting
  - Error logging with actionable messages

## Security Requirements

### FR-500: Tenant Isolation
- **Description**: The system SHALL ensure complete isolation between tenants
- **Requirements**:
  - No cross-tenant information leakage
  - Independent authentication and authorization per tenant
  - Separate resource namespaces when possible
- **Implementation**:
  - Kubernetes RBAC integration
  - Separate CRD instances per tenant
  - Isolated leadership election scopes

### FR-501: Configuration Security
- **Description**: The system SHALL handle sensitive configuration securely
- **Requirements**:
  - Support for Kubernetes secrets
  - No sensitive data in environment variables when possible
  - Secure defaults for all configuration options

## Performance Requirements

### FR-600: Scalability
- **Description**: The system SHALL support large-scale multi-tenant deployments
- **Requirements**:
  - Support for 3+ pools per cluster
  - Support for multiple networks simultaneously
  - Efficient resource utilization across tenants
- **Performance Targets**:
  - Leadership decisions within 5 seconds
  - CRD updates within 10 seconds
  - Health check response time under 1 second

### FR-601: Resource Efficiency
- **Description**: The system SHALL minimize resource overhead
- **Requirements**:
  - Shared cluster management components
  - Efficient CRD watching with minimal API calls
  - Configurable resource limits

## Acceptance Criteria

### AC-001: Multi-Tenant Deployment
- **Given**: A Kubernetes cluster with multiple pools configured
- **When**: Pools are deployed with different POOL_ID values
- **Then**: 
  - Each pool operates independently
  - Cluster and lease names are unique per pool
  - Leadership decisions are isolated per pool
  - Metrics include proper multi-tenant labels

### AC-002: Network Isolation
- **Given**: The same pool ID deployed on different networks
- **When**: Both deployments are active
- **Then**:
  - Each network deployment operates independently
  - Different cluster names are generated
  - Network-specific configuration is applied
  - No leadership conflicts occur

### AC-003: Backward Compatibility
- **Given**: An existing single-tenant deployment
- **When**: The system is upgraded without configuration changes
- **Then**:
  - Deployment continues to operate normally
  - Legacy cluster and lease names are preserved
  - All existing functionality remains available
  - No service disruption occurs

### AC-004: Configuration Validation
- **Given**: Invalid multi-tenant configuration
- **When**: The system starts up
- **Then**:
  - Clear error messages are provided
  - System fails fast without causing issues
  - Validation errors include specific details
  - System does not start with invalid configuration

### AC-005: Health Check Integration
- **Given**: Health checks are configured for a multi-tenant pool
- **When**: Health checks fail for one pool
- **Then**:
  - Only the failing pool's leadership is affected
  - Other pools continue to operate normally
  - Health status is reflected in metrics
  - Recovery is automatic when health checks pass

## Testing Requirements

### TR-001: Unit Testing
- **Coverage**: Minimum 80% code coverage
- **Scope**: All multi-tenant functionality, validation, and configuration
- **Test Types**: 
  - Pool ID validation
  - Network isolation
  - Configuration validation
  - Backward compatibility
  - Leadership isolation

### TR-002: Integration Testing
- **Scope**: End-to-end multi-tenant scenarios
- **Environment**: Real Kubernetes clusters with multiple tenants
- **Scenarios**:
  - Multi-tenant deployment and operation
  - Cross-network isolation validation
  - Migration from single-tenant to multi-tenant
  - Failure recovery scenarios

### TR-003: Performance Testing
- **Scope**: Large-scale multi-tenant deployments
- **Metrics**: Resource usage, response times, scalability limits
- **Scenarios**:
  - 3+ pool deployment
  - Multiple network simultaneous operation
  - High-frequency leadership changes
  - Resource exhaustion recovery
