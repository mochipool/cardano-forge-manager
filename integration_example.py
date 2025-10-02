#!/usr/bin/env python3
"""
Example integration showing how cluster-wide coordination integrates
with existing StatefulSet leader election in forgemanager.py
"""

import os
import time
import logging
from typing import Optional, Tuple

# Cluster management imports (new)
from cluster_manager import ClusterManager

# Existing imports (from original forgemanager.py)
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger("cardano-forge-manager")

# Environment variables
NAMESPACE = os.environ.get("NAMESPACE", "default")
POD_NAME = os.environ.get("POD_NAME", "")
LEASE_NAME = os.environ.get("LEASE_NAME", "cardano-node-leader")
LEASE_DURATION = int(os.environ.get("LEASE_DURATION", 15))
SLEEP_INTERVAL = int(os.environ.get("SLEEP_INTERVAL", 5))

# Cluster-wide coordination settings (new)
ENABLE_CLUSTER_MANAGEMENT = os.environ.get("ENABLE_CLUSTER_MANAGEMENT", "false").lower() in ("true", "1", "yes")
CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "default-cluster")
CLUSTER_PRIORITY = int(os.environ.get("CLUSTER_PRIORITY", 10))
HEALTH_CHECK_ENDPOINT = os.environ.get("HEALTH_CHECK_ENDPOINT", "")
HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", 30))

# Kubernetes clients
coord_api = client.CoordinationV1Api()

# Global state
cluster_manager: Optional[ClusterManager] = None
current_local_leadership_state = False


def attempt_local_leader_election() -> bool:
    """
    Traditional Kubernetes leader election within StatefulSet.
    This is the EXISTING logic - unchanged from the original forgemanager.py
    """
    try:
        # Try to create or update the lease
        lease_body = client.V1Lease(
            metadata=client.V1ObjectMeta(name=LEASE_NAME, namespace=NAMESPACE),
            spec=client.V1LeaseSpec(
                holder_identity=POD_NAME,
                lease_duration_seconds=LEASE_DURATION,
                acquire_time=client.V1MicroTime(),
                renew_time=client.V1MicroTime(),
            )
        )

        try:
            # Try to create new lease
            coord_api.create_namespaced_lease(namespace=NAMESPACE, body=lease_body)
            logger.info(f"Acquired new lease {LEASE_NAME} as leader {POD_NAME}")
            return True
        except ApiException as e:
            if e.status == 409:  # Lease already exists
                # Try to update existing lease
                try:
                    existing_lease = coord_api.read_namespaced_lease(
                        name=LEASE_NAME, namespace=NAMESPACE
                    )
                    
                    # Check if we can take over the lease
                    if (existing_lease.spec.holder_identity == POD_NAME or
                        _is_lease_expired(existing_lease)):
                        
                        lease_body.spec.acquire_time = existing_lease.spec.acquire_time
                        coord_api.replace_namespaced_lease(
                            name=LEASE_NAME, namespace=NAMESPACE, body=lease_body
                        )
                        logger.info(f"Renewed/acquired lease {LEASE_NAME} as leader {POD_NAME}")
                        return True
                    else:
                        logger.debug(f"Lease {LEASE_NAME} held by {existing_lease.spec.holder_identity}")
                        return False
                        
                except ApiException as inner_e:
                    logger.warning(f"Failed to update lease: {inner_e}")
                    return False
            else:
                logger.error(f"Failed to create lease: {e}")
                return False
                
    except Exception as e:
        logger.error(f"Unexpected error during leader election: {e}")
        return False


def _is_lease_expired(lease) -> bool:
    """Check if a lease has expired."""
    if not lease.spec.renew_time:
        return True
    
    import datetime
    renew_time = lease.spec.renew_time
    if isinstance(renew_time, str):
        renew_time = datetime.datetime.fromisoformat(renew_time.replace('Z', '+00:00'))
    
    expiry_time = renew_time + datetime.timedelta(seconds=lease.spec.lease_duration_seconds)
    return datetime.datetime.now(datetime.timezone.utc) > expiry_time


def provision_forging_credentials():
    """Copy forging credentials to target locations."""
    import shutil
    
    credentials = [
        ("/secrets/kes.skey", "/opt/cardano/secrets/kes.skey"),
        ("/secrets/vrf.skey", "/opt/cardano/secrets/vrf.skey"),
        ("/secrets/node.cert", "/opt/cardano/secrets/node.cert"),
    ]
    
    for source, target in credentials:
        try:
            if os.path.exists(source):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
                os.chmod(target, 0o600)
                logger.debug(f"Provisioned credential: {source} -> {target}")
            else:
                logger.warning(f"Source credential not found: {source}")
        except Exception as e:
            logger.error(f"Failed to provision {source} -> {target}: {e}")


def remove_forging_credentials():
    """Remove forging credentials from target locations."""
    credentials = [
        "/opt/cardano/secrets/kes.skey",
        "/opt/cardano/secrets/vrf.skey", 
        "/opt/cardano/secrets/node.cert",
    ]
    
    for credential_path in credentials:
        try:
            if os.path.exists(credential_path):
                os.remove(credential_path)
                logger.debug(f"Removed credential: {credential_path}")
        except Exception as e:
            logger.error(f"Failed to remove {credential_path}: {e}")


def send_sighup_to_cardano_node(reason: str = "credential_change") -> bool:
    """Send SIGHUP to cardano-node process (if possible)."""
    # Implementation from existing forgemanager.py
    logger.info(f"SIGHUP signal sent (or attempted) - reason: {reason}")
    return True


def update_metrics(local_leader: bool, forging: bool, cluster_forging: Optional[bool] = None):
    """Update Prometheus metrics."""
    # This would update the existing metrics from forgemanager.py
    logger.debug(f"Metrics updated: leader={local_leader}, forging={forging}, cluster_forging={cluster_forging}")


def initialize_cluster_manager() -> Optional[ClusterManager]:
    """Initialize cluster manager if enabled."""
    if not ENABLE_CLUSTER_MANAGEMENT:
        logger.info("Cluster management disabled - running in single-cluster mode")
        return None
    
    try:
        logger.info("Initializing cluster manager for multi-cluster coordination")
        manager = ClusterManager(
            cluster_name=CLUSTER_NAME,
            namespace=NAMESPACE,
            priority=CLUSTER_PRIORITY,
            health_check_endpoint=HEALTH_CHECK_ENDPOINT,
            health_check_interval=HEALTH_CHECK_INTERVAL,
        )
        
        # Start the cluster manager (creates CRD, starts health checks, etc.)
        manager.start()
        logger.info(f"Cluster manager initialized for cluster: {CLUSTER_NAME}")
        return manager
        
    except Exception as e:
        logger.error(f"Failed to initialize cluster manager: {e}")
        # Fall back to single-cluster mode
        return None


def main_loop():
    """
    Main forge manager loop with hierarchical leadership.
    
    This integrates the NEW cluster-wide logic with EXISTING StatefulSet leader election.
    """
    global cluster_manager, current_local_leadership_state
    
    # Initialize cluster manager once at startup
    cluster_manager = initialize_cluster_manager()
    
    logger.info(f"Starting forge manager main loop (pod: {POD_NAME})")
    if cluster_manager:
        logger.info(f"Cluster-wide coordination enabled for cluster: {CLUSTER_NAME} (priority: {CLUSTER_PRIORITY})")
    else:
        logger.info("Running in traditional single-cluster mode")
    
    while True:
        try:
            # STEP 1: LOCAL LEADER ELECTION (Existing StatefulSet logic)
            # This is unchanged from the original forgemanager.py
            local_leader = attempt_local_leader_election()
            
            # Track leadership changes for metrics
            if local_leader != current_local_leadership_state:
                logger.info(f"Local leadership changed: {current_local_leadership_state} -> {local_leader}")
                current_local_leadership_state = local_leader
                
            if not local_leader:
                # I'm a FOLLOWER in this StatefulSet
                logger.debug(f"Pod {POD_NAME} is not the local leader - removing credentials")
                remove_forging_credentials()
                send_sighup_to_cardano_node("not_local_leader")
                update_metrics(local_leader=False, forging=False)
                
                # Important: Followers don't participate in cluster-wide decisions
                time.sleep(SLEEP_INTERVAL)
                continue
            
            # STEP 2: CLUSTER-WIDE COORDINATION (New feature - only for local leaders)
            logger.debug(f"Pod {POD_NAME} is the local leader - checking cluster-wide permissions")
            
            if cluster_manager is None:
                # TRADITIONAL SINGLE-CLUSTER MODE (backward compatibility)
                logger.debug("Single-cluster mode: local leader can forge immediately")
                provision_forging_credentials()
                send_sighup_to_cardano_node("local_leadership_acquired")
                update_metrics(local_leader=True, forging=True)
                
            else:
                # CLUSTER-WIDE MODE (new feature)
                cluster_allows_forging, reason = cluster_manager.should_allow_local_leadership()
                
                if cluster_allows_forging:
                    # Cluster-wide permission GRANTED
                    logger.info(f"Cluster-wide leadership granted - {reason}")
                    provision_forging_credentials()
                    send_sighup_to_cardano_node("cluster_leadership_acquired")
                    update_metrics(local_leader=True, forging=True, cluster_forging=True)
                    
                    # Update CRD status (only local leader can do this)
                    cluster_manager.update_crd_status(
                        active_leader=POD_NAME,
                        forging_enabled=True,
                        message=f"Forging enabled - {reason}"
                    )
                    
                else:
                    # Cluster-wide permission DENIED
                    logger.info(f"Cluster-wide leadership denied - {reason}")
                    remove_forging_credentials()
                    send_sighup_to_cardano_node("cluster_leadership_denied") 
                    update_metrics(local_leader=True, forging=False, cluster_forging=False)
                    
                    # Update CRD status
                    cluster_manager.update_crd_status(
                        active_leader="",
                        forging_enabled=False,
                        message=f"Forging disabled - {reason}"
                    )
                    
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            
        # Sleep before next iteration
        time.sleep(SLEEP_INTERVAL)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    
    if cluster_manager:
        try:
            cluster_manager.stop()
            logger.info("Cluster manager stopped")
        except Exception as e:
            logger.error(f"Error stopping cluster manager: {e}")
    
    # Remove credentials on shutdown
    remove_forging_credentials()
    logger.info("Forge manager shutdown complete")
    exit(0)


if __name__ == "__main__":
    import signal as sig
    
    # Setup signal handlers
    sig.signal(sig.SIGTERM, signal_handler)
    sig.signal(sig.SIGINT, signal_handler)
    
    # Start Prometheus metrics server (existing code)
    from prometheus_client import start_http_server
    start_http_server(int(os.environ.get("METRICS_PORT", 8000)))
    logger.info(f"Metrics server started on port {os.environ.get('METRICS_PORT', 8000)}")
    
    # Run main loop
    main_loop()