#!/usr/bin/env python3
# src/forgemanager.py
"""
Cardano Forge Manager - Kubernetes Sidecar for Dynamic Block Producer Leadership

This sidecar manages leader election, credential distribution, and process signaling
for Cardano block producer nodes running in Kubernetes.
"""

import os
import time
import logging
import shutil
import stat
import signal
import threading
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone, timedelta

# Third-party imports
import psutil
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from prometheus_client import start_http_server, Gauge, Counter, Info

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
    "cardano_forging_enabled", "Whether this pod is actively forging blocks", ["pod"]
)
leader_status = Gauge(
    "cardano_leader_status", "Whether this pod is the elected leader", ["pod"]
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

# Initialize info metric
info_metric.info({"pod_name": POD_NAME, "namespace": NAMESPACE, "version": "1.0.0"})

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

# -----------------------------
# Global State
# -----------------------------
current_leadership_state = False
last_socket_check = 0
cardano_node_pid: Optional[int] = None
node_startup_phase = True  # Track if node is in startup phase
startup_credentials_provisioned = False  # Track if startup credentials are provided

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
        logger.debug(f"Cannot find {CARDANO_NODE_PROCESS_NAME} process - likely in different container")
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
        logger.info(f"Cannot send SIGHUP to cardano-node (cross-container setup) - reason: {reason}")
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
        logger.info(f"Assuming cross-container setup - credentials updated without SIGHUP - reason: {reason}")
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
            node_startup_phase = True
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
                    logger.info("Running in cross-container mode - process signaling not available")
                
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


def update_leader_status(is_leader: bool):
    """Update CardanoLeader CRD status with current leadership state."""
    status_body = {
        "status": {
            "leaderPod": POD_NAME if is_leader else "",
            "forgingEnabled": is_leader,
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
            f"CRD status updated: leader={POD_NAME if is_leader else 'none'}, forgingEnabled={is_leader}"
        )
    except ApiException as e:
        logger.error(f"Failed to update CRD status: {e}")


def update_metrics(is_leader: bool):
    """Update Prometheus metrics with current state."""
    leader_status.labels(pod=POD_NAME).set(1 if is_leader else 0)
    forging_enabled.labels(pod=POD_NAME).set(1 if is_leader else 0)
    logger.debug(f"Metrics updated: leader={is_leader}, forging={is_leader}")


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


def wait_for_socket(timeout: int = None) -> bool:
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
    """Ensure credential state matches leadership status."""
    credentials_changed = False

    # Define credential files using direct environment variables
    credential_files = [
        (SOURCE_KES_KEY, TARGET_KES_KEY, "kes"),
        (SOURCE_VRF_KEY, TARGET_VRF_KEY, "vrf"),
        (SOURCE_OP_CERT, TARGET_OP_CERT, "opcert"),
    ]
    if is_leader:
        logger.info("Ensuring credentials are present for leader")
        for src, dest, file_type in credential_files:
            if not os.path.exists(dest) or not files_identical(src, dest):
                if copy_secret(src, dest, file_type):
                    credentials_changed = True
    else:
        logger.info("Ensuring credentials are absent for non-leader")
        for _, dest, file_type in credential_files:
            if os.path.exists(dest):
                if remove_file(dest, file_type):
                    credentials_changed = True

    # Send SIGHUP if credentials changed
    if credentials_changed and send_sighup:
        reason = "enable_forging" if is_leader else "disable_forging"
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
    from kubernetes.client import V1Lease, V1ObjectMeta, V1LeaseSpec

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
    """Update lease with current timestamp."""
    lease.spec.renew_time = datetime.now(timezone.utc).isoformat()
    return coord_api.patch_namespaced_lease(
        name=LEASE_NAME, namespace=NAMESPACE, body=lease
    )


def try_acquire_leader() -> bool:
    """Attempt to acquire leadership via lease mechanism."""
    global current_leadership_state

    try:
        lease = get_lease()
        now = datetime.now(timezone.utc)

        if not lease:
            lease = create_lease()

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

        # Try to acquire if lease is expired, vacant, or we already hold it
        if expired or holder == "" or holder == POD_NAME:
            old_holder = holder
            lease.spec.holder_identity = POD_NAME
            lease.spec.renew_time = now.isoformat()

            try:
                patch_lease(lease)
                new_leader = True

                # Log leadership transition
                if old_holder != POD_NAME:
                    leadership_changes_total.inc()
                    logger.info(
                        f"Leadership acquired by {POD_NAME} (previous: {old_holder or 'vacant'})"
                    )
                    current_leadership_state = True
                else:
                    logger.debug(f"Leadership renewed by {POD_NAME}")

                return True

            except ApiException as e:
                if e.status == 409:  # Conflict - someone else got it
                    logger.debug(f"Failed to acquire lease due to conflict (409)")
                    new_leader = False
                else:
                    logger.error(f"Unexpected error acquiring lease: {e}")
                    raise
        else:
            new_leader = False

        # Check if we lost leadership
        if current_leadership_state and holder != POD_NAME:
            leadership_changes_total.inc()
            logger.info(f"Leadership lost to {holder}")
            current_leadership_state = False

        return holder == POD_NAME

    except Exception as e:
        logger.error(f"Error in leader election: {e}")
        return False


# -----------------------------
# Metrics Server
# -----------------------------


def start_metrics_server():
    """Start Prometheus metrics server in background thread."""
    try:
        start_http_server(METRICS_PORT)
        logger.info(f"Prometheus metrics server started on port {METRICS_PORT}")
    except Exception as e:
        logger.error(f"Failed to start metrics server on port {METRICS_PORT}: {e}")
        raise


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
                    # Sleep and check again
                    time.sleep(SLEEP_INTERVAL)
                    continue
                
                logger.debug("Node startup phase complete - proceeding with leader election")

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
                is_leader = try_acquire_leader()
                logger.debug(f"Leadership acquisition result: {is_leader}")

                # Ensure credential state matches leadership (normal operation)
                logger.debug(f"Ensuring secrets for leader status: {is_leader}")
                credentials_changed = ensure_secrets(is_leader)
                if credentials_changed:
                    logger.info(f"Credentials {'provisioned' if is_leader else 'removed'} for leadership status")

                # Update status and metrics
                logger.debug("Updating CRD status and metrics")
                update_leader_status(is_leader)
                update_metrics(is_leader)

                # Sleep until next iteration
                time.sleep(SLEEP_INTERVAL)

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
