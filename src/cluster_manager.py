#!/usr/bin/env python3
# src/cluster_manager.py
"""
CardanoForgeCluster CRD management for cluster-wide forge coordination.

This module provides functionality for:
- Watching CardanoForgeCluster CRD changes
- Evaluating cluster-wide forge state and priorities
- Health check integration
- Hierarchical decision making for forge enablement
"""

import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests
from kubernetes import client, watch
from kubernetes.client.rest import ApiException

logger = logging.getLogger("cardano-forge-manager.cluster")

# Environment variables for cluster management
# Legacy single-tenant variables (for backward compatibility)
CLUSTER_IDENTIFIER = os.environ.get("CLUSTER_IDENTIFIER", socket.gethostname())
CLUSTER_REGION = os.environ.get("CLUSTER_REGION", "unknown")
CLUSTER_ENVIRONMENT = os.environ.get("CLUSTER_ENVIRONMENT", "production")
CLUSTER_PRIORITY = int(os.environ.get("CLUSTER_PRIORITY", "100"))

# Multi-tenant environment variables
CARDANO_NETWORK = os.environ.get("CARDANO_NETWORK", "mainnet")
POOL_ID = os.environ.get("POOL_ID", "")
POOL_ID_HEX = os.environ.get("POOL_ID_HEX", "")
POOL_NAME = os.environ.get("POOL_NAME", "")
POOL_TICKER = os.environ.get("POOL_TICKER", "")
NETWORK_MAGIC = int(os.environ.get("NETWORK_MAGIC", "764824073"))  # Default to mainnet
APPLICATION_TYPE = os.environ.get("APPLICATION_TYPE", "block-producer")

# Control variables
ENABLE_CLUSTER_MANAGEMENT = os.environ.get(
    "ENABLE_CLUSTER_MANAGEMENT", "false"
).lower() in ("true", "1", "yes")
HEALTH_CHECK_ENDPOINT = os.environ.get("HEALTH_CHECK_ENDPOINT", "")
HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "30"))

# CRD configuration
CRD_GROUP = "cardano.io"
CRD_VERSION = "v1"
CRD_PLURAL = "cardanoforgeclusters"


# Pool ID validation and utilities
def validate_pool_id(pool_id: str) -> bool:
    """Validate pool ID as a unique identifier.

    Pool ID can be any non-empty string that serves as a unique identifier.
    While SPOs should ideally use their actual Cardano pool ID, any unique
    identifier is acceptable for multi-tenant purposes.
    """
    return bool(pool_id and pool_id.strip())


def validate_pool_id_hex(pool_id_hex: str) -> bool:
    """Validate pool ID hex format (optional field).

    If provided, should be a valid hex string, but this is optional.
    """
    if not pool_id_hex or not pool_id_hex.strip():
        return True  # Empty is valid (optional field)
    import re

    return bool(re.match(r"^[a-f0-9]+$", pool_id_hex.lower()))


def get_pool_short_id(pool_id: str) -> str:
    """Get short form of pool ID for naming purposes."""
    if pool_id.startswith("pool1"):
        return pool_id[:10]  # pool1abcd
    elif len(pool_id) >= 8:
        return pool_id[:8]  # abcd1234
    return pool_id


def get_multi_tenant_cluster_name() -> str:
    """Generate cluster name for multi-tenant deployment."""
    if POOL_ID and CARDANO_NETWORK and CLUSTER_REGION:
        pool_short = get_pool_short_id(POOL_ID)
        return f"{CARDANO_NETWORK}-{pool_short}-{CLUSTER_REGION}"
    else:
        # Fall back to legacy naming
        return CLUSTER_IDENTIFIER


def get_lease_name() -> str:
    """Generate lease name scoped to network and pool."""
    if POOL_ID and CARDANO_NETWORK:
        pool_short = get_pool_short_id(POOL_ID)
        return f"cardano-leader-{CARDANO_NETWORK}-{pool_short}"
    else:
        # Fall back to legacy naming
        return "cardano-node-leader"


def validate_multi_tenant_config() -> Tuple[bool, str]:
    """Validate multi-tenant configuration."""
    if not ENABLE_CLUSTER_MANAGEMENT:
        return True, "cluster_management_disabled"

    # If pool ID is provided, validate multi-tenant setup
    if POOL_ID:
        if not validate_pool_id(POOL_ID):
            return (
                False,
                f"invalid_pool_id: Pool ID must be a non-empty unique identifier",
            )

        if POOL_ID_HEX and not validate_pool_id_hex(POOL_ID_HEX):
            return (
                False,
                f"invalid_pool_id_hex: {POOL_ID_HEX} must be valid hex characters",
            )

        # Allow any network name - operators may use custom networks
        if not CARDANO_NETWORK or not CARDANO_NETWORK.strip():
            return False, "invalid_network: Network name cannot be empty"

        # Validate network magic for known networks (optional validation)
        known_magics = {"mainnet": 764824073, "preprod": 1, "preview": 2}

        # Only validate magic for known networks, custom networks can use any magic
        if CARDANO_NETWORK in known_magics:
            if NETWORK_MAGIC != known_magics[CARDANO_NETWORK]:
                return (
                    False,
                    f"network_magic_mismatch: {CARDANO_NETWORK} expects {known_magics[CARDANO_NETWORK]}, got {NETWORK_MAGIC}",
                )

    return True, "valid_config"


class ClusterForgeManager:
    """Manages cluster-wide forge state using CardanoForgeCluster CRD."""

    def __init__(self, custom_objects_api: client.CustomObjectsApi):
        self.api = custom_objects_api

        # Validate multi-tenant configuration
        config_valid, config_message = validate_multi_tenant_config()
        if not config_valid:
            raise ValueError(f"Invalid multi-tenant configuration: {config_message}")

        # Multi-tenant identification
        self.cluster_id = get_multi_tenant_cluster_name()
        self.lease_name = get_lease_name()

        # Network and pool configuration
        self.network = CARDANO_NETWORK
        self.network_magic = NETWORK_MAGIC
        self.pool_id = POOL_ID
        self.pool_id_hex = POOL_ID_HEX
        self.pool_name = POOL_NAME
        self.pool_ticker = POOL_TICKER
        self.application_type = APPLICATION_TYPE

        # Legacy compatibility
        self.region = CLUSTER_REGION
        self.environment = CLUSTER_ENVIRONMENT
        self.priority = CLUSTER_PRIORITY
        self.enabled = ENABLE_CLUSTER_MANAGEMENT

        # State tracking
        self._current_cluster_crd: Optional[Dict[str, Any]] = None
        self._cluster_forge_enabled = False
        self._effective_priority = self.priority
        self._last_health_check = None
        self._consecutive_health_failures = 0
        self._watch_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

        logger.info(
            f"Cluster manager initialized: enabled={self.enabled}, cluster={self.cluster_id}, "
            f"network={self.network}, pool={self.pool_id or 'legacy'}, region={self.region}, priority={self.priority}"
        )

    def start(self):
        """Start cluster management threads if enabled."""
        if not self.enabled:
            logger.info(
                "Cluster management disabled via ENABLE_CLUSTER_MANAGEMENT=false"
            )
            return

        try:
            # Ensure CRD exists or create it
            self._ensure_cluster_crd()

            # Start CRD watching thread
            self._watch_thread = threading.Thread(
                target=self._watch_cluster_crd, daemon=True
            )
            self._watch_thread.start()
            logger.info("Started CardanoForgeCluster CRD watch thread")

            # Start health check thread if configured
            if HEALTH_CHECK_ENDPOINT:
                self._health_thread = threading.Thread(
                    target=self._health_check_loop, daemon=True
                )
                self._health_thread.start()
                logger.info(f"Started health check thread for {HEALTH_CHECK_ENDPOINT}")

        except Exception as e:
            logger.error(f"Failed to start cluster management: {e}")
            self.enabled = False

    def stop(self):
        """Stop all cluster management threads."""
        logger.info("Stopping cluster management")
        self._shutdown_event.set()

        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=5)

        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=5)

    def should_allow_local_leadership(self) -> Tuple[bool, str]:
        """
        Determine if local leadership election should be allowed.

        Returns:
            Tuple[bool, str]: (allowed, reason)
        """
        if not self.enabled:
            return True, "cluster_management_disabled"

        if not self._current_cluster_crd:
            # If CRD doesn't exist, default to allowing leadership (backward compatibility)
            return True, "no_cluster_crd"

        try:
            spec = self._current_cluster_crd.get("spec", {})
            status = self._current_cluster_crd.get("status", {})

            forge_state = spec.get("forgeState", "Priority-based")
            effective_state = status.get("effectiveState", forge_state)

            if effective_state == "Disabled":
                return False, "cluster_forge_disabled"

            if effective_state == "Enabled":
                return True, "cluster_forge_enabled"

            # Priority-based decision making
            if effective_state == "Priority-based":
                # TODO: Implement cross-cluster priority comparison
                # For now, allow if this cluster has high priority
                effective_priority = status.get("effectivePriority", self.priority)
                if effective_priority <= 10:  # High priority clusters
                    return True, f"high_priority_{effective_priority}"
                else:
                    return True, f"priority_based_{effective_priority}"

            return True, "default_allow"

        except Exception as e:
            logger.error(f"Error evaluating cluster leadership: {e}")
            return True, "evaluation_error"

    def update_leader_status(self, pod_name: Optional[str], is_leader: bool):
        """Update the cluster CRD with current leader information."""
        if not self.enabled or not self._current_cluster_crd:
            return

        try:
            status_patch = {
                "status": {
                    "activeLeader": pod_name if is_leader else "",
                    "lastTransition": datetime.now(timezone.utc).isoformat(),
                }
            }

            self.api.patch_cluster_custom_object_status(
                group=CRD_GROUP,
                version=CRD_VERSION,
                plural=CRD_PLURAL,
                name=self.cluster_id,
                body=status_patch,
            )

            logger.debug(
                f"Updated cluster CRD status: leader={pod_name}, is_leader={is_leader}"
            )

        except ApiException as e:
            logger.warning(f"Failed to update cluster CRD status: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating cluster CRD status: {e}")

    def get_cluster_metrics(self) -> Dict[str, Any]:
        """Get current cluster state for metrics export."""
        if not self.enabled:
            return {"enabled": False}

        return {
            "enabled": True,
            "forge_enabled": self._cluster_forge_enabled,
            "effective_priority": self._effective_priority,
            "cluster_id": self.cluster_id,
            "region": self.region,
            # Multi-tenant information
            "network": self.network,
            "pool_id": self.pool_id,
            "pool_ticker": self.pool_ticker,
            "application_type": self.application_type,
            "health_status": {
                "healthy": self._consecutive_health_failures == 0,
                "consecutive_failures": self._consecutive_health_failures,
                "last_check": (
                    self._last_health_check.isoformat()
                    if self._last_health_check
                    else None
                ),
            },
        }

    def _ensure_cluster_crd(self):
        """Ensure CardanoForgeCluster CRD exists for this cluster."""
        try:
            # Try to get existing CRD
            self._current_cluster_crd = self.api.get_cluster_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                plural=CRD_PLURAL,
                name=self.cluster_id,
            )
            logger.info(f"Found existing CardanoForgeCluster CRD: {self.cluster_id}")

        except ApiException as e:
            if e.status == 404:
                # Create new CRD
                logger.info(f"Creating CardanoForgeCluster CRD: {self.cluster_id}")
                self._create_cluster_crd()
            else:
                logger.error(f"Error checking CardanoForgeCluster CRD: {e}")
                raise

    def _create_cluster_crd(self):
        """Create a new CardanoForgeCluster CRD for this cluster."""
        # Build labels with multi-tenant support
        labels = {
            "cardano.io/region": self.region,
            "cardano.io/environment": self.environment,
            "cardano.io/managed-by": "cardano-forge-manager",
            "cardano.io/network": self.network,
            "cardano.io/application": self.application_type,
        }

        # Add pool-specific labels if available
        if self.pool_id:
            labels["cardano.io/pool-id"] = self.pool_id
            if self.pool_id_hex:
                labels["cardano.io/pool-id-hex"] = self.pool_id_hex
            if self.pool_ticker:
                labels["cardano.io/pool-ticker"] = self.pool_ticker

        crd_body = {
            "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
            "kind": "CardanoForgeCluster",
            "metadata": {
                "name": self.cluster_id,
                "labels": labels,
            },
            "spec": {
                # Network configuration
                "network": {
                    "name": self.network,
                    "magic": self.network_magic,
                    "era": "conway",
                },
                # Pool configuration
                "pool": {
                    "id": self.pool_id or "unknown",
                    "idHex": self.pool_id_hex or "unknown",
                    "name": self.pool_name or "Unknown Pool",
                    "ticker": self.pool_ticker or "UNK",
                },
                # Application configuration
                "application": {
                    "type": self.application_type,
                    "environment": self.environment,
                },
                # Regional configuration
                "region": self.region,
                # Forge state configuration
                "forgeState": "Priority-based",
                "priority": self.priority,
                # Health check configuration
                "healthCheck": (
                    {
                        "enabled": bool(HEALTH_CHECK_ENDPOINT),
                        "endpoint": HEALTH_CHECK_ENDPOINT,
                        "interval": f"{HEALTH_CHECK_INTERVAL}s",
                        "timeout": "10s",
                        "failureThreshold": 3,
                    }
                    if HEALTH_CHECK_ENDPOINT
                    else {"enabled": False}
                ),
            },
            "status": {
                "effectiveState": "Priority-based",
                "effectivePriority": self.priority,
                "lastTransition": datetime.now(timezone.utc).isoformat(),
                "reason": "InitialCreation",
                "conditions": [
                    {
                        "type": "Ready",
                        "status": "True",
                        "lastTransitionTime": datetime.now(timezone.utc).isoformat(),
                        "reason": "ClusterInitialized",
                        "message": "Cluster CRD created successfully",
                    }
                ],
                "healthStatus": {
                    "healthy": True,
                    "consecutiveFailures": 0,
                    "message": "Initial state",
                },
            },
        }

        try:
            self._current_cluster_crd = self.api.create_cluster_custom_object(
                group=CRD_GROUP, version=CRD_VERSION, plural=CRD_PLURAL, body=crd_body
            )
            logger.info(f"Created CardanoForgeCluster CRD: {self.cluster_id}")

        except ApiException as e:
            logger.error(f"Failed to create CardanoForgeCluster CRD: {e}")
            raise

    def _watch_cluster_crd(self):
        """Watch for changes to CardanoForgeCluster CRDs."""
        logger.info("Starting CardanoForgeCluster CRD watch")

        while not self._shutdown_event.is_set():
            try:
                w = watch.Watch()
                for event in w.stream(
                    self.api.list_cluster_custom_object,
                    group=CRD_GROUP,
                    version=CRD_VERSION,
                    plural=CRD_PLURAL,
                    timeout_seconds=30,
                ):
                    if self._shutdown_event.is_set():
                        break

                    event_type = event["type"]
                    obj = event["object"]
                    obj_name = obj.get("metadata", {}).get("name", "")

                    if obj_name == self.cluster_id:
                        logger.debug(f"Received CRD event: {event_type} for {obj_name}")
                        self._handle_cluster_crd_change(obj)

                w.stop()

            except ApiException as e:
                if e.status == 410:  # Resource version too old
                    logger.info("CRD watch resource version expired, restarting")
                    continue
                else:
                    logger.error(f"CRD watch error: {e}")
                    time.sleep(5)

            except Exception as e:
                logger.error(f"Unexpected CRD watch error: {e}")
                time.sleep(5)

        logger.info("CardanoForgeCluster CRD watch stopped")

    def _handle_cluster_crd_change(self, crd_obj: Dict[str, Any]):
        """Handle changes to our cluster's CRD."""
        try:
            self._current_cluster_crd = crd_obj

            spec = crd_obj.get("spec", {})
            status = crd_obj.get("status", {})

            forge_state = spec.get("forgeState", "Priority-based")
            effective_state = status.get("effectiveState", forge_state)

            # Update local state
            old_forge_enabled = self._cluster_forge_enabled
            self._cluster_forge_enabled = effective_state in (
                "Enabled",
                "Priority-based",
            )
            self._effective_priority = status.get(
                "effectivePriority", spec.get("priority", self.priority)
            )

            if old_forge_enabled != self._cluster_forge_enabled:
                logger.info(
                    f"Cluster forge state changed: {old_forge_enabled} -> {self._cluster_forge_enabled} (state: {effective_state})"
                )

        except Exception as e:
            logger.error(f"Error handling cluster CRD change: {e}")

    def _health_check_loop(self):
        """Perform periodic health checks."""
        logger.info(f"Starting health check loop for {HEALTH_CHECK_ENDPOINT}")

        while not self._shutdown_event.is_set():
            try:
                self._perform_health_check()

                # Wait for next interval
                if self._shutdown_event.wait(HEALTH_CHECK_INTERVAL):
                    break

            except Exception as e:
                logger.error(f"Health check loop error: {e}")
                time.sleep(5)

        logger.info("Health check loop stopped")

    def _perform_health_check(self):
        """Perform a single health check."""
        try:
            response = requests.get(
                HEALTH_CHECK_ENDPOINT,
                timeout=10,
                headers={"User-Agent": "cardano-forge-manager/1.0"},
            )

            healthy = response.status_code == 200
            self._last_health_check = datetime.now(timezone.utc)

            if healthy:
                self._consecutive_health_failures = 0
            else:
                self._consecutive_health_failures += 1

            logger.debug(
                f"Health check: {healthy}, consecutive failures: {self._consecutive_health_failures}"
            )

            # Update CRD status if needed
            self._update_health_status(healthy, f"HTTP {response.status_code}")

        except requests.RequestException as e:
            self._consecutive_health_failures += 1
            self._last_health_check = datetime.now(timezone.utc)

            logger.warning(
                f"Health check failed: {e}, consecutive failures: {self._consecutive_health_failures}"
            )
            self._update_health_status(False, str(e))

        except Exception as e:
            logger.error(f"Unexpected health check error: {e}")

    def _update_health_status(self, healthy: bool, message: str):
        """Update the health status in the CRD."""
        if not self._current_cluster_crd:
            return

        try:
            status_patch = {
                "status": {
                    "healthStatus": {
                        "healthy": healthy,
                        "lastProbeTime": self._last_health_check.isoformat(),
                        "consecutiveFailures": self._consecutive_health_failures,
                        "message": message,
                    }
                }
            }

            self.api.patch_cluster_custom_object_status(
                group=CRD_GROUP,
                version=CRD_VERSION,
                plural=CRD_PLURAL,
                name=self.cluster_id,
                body=status_patch,
            )

        except Exception as e:
            logger.warning(f"Failed to update health status: {e}")


# Backward compatibility - create a global instance that can be disabled
cluster_manager: Optional[ClusterForgeManager] = None


def initialize_cluster_manager(
    custom_objects_api: client.CustomObjectsApi,
) -> Optional[ClusterForgeManager]:
    """Initialize the global cluster manager instance."""
    global cluster_manager

    if cluster_manager is None:
        cluster_manager = ClusterForgeManager(custom_objects_api)
        cluster_manager.start()

    return cluster_manager


def get_cluster_manager() -> Optional[ClusterForgeManager]:
    """Get the global cluster manager instance."""
    return cluster_manager


def should_allow_local_leadership() -> Tuple[bool, str]:
    """
    Check if local leadership election should be allowed based on cluster state.

    Returns:
        Tuple[bool, str]: (allowed, reason)
    """
    if cluster_manager and cluster_manager.enabled:
        return cluster_manager.should_allow_local_leadership()

    return True, "cluster_management_disabled"


def update_cluster_leader_status(pod_name: Optional[str], is_leader: bool):
    """Update cluster CRD with current leader status."""
    if cluster_manager and cluster_manager.enabled:
        cluster_manager.update_leader_status(pod_name, is_leader)


def get_cluster_metrics() -> Dict[str, Any]:
    """Get cluster metrics for Prometheus export."""
    if cluster_manager and cluster_manager.enabled:
        return cluster_manager.get_cluster_metrics()

    return {"enabled": False}
