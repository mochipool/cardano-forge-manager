#!/usr/bin/env python3
# src/forgemanager.py
"""
Cardano Forge Manager - Kubernetes Sidecar for Dynamic Block Producer Leadership

This sidecar manages leader election, credential distribution, and process signaling
for Cardano block producer nodes running in Kubernetes.
"""

import logging
import os
import psutil
import random
import shutil
import signal
import stat
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlparse
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from prometheus_client import Counter, Gauge, Info, start_http_server, generate_latest

# Cluster management (extension)
import cluster_manager

# -----------------------------
# Environment variables
# -----------------------------
NAMESPACE = os.environ.get("NAMESPACE", "default")
POD_NAME = os.environ.get("POD_NAME", "")
CRD_GROUP = os.environ.get("CRD_GROUP", "cardano.io")
CRD_VERSION = os.environ.get("CRD_VERSION", "v1")
CRD_PLURAL = os.environ.get("CRD_PLURAL", "cardanoleaders")
CRD_NAME = os.environ.get("CRD_NAME", "cardano-leader")
SLEEP_INTERVAL = int(os.environ.get("SLEEP_INTERVAL", 5))
NODE_SOCKET = os.environ.get("NODE_SOCKET", "/ipc/node.socket")
SOCKET_WAIT_TIMEOUT = int(os.environ.get("SOCKET_WAIT_TIMEOUT", 600))
DISABLE_SOCKET_CHECK = os.environ.get("DISABLE_SOCKET_CHECK", "false").lower() in (
    "true",
    "1",
    "yes",
)
LEASE_NAME = os.environ.get("LEASE_NAME", "cardano-node-leader")
LEASE_DURATION = int(os.environ.get("LEASE_DURATION", 15))  # seconds
METRICS_PORT = int(os.environ.get("METRICS_PORT", 8000))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# -----------------------------
# Secrets - Full paths from environment
# -----------------------------
# Source paths (mounted secret volume)
SOURCE_KES_KEY = os.environ.get("SOURCE_KES_KEY", "/secrets/kes.skey")
SOURCE_VRF_KEY = os.environ.get("SOURCE_VRF_KEY", "/secrets/vrf.skey")
SOURCE_OP_CERT = os.environ.get("SOURCE_OP_CERT", "/secrets/node.cert")

# Target paths (where cardano-node expects them)
TARGET_KES_KEY = os.environ.get("TARGET_KES_KEY", "/opt/cardano/secrets/kes.skey")
TARGET_VRF_KEY = os.environ.get("TARGET_VRF_KEY", "/opt/cardano/secrets/vrf.skey")
TARGET_OP_CERT = os.environ.get("TARGET_OP_CERT", "/opt/cardano/secrets/node.cert")

# Process discovery
CARDANO_NODE_PROCESS_NAME = os.environ.get("CARDANO_NODE_PROCESS_NAME", "cardano-node")

# Multi-tenant configuration (for cluster manager integration)
CARDANO_NETWORK = os.environ.get("CARDANO_NETWORK", "mainnet")
POOL_ID = os.environ.get("POOL_ID", "")
POOL_ID_HEX = os.environ.get("POOL_ID_HEX", "")
POOL_NAME = os.environ.get("POOL_NAME", "")
POOL_TICKER = os.environ.get("POOL_TICKER", "")
NETWORK_MAGIC = int(os.environ.get("NETWORK_MAGIC", "764824073"))  # Default to mainnet
APPLICATION_TYPE = os.environ.get("APPLICATION_TYPE", "block-producer")

# -----------------------------
# Logging Setup
# -----------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s",
)
logger = logging.getLogger("cardano-forge-manager")

# -----------------------------
# Prometheus Metrics
# -----------------------------
forging_enabled = Gauge(
    "cardano_forging_enabled",
    "Whether this pod is actively forging blocks",
    ["pod", "network", "pool_id", "application"],
)
leader_status = Gauge(
    "cardano_leader_status",
    "Whether this pod is the elected leader",
    ["pod", "network", "pool_id", "application"],
)
leadership_changes_total = Counter(
    "cardano_leadership_changes_total", "Total number of leadership transitions"
)
sighup_signals_total = Counter(
    "cardano_sighup_signals_total",
    "Total number of SIGHUP signals sent to cardano-node",
    ["reason"],
)
credential_operations_total = Counter(
    "cardano_credential_operations_total",
    "Total number of credential file operations",
    ["operation", "file"],
)
info_metric = Info(
    "cardano_forge_manager_info", "Information about the forge manager instance"
)

# Cluster-wide metrics (extension) - updated for multi-tenant support
cluster_forge_enabled = Gauge(
    "cardano_cluster_forge_enabled",
    "Whether this cluster is enabled for forging",
    ["cluster", "region", "network", "pool_id"],
)
cluster_forge_priority = Gauge(
    "cardano_cluster_forge_priority",
    "Effective priority of this cluster for forging",
    ["cluster", "region", "network", "pool_id"],
)

# Initialize info metric with multi-tenant information
info_metric.info(
    {
        "pod_name": POD_NAME,
        "namespace": NAMESPACE,
        "version": "2.0.0",
        "network": CARDANO_NETWORK,
        "pool_id": POOL_ID or "unknown",
        "pool_ticker": POOL_TICKER or "unknown",
        "application_type": APPLICATION_TYPE,
    }
)

# -----------------------------
# Kubernetes Client Setup
# -----------------------------
try:
    config.load_incluster_config()
    logger.info("Loaded in-cluster Kubernetes configuration")
except Exception:
    config.load_kube_config()
    logger.info("Loaded local Kubernetes configuration")

custom_objects = client.CustomObjectsApi()
coord_api = client.CoordinationV1Api()

# Initialize cluster management
cluster_manager.initialize_cluster_manager(custom_objects, POD_NAME, NAMESPACE)

# -----------------------------
# Global State
# -----------------------------
current_leadership_state = False
previous_leadership_state = None  # Track previous state to prevent unnecessary updates
last_socket_check = 0
cardano_node_pid: Optional[int] = None
node_startup_phase = True  # Track if node is in startup phase
startup_credentials_provisioned = False  # Track if startup credentials are provided
# CRD state tracking to reduce unnecessary updates
last_crd_leader_state = None
last_crd_forging_state = None
# Track whether we've synced our in-memory CRD state with the live CRD
crd_status_initialized = False

# -----------------------------
# Process Management Functions
# -----------------------------


def discover_cardano_node_pid() -> Optional[int]:
    """Discover the cardano-node process PID.

    Note: In multi-container pods, the cardano-node process may be running
    in a different container and not visible via psutil. We'll try to find it
    but if not found, we'll rely on socket-based detection instead.
    """
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            if proc.info["name"] == CARDANO_NODE_PROCESS_NAME:
                logger.debug(
                    f"Found {CARDANO_NODE_PROCESS_NAME} process with PID {proc.info['pid']}"
                )
                return proc.info["pid"]
            # Also check command line for cardano-node
            if proc.info["cmdline"] and any(
                CARDANO_NODE_PROCESS_NAME in arg for arg in proc.info["cmdline"]
            ):
                logger.debug(
                    f"Found {CARDANO_NODE_PROCESS_NAME} in cmdline with PID {proc.info['pid']}"
                )
                return proc.info["pid"]

        # If not found, log this as debug (not error) since it's expected in multi-container setups
        logger.debug(
            f"Cannot find {CARDANO_NODE_PROCESS_NAME} process - likely in different container"
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.warning(f"Error discovering cardano-node process: {e}")
    except Exception as e:
        logger.error(f"Unexpected error discovering cardano-node process: {e}")
    return None


def send_sighup_to_cardano_node(reason: str = "credential_change") -> bool:
    """Send SIGHUP signal to cardano-node process.

    In multi-container setups, the cardano-node process is not visible to this container,
    so SIGHUP signaling is not possible. Log this information but don't treat as error.
    """
    global cardano_node_pid

    # Refresh PID if not cached or process doesn't exist
    if cardano_node_pid is None or not psutil.pid_exists(cardano_node_pid):
        cardano_node_pid = discover_cardano_node_pid()

    if cardano_node_pid is None:
        logger.info(
            f"Cannot send SIGHUP to cardano-node (cross-container setup) - reason: {reason}"
        )
        # In multi-container setups, we can't signal the process directly
        # The credential changes should still take effect when the node reads them
        sighup_signals_total.labels(reason=f"{reason}_skipped").inc()
        return True  # Return True because this is expected behavior

    try:
        os.kill(cardano_node_pid, signal.SIGHUP)
        sighup_signals_total.labels(reason=reason).inc()
        logger.info(
            f"Sent SIGHUP to cardano-node (PID {cardano_node_pid}) - reason: {reason}"
        )
        return True
    except ProcessLookupError:
        logger.warning(
            f"cardano-node process (PID {cardano_node_pid}) not found - refreshing PID cache"
        )
        cardano_node_pid = None  # Clear cached PID
        # Retry once with cross-container assumption
        logger.info(
            f"Assuming cross-container setup - credentials updated without SIGHUP - reason: {reason}"
        )
        sighup_signals_total.labels(reason=f"{reason}_cross_container").inc()
        return True
    except PermissionError:
        logger.error(f"Permission denied sending SIGHUP to PID {cardano_node_pid}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending SIGHUP to PID {cardano_node_pid}: {e}")
        return False


def is_node_in_startup_phase() -> bool:
    """Detect if cardano-node is in startup phase vs running normally.

    In multi-container setups, we rely primarily on socket existence and stability
    rather than process discovery since we can't see the cardano-node process.
    """
    global node_startup_phase, cardano_node_pid

    # If socket doesn't exist, node is definitely in startup
    if not os.path.exists(NODE_SOCKET):
        if not node_startup_phase:
            logger.info("Node socket disappeared - node entering startup/restart phase")
            # Forfeit leadership immediately when node dies/restarts
            forfeit_leadership()
            node_startup_phase = True
            # Reset startup credentials flag to ensure they get provisioned again
            global startup_credentials_provisioned
            startup_credentials_provisioned = False
            # Clear cached PID since the process likely died
            cardano_node_pid = None
        return True

    # If we were in startup phase and socket now exists, check if it's stable
    if node_startup_phase:
        try:
            # Check that it's actually a socket
            if stat.S_ISSOCK(os.stat(NODE_SOCKET).st_mode):
                logger.info("Node startup phase complete - socket is ready and stable")
                node_startup_phase = False

                # Try to discover PID for potential signaling, but don't require it
                current_pid = discover_cardano_node_pid()
                if current_pid:
                    cardano_node_pid = current_pid
                    logger.debug(f"Cached cardano-node PID: {current_pid}")
                else:
                    logger.info(
                        "Running in cross-container mode - process signaling not available"
                    )

                return False
            else:
                logger.debug(f"File {NODE_SOCKET} exists but is not a socket")
                return True
        except Exception as e:
            logger.debug(f"Socket stability check failed: {e}")
            return True

    return node_startup_phase


def provision_startup_credentials() -> bool:
    """Provision credentials needed for node startup, regardless of leadership."""
    global startup_credentials_provisioned

    logger.info("Provisioning credentials for node startup")

    # Define credential files
    credential_files = [
        (SOURCE_KES_KEY, TARGET_KES_KEY, "kes"),
        (SOURCE_VRF_KEY, TARGET_VRF_KEY, "vrf"),
        (SOURCE_OP_CERT, TARGET_OP_CERT, "opcert"),
    ]

    success = True
    for src, dest, file_type in credential_files:
        if not os.path.exists(dest):
            if not copy_secret(src, dest, file_type):
                success = False
        else:
            logger.debug(f"Startup credential {dest} already exists")

    if success:
        startup_credentials_provisioned = True
        logger.info("Startup credentials provisioned successfully")
    else:
        logger.error("Failed to provision all startup credentials")

    return success


# -----------------------------
# Helper Functions
# -----------------------------


def forfeit_leadership():
    """Forfeit current leadership due to node restart/failure."""
    global current_leadership_state

    if not current_leadership_state:
        return  # Nothing to forfeit

    logger.warning("Forfeiting leadership due to cardano-node restart")

    # Clear leadership state immediately
    current_leadership_state = False
    leadership_changes_total.inc()

    # Clean up credentials immediately
    ensure_secrets(is_leader=False, send_sighup=False)

    # Check current CRD status before clearing to avoid race condition
    # Only clear if we're still shown as the leader in the CRD
    try:
        current_crd = custom_objects.get_namespaced_custom_object_status(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=NAMESPACE,
            plural=CRD_PLURAL,
            name=CRD_NAME,
        )

        # Check if we're still the recorded leader
        current_leader = current_crd.get("status", {}).get("leaderPod", "")

        if current_leader != POD_NAME:
            logger.info(
                f"Not clearing CRD status - another pod ({current_leader or 'none'}) is now leader"
            )
            # Update local metrics but don't touch CRD
            update_metrics(is_leader=False)
            return

        # We're still the recorded leader, safe to clear the status
        logger.info(
            f"Clearing CRD status - we ({POD_NAME}) are still the recorded leader"
        )

    except ApiException as e:
        if e.status == 404:
            logger.info("CRD not found during leadership forfeiture - nothing to clear")
            update_metrics(is_leader=False)
            return
        else:
            logger.warning(f"Could not check CRD status during forfeiture: {e}")
            logger.info("Proceeding with caution to clear status anyway")

    # Update CRD to clear leadership status
    status_body = {
        "status": {
            "leaderPod": "",
            "forgingEnabled": False,
            "lastTransitionTime": datetime.now(timezone.utc).isoformat(),
        }
    }
    try:
        custom_objects.patch_namespaced_custom_object_status(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=NAMESPACE,
            plural=CRD_PLURAL,
            name=CRD_NAME,
            body=status_body,
        )
        logger.info("Leadership forfeited - CRD status cleared")
    except ApiException as e:
        logger.error(f"Failed to clear CRD status during leadership forfeiture: {e}")

    # Update local metrics
    update_metrics(is_leader=False)


def update_leader_status(is_leader: bool):
    """Update CardanoLeader CRD status with current leadership and forging state.
    
    CRITICAL: If we hold the lease (is_leader=True), we MUST write our pod name to the CRD.
    This ensures the CRD always reflects the current lease holder, regardless of previous state.
    Non-leaders should not overwrite the CRD unless they need to clear stale data.
    """
    # Get forging permission from cluster manager
    forging_allowed, forging_reason = cluster_manager.should_allow_forging()
    # Only forge if we're leader AND cluster allows forging
    forging_enabled = is_leader and forging_allowed
    
    # If we're the leader, ALWAYS update CRD with our pod name
    # If we're not the leader, only update if we need to clear our own stale entry
    should_update = False
    
    if is_leader:
        # ALWAYS update when we hold the lease - this is the source of truth
        should_update = True
        logger.debug(f"Leader update: Writing {POD_NAME} to CRD (forging: {forging_enabled})")
    else:
        # Non-leader: Check if CRD incorrectly shows us as leader and clear it
        try:
            current_crd = custom_objects.get_namespaced_custom_object_status(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=NAMESPACE,
                plural=CRD_PLURAL,
                name=CRD_NAME,
            )
            live_status = current_crd.get("status", {}) if isinstance(current_crd, dict) else {}
            live_leader = live_status.get("leaderPod", "")
            
            if live_leader == POD_NAME:
                # CRD incorrectly shows us as leader - we must clear it
                should_update = True
                logger.info(f"Non-leader cleanup: Clearing stale {POD_NAME} from CRD")
            else:
                # CRD doesn't show us as leader - no update needed
                logger.debug(f"Non-leader: CRD shows {live_leader or 'none'} as leader, no update needed")
        except ApiException as e:
            if e.status == 404:
                logger.debug("CRD not found; non-leader skipping update")
            else:
                logger.warning(f"Could not read CRD status as non-leader: {e}")
    
    if not should_update:
        return
    
    status_body = {
        "status": {
            "leaderPod": POD_NAME if is_leader else "",
            "forgingEnabled": forging_enabled,
            "lastTransitionTime": datetime.now(timezone.utc).isoformat(),
        }
    }
    try:
        custom_objects.patch_namespaced_custom_object_status(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=NAMESPACE,
            plural=CRD_PLURAL,
            name=CRD_NAME,
            body=status_body,
        )
        
        logger.info(
            f"CRD status updated: leader={POD_NAME if is_leader else 'none'}, forgingEnabled={forging_enabled} (cluster allows: {forging_allowed}, reason: {forging_reason})"
        )

        # Also update cluster CRD if cluster management is enabled
        cluster_manager.update_cluster_leader_status(
            POD_NAME if is_leader else None, forging_enabled
        )

    except ApiException as e:
        logger.error(f"Failed to update CRD status: {e}")


def update_metrics(is_leader: bool):
    """Update Prometheus metrics with current leadership and forging state."""
    # Get forging permission from cluster manager
    forging_allowed, forging_reason = cluster_manager.should_allow_forging()
    # Only forge if we're leader AND cluster allows forging
    forging_enabled_actual = is_leader and forging_allowed
    
    # Use multi-tenant labels
    pool_id_short = POOL_ID[:10] if POOL_ID else "unknown"
    labels = {
        "pod": POD_NAME,
        "network": CARDANO_NETWORK,
        "pool_id": pool_id_short,
        "application": APPLICATION_TYPE,
    }

    leader_status.labels(**labels).set(1 if is_leader else 0)
    forging_enabled.labels(**labels).set(1 if forging_enabled_actual else 0)

    # Update cluster-wide metrics if available
    cluster_metrics = cluster_manager.get_cluster_metrics()
    if cluster_metrics.get("enabled", False):
        cluster_id = cluster_metrics.get("cluster_id", "unknown")
        region = cluster_metrics.get("region", "unknown")
        network = cluster_metrics.get("network", "unknown")
        pool_id = cluster_metrics.get("pool_id", "unknown")
        pool_id_short = pool_id[:10] if pool_id and pool_id != "unknown" else "unknown"

        cluster_labels = {
            "cluster": cluster_id,
            "region": region,
            "network": network,
            "pool_id": pool_id_short,
        }

        cluster_forge_enabled.labels(**cluster_labels).set(
            1 if cluster_metrics.get("forge_enabled", False) else 0
        )
        cluster_forge_priority.labels(**cluster_labels).set(
            cluster_metrics.get("effective_priority", 999)
        )

    logger.debug(f"Metrics updated: leader={is_leader}, forging={forging_enabled_actual} (cluster allows: {forging_allowed}, reason: {forging_reason})")


def copy_secret(src: str, dest: str, file_type: str) -> bool:
    """Copy secret file with proper permissions and logging."""
    if not os.path.exists(src):
        logger.warning(f"Source secret {src} not found")
        return False

    try:
        # Ensure target directory exists
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        # Copy file
        shutil.copy2(src, dest)

        # Set restrictive permissions (600)
        os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)

        credential_operations_total.labels(operation="copy", file=file_type).inc()
        logger.info(f"Copied secret {src} -> {dest} with permissions 600")
        return True
    except Exception as e:
        logger.error(f"Failed to copy secret {src} -> {dest}: {e}")
        return False


def remove_file(path: str, file_type: str) -> bool:
    """Remove file with logging and metrics."""
    if os.path.exists(path):
        try:
            os.remove(path)
            credential_operations_total.labels(operation="remove", file=file_type).inc()
            logger.info(f"Removed credential file {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove {path}: {e}")
            return False
    else:
        logger.debug(f"File {path} already absent")
        return True


def wait_for_socket(timeout: int = 0) -> bool:
    """Wait for cardano-node socket to exist before proceeding."""
    if DISABLE_SOCKET_CHECK:
        logger.info("Socket check disabled via DISABLE_SOCKET_CHECK")
        return True

    timeout = timeout or SOCKET_WAIT_TIMEOUT
    start_time = time.time()

    logger.info(f"Waiting for node socket: {NODE_SOCKET} (timeout: {timeout}s)")

    while not os.path.exists(NODE_SOCKET):
        if time.time() - start_time > timeout:
            logger.warning(
                f"Timeout waiting for node socket: {NODE_SOCKET} after {timeout}s"
            )
            return False
        time.sleep(1)

    # Additional check that it's actually a socket
    try:
        if stat.S_ISSOCK(os.stat(NODE_SOCKET).st_mode):
            logger.info(f"Node socket found and verified: {NODE_SOCKET}")
            return True
        else:
            logger.warning(f"File {NODE_SOCKET} exists but is not a socket")
            return False
    except Exception as e:
        logger.warning(f"Could not verify socket {NODE_SOCKET}: {e}")
        return True  # Assume it's valid to avoid blocking


def ensure_secrets(is_leader: bool, send_sighup: bool = True) -> bool:
    """Ensure credential state matches forging permission."""
    credentials_changed = False
    
    # Check if we should actually forge (leader + cluster allows forging)
    forging_allowed, forging_reason = cluster_manager.should_allow_forging()
    should_have_credentials = is_leader and forging_allowed

    # Define credential files using direct environment variables
    credential_files = [
        (SOURCE_KES_KEY, TARGET_KES_KEY, "kes"),
        (SOURCE_VRF_KEY, TARGET_VRF_KEY, "vrf"),
        (SOURCE_OP_CERT, TARGET_OP_CERT, "opcert"),
    ]
    
    if should_have_credentials:
        logger.info(f"Ensuring credentials are present for forging (leader: {is_leader}, cluster allows: {forging_allowed}, reason: {forging_reason})")
        for src, dest, file_type in credential_files:
            if not os.path.exists(dest) or not files_identical(src, dest):
                if copy_secret(src, dest, file_type):
                    credentials_changed = True
    else:
        reason = "not leader" if not is_leader else f"cluster disallows forging ({forging_reason})"
        logger.info(f"Ensuring credentials are absent ({reason})")
        for _, dest, file_type in credential_files:
            if os.path.exists(dest):
                if remove_file(dest, file_type):
                    credentials_changed = True

    # Send SIGHUP if credentials changed
    if credentials_changed and send_sighup:
        reason = "enable_forging" if should_have_credentials else "disable_forging"
        send_sighup_to_cardano_node(reason)

    return credentials_changed


def files_identical(file1: str, file2: str) -> bool:
    """Check if two files are identical."""
    try:
        if not (os.path.exists(file1) and os.path.exists(file2)):
            return False

        stat1 = os.stat(file1)
        stat2 = os.stat(file2)

        # Quick size check first
        if stat1.st_size != stat2.st_size:
            return False

        # Compare modification times
        if abs(stat1.st_mtime - stat2.st_mtime) < 1:  # Within 1 second
            return True

        # Fallback to content comparison for small files
        if stat1.st_size < 1024 * 1024:  # 1MB
            with open(file1, "rb") as f1, open(file2, "rb") as f2:
                return f1.read() == f2.read()

        return False
    except Exception:
        return False


def startup_cleanup():
    """Clean up orphaned credentials on startup if not current lease holder."""
    logger.info("Performing startup credential cleanup")

    # Check current lease holder
    lease = get_lease()
    if lease:
        holder = getattr(lease.spec, "holder_identity", "")
        if holder and holder != POD_NAME:
            logger.info(
                f"Current lease holder is {holder}, cleaning up any orphaned credentials"
            )
            cleanup_performed = ensure_secrets(is_leader=False, send_sighup=False)
            if cleanup_performed:
                send_sighup_to_cardano_node("startup_cleanup")
                logger.info("Startup cleanup completed - removed orphaned credentials")
            else:
                logger.info("No orphaned credentials found during startup")
        else:
            logger.info(
                f"This pod ({POD_NAME}) may be the lease holder or lease is vacant"
            )
    else:
        logger.info("No lease found during startup - assuming clean state")


# -----------------------------
# Utility Functions for Lease Stability
# -----------------------------

def calculate_jittered_sleep(base_interval: int, max_jitter_percent: float = 0.2) -> float:
    """Calculate sleep interval with jitter to prevent synchronized wake-ups.
    
    Args:
        base_interval: Base sleep interval in seconds
        max_jitter_percent: Maximum jitter as percentage of base interval (0.0-1.0)
    
    Returns:
        Sleep interval with random jitter applied
    """
    jitter_range = base_interval * max_jitter_percent
    jitter = random.uniform(-jitter_range, jitter_range)
    return max(1.0, base_interval + jitter)  # Ensure minimum 1 second

def calculate_exponential_backoff(attempt: int, base_delay: float = 0.5, max_delay: float = 30.0) -> float:
    """Calculate exponential backoff delay for retry attempts.
    
    Args:
        attempt: Retry attempt number (0-based)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
    
    Returns:
        Backoff delay with jitter
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    # Add jitter to prevent thundering herd
    jitter = random.uniform(0.1, 0.3) * delay
    return delay + jitter

# -----------------------------
# Lease Functions
# -----------------------------


def parse_k8s_time(time_val) -> datetime:
    """Parse Kubernetes timestamp (str or datetime) to timezone-aware datetime (UTC)."""
    if not time_val:
        return datetime.now(timezone.utc)
    # If already datetime, normalize tzinfo
    if isinstance(time_val, datetime):
        return time_val if time_val.tzinfo else time_val.replace(tzinfo=timezone.utc)
    # Otherwise, expect string
    time_str = str(time_val)
    try:
        return datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        try:
            return datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            try:
                # Handle +00:00 timezone format (ISO 8601 with timezone offset)
                return datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%f%z")
            except ValueError:
                try:
                    # Handle +00:00 timezone format without microseconds
                    return datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S%z")
                except ValueError:
                    logger.warning(f"Could not parse timestamp: {time_str}")
                    return datetime.now(timezone.utc)


def get_lease():
    """Get current lease object or None if not found."""
    try:
        return coord_api.read_namespaced_lease(LEASE_NAME, NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            return None
        else:
            logger.error(f"Error reading lease: {e}")
            raise


def create_lease():
    """Create new lease object."""
    from kubernetes.client import V1Lease, V1LeaseSpec, V1ObjectMeta

    now = datetime.now(timezone.utc).isoformat()
    lease = V1Lease(
        metadata=V1ObjectMeta(name=LEASE_NAME),
        spec=V1LeaseSpec(
            holder_identity="",
            lease_duration_seconds=LEASE_DURATION,
            acquire_time=now,
            renew_time=now,
            lease_transitions=0,
        ),
    )
    try:
        created_lease = coord_api.create_namespaced_lease(
            namespace=NAMESPACE, body=lease
        )
        logger.info(f"Created new lease: {LEASE_NAME}")
        return created_lease
    except ApiException as e:
        if e.status == 409:  # Already exists
            logger.info(f"Lease {LEASE_NAME} already exists, retrieving it")
            return get_lease()
        raise


def patch_lease(lease):
    """Update lease with current timestamp using optimistic concurrency control."""
    lease.spec.renew_time = datetime.now(timezone.utc).isoformat()
    
    # Use resource version for optimistic concurrency control
    # This prevents race conditions when multiple pods try to update the same lease
    try:
        return coord_api.patch_namespaced_lease(
            name=LEASE_NAME, namespace=NAMESPACE, body=lease
        )
    except ApiException as e:
        if e.status == 409:  # Conflict due to resource version mismatch
            logger.debug(f"Lease patch conflict (409) - resource version changed")
            raise  # Let the caller handle the conflict
        else:
            logger.error(f"Unexpected error patching lease: {e}")
            raise


def try_acquire_leader() -> bool:
    """Attempt to acquire leadership via lease mechanism with proper race condition handling."""
    global current_leadership_state

    # Note: With the new design, leadership is always allowed for operational visibility.
    # Forging permission is handled separately in ensure_secrets() and update_*() functions.
    # This ensures the CRD is always kept up-to-date even when forging is disabled.

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Always get fresh lease state to avoid stale reads
            lease = get_lease()
            now = datetime.now(timezone.utc)

            if not lease:
                try:
                    lease = create_lease()
                    # If lease creation succeeded, we might be able to claim it
                    # but we need to get the fresh state after creation
                    lease = get_lease()
                except ApiException as e:
                    if e.status == 409:  # Already exists
                        lease = get_lease()  # Get the existing lease
                    else:
                        raise

            if not lease:
                logger.warning("Could not get lease even after creation attempt")
                return False

            holder = getattr(lease.spec, "holder_identity", "")
            lease_duration = int(
                getattr(lease.spec, "lease_duration_seconds", LEASE_DURATION)
            )
            renew_time = getattr(lease.spec, "renew_time", None)

            # Check if lease is expired
            expired = True
            if renew_time:
                renew_time_dt = parse_k8s_time(renew_time)
                expired = (renew_time_dt + timedelta(seconds=lease_duration)) < now

            # Determine if we can/should acquire the lease
            can_acquire = False
            acquisition_reason = ""
            
            if holder == POD_NAME:
                can_acquire = True
                acquisition_reason = "renewal"
            elif expired:
                can_acquire = True
                acquisition_reason = f"expired_lease_from_{holder or 'vacant'}"
            elif holder == "":
                can_acquire = True
                acquisition_reason = "vacant_lease"

            if can_acquire:
                old_holder = holder
                lease.spec.holder_identity = POD_NAME
                lease.spec.renew_time = now.isoformat()
                
                # Increment lease transitions when taking over from another holder
                if old_holder != POD_NAME and old_holder != "":
                    current_transitions = getattr(lease.spec, "lease_transitions", 0)
                    lease.spec.lease_transitions = current_transitions + 1

                try:
                    updated_lease = patch_lease(lease)
                    
                    # Validate that we actually got the lease
                    final_holder = getattr(updated_lease.spec, "holder_identity", "")
                    if final_holder != POD_NAME:
                        logger.warning(f"Lease patch succeeded but holder is {final_holder}, not {POD_NAME}")
                        if current_leadership_state:
                            current_leadership_state = False
                        return False

                    # Log leadership transition only on actual changes
                    if old_holder != POD_NAME:
                        leadership_changes_total.inc()
                        logger.info(
                            f"Leadership acquired by {POD_NAME} (previous: {old_holder or 'vacant'}, reason: {acquisition_reason})"
                        )
                        current_leadership_state = True
                    else:
                        logger.debug(f"Leadership renewed by {POD_NAME}")
                        # Ensure state is consistent
                        current_leadership_state = True

                    return True

                except ApiException as e:
                    if e.status == 409:  # Conflict - someone else got it
                        logger.debug(f"Lease acquisition conflict (409) - attempt {attempt + 1}/{max_retries}")
                        if attempt < max_retries - 1:
                            # Wait with exponential backoff before retrying
                            backoff_delay = calculate_exponential_backoff(attempt)
                            logger.debug(f"Retrying after {backoff_delay:.2f}s backoff")
                            time.sleep(backoff_delay)
                            continue
                        else:
                            logger.debug("Max retries reached for lease acquisition")
                            return False  # Failed to acquire lease after all retries
                    else:
                        logger.error(f"Unexpected error acquiring lease: {e}")
                        raise
            else:
                # Cannot acquire lease - check if we lost leadership
                if current_leadership_state and holder != POD_NAME:
                    leadership_changes_total.inc()
                    logger.info(f"Leadership lost to {holder}")
                    current_leadership_state = False

            # If we reach here, we don't hold the lease
            final_result = holder == POD_NAME
            
            # Validate consistency between lease holder and our state
            if final_result != current_leadership_state:
                logger.debug(f"Leadership state inconsistency detected: holder={holder}, pod={POD_NAME}, current_state={current_leadership_state}")
                # Update state to match reality
                current_leadership_state = final_result
                if not final_result and previous_leadership_state:
                    logger.info(f"Leadership state corrected: we no longer hold the lease (holder: {holder})")
            
            return final_result

        except Exception as e:
            logger.error(f"Error in leader election attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                backoff_delay = calculate_exponential_backoff(attempt, base_delay=1.0)
                logger.debug(f"Retrying after error backoff: {backoff_delay:.2f}s")
                time.sleep(backoff_delay)
                continue
            else:
                logger.error(f"Leader election failed after {max_retries} attempts")
                return False

    # Fallback - should not reach here
    return current_leadership_state


# -----------------------------
# HTTP Server for Metrics and Startup Status
# -----------------------------


class ForgeManagerHTTPHandler(BaseHTTPRequestHandler):
    """Custom HTTP handler that serves both Prometheus metrics and startup status."""
    
    def do_GET(self):
        """Handle GET requests for metrics and startup status."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == "/metrics":
            # Serve Prometheus metrics
            try:
                metrics_data = generate_latest()
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
                self.end_headers()
                self.wfile.write(metrics_data)
            except Exception as e:
                logger.error(f"Error generating metrics: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Error generating metrics')
        
        elif path == "/startup-status":
            # Serve startup status for startupProbe
            try:
                is_ready = check_startup_credentials_ready()
                if is_ready:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = {
                        "status": "ready",
                        "message": "Startup credentials provisioned successfully",
                        "credentials_provisioned": startup_credentials_provisioned,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    import json
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_response(503)  # Service Unavailable
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = {
                        "status": "not_ready",
                        "message": "Startup credentials not yet provisioned",
                        "credentials_provisioned": startup_credentials_provisioned,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    import json
                    self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                logger.error(f"Error checking startup status: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Error checking startup status')
        
        elif path == "/health":
            # Simple health check endpoint
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        
        else:
            # 404 for unknown paths
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        logger.debug(f"HTTP: {format % args}")


def check_startup_credentials_ready() -> bool:
    """Check if startup credentials are ready for cardano-node.
    
    Returns True if:
    1. startup_credentials_provisioned flag is True, OR
    2. All required credential files exist at their target locations
    """
    global startup_credentials_provisioned
    
    # If the flag is set, we're ready
    if startup_credentials_provisioned:
        return True
    
    # Check if all required credential files exist
    required_files = [TARGET_KES_KEY, TARGET_VRF_KEY, TARGET_OP_CERT]
    
    try:
        for file_path in required_files:
            if not os.path.exists(file_path):
                logger.debug(f"Startup credential not ready: {file_path} does not exist")
                return False
            
            # Check that the file is readable and not empty
            stat_info = os.stat(file_path)
            if stat_info.st_size == 0:
                logger.debug(f"Startup credential not ready: {file_path} is empty")
                return False
        
        logger.debug("All startup credentials are present and non-empty")
        return True
        
    except Exception as e:
        logger.debug(f"Error checking startup credentials: {e}")
        return False


def start_metrics_server():
    """Start HTTP server for both Prometheus metrics and startup status."""
    def run_server():
        try:
            server = HTTPServer(('0.0.0.0', METRICS_PORT), ForgeManagerHTTPHandler)
            logger.info(f"HTTP server started on port {METRICS_PORT} (metrics: /metrics, startup: /startup-status)")
            server.serve_forever()
        except Exception as e:
            logger.error(f"HTTP server error: {e}")
    
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Give server a moment to start
    time.sleep(0.5)


# -----------------------------
# Main Loop
# -----------------------------


def main():
    """Main application loop."""
    global startup_credentials_provisioned

    logger.info(
        f"Starting Cardano Forge Manager for pod {POD_NAME} in namespace {NAMESPACE}"
    )

    # Start metrics server
    start_metrics_server()

    # Initialize metrics to 0
    update_metrics(is_leader=False)

    # Handle startup phase - provision credentials before node startup
    if not provision_startup_credentials():
        logger.error("Failed to provision startup credentials - node may fail to start")

    # Wait for node socket on startup
    logger.info("Waiting for cardano-node to be ready...")
    if not wait_for_socket():
        logger.error("Cardano node failed to start within timeout - continuing anyway")

    # Check if node startup is complete
    in_startup = is_node_in_startup_phase()

    # Perform startup cleanup only after node is running
    if not in_startup:
        startup_cleanup()

    logger.info(f"Starting main leadership election loop (interval: {SLEEP_INTERVAL}s)")

    try:
        while True:
            try:
                # Check node startup state
                in_startup = is_node_in_startup_phase()

                if in_startup:
                    logger.debug(
                        "Node in startup phase - maintaining startup credentials"
                    )
                    # During startup, ensure credentials exist but don't do leader election
                    if not startup_credentials_provisioned:
                        provision_startup_credentials()

                    # No SIGHUP during startup phase
                    # Sleep and check again (with jitter even during startup)
                    startup_sleep = calculate_jittered_sleep(SLEEP_INTERVAL)
                    time.sleep(startup_sleep)
                    continue

                logger.debug(
                    "Node startup phase complete - proceeding with leader election"
                )

                # Node is running normally - perform leader election
                if startup_credentials_provisioned:
                    logger.info(
                        "Node startup complete - beginning normal leadership election"
                    )
                    startup_credentials_provisioned = False  # Reset flag
                    # Perform delayed startup cleanup now that node is stable
                    startup_cleanup()

                # Try to acquire leadership
                logger.debug("Attempting to acquire leadership...")
                previous_leadership_state = current_leadership_state  # Track previous state
                is_leader = try_acquire_leader()
                logger.debug(f"Leadership acquisition result: {is_leader}")

                # Ensure credential state matches leadership (normal operation)
                logger.debug(f"Ensuring secrets for leader status: {is_leader}")
                credentials_changed = ensure_secrets(is_leader)
                if credentials_changed:
                    logger.info(
                        f"Credentials {'provisioned' if is_leader else 'removed'} for leadership status"
                    )

                # Update status and metrics
                logger.debug("Updating CRD status and metrics")
                update_leader_status(is_leader)
                update_metrics(is_leader)

                # Sleep until next iteration with jitter to prevent synchronized wake-ups
                jittered_sleep = calculate_jittered_sleep(SLEEP_INTERVAL)
                logger.debug(f"Sleeping for {jittered_sleep:.2f}s (base: {SLEEP_INTERVAL}s + jitter)")
                time.sleep(jittered_sleep)

            except KeyboardInterrupt:
                logger.info("Received interrupt signal, shutting down gracefully")
                break
            except Exception as e:
                logger.error(f"Error in main loop iteration: {e}")
                # Continue running but sleep a bit longer on errors
                time.sleep(min(SLEEP_INTERVAL * 2, 30))

    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    finally:
        # Cleanup on shutdown
        if current_leadership_state:
            logger.info("Cleaning up credentials before shutdown")
            ensure_secrets(is_leader=False)

        # Stop cluster management
        cluster_mgr = cluster_manager.get_cluster_manager()
        if cluster_mgr:
            cluster_mgr.stop()

        logger.info("Cardano Forge Manager shutdown complete")


def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    # The main loop will handle cleanup via KeyboardInterrupt
    raise KeyboardInterrupt


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Validate required environment variables
    if not POD_NAME:
        logger.error("POD_NAME environment variable is required")
        exit(1)
    if not NAMESPACE:
        logger.error("NAMESPACE environment variable is required")
        exit(1)

    main()
