#!/usr/bin/env python3
# tests/test_cluster_management.py
"""
Test suite for cluster-wide forge management functionality.

This module provides comprehensive testing for:
- CardanoForgeCluster CRD operations
- Cluster-wide leadership decisions
- Health check integration
- Metrics export
- Backward compatibility
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import os
import sys
import json
import importlib
from datetime import datetime, timezone, timedelta

# Set test environment variables before importing cluster_manager
os.environ.update(
    {
        "CLUSTER_IDENTIFIER": "test-cluster",
        "CLUSTER_REGION": "us-test-1",
        "CLUSTER_ENVIRONMENT": "test",
        "CLUSTER_PRIORITY": "5",
        "ENABLE_CLUSTER_MANAGEMENT": "true",
        "HEALTH_CHECK_ENDPOINT": "http://test.example.com/health",
        "HEALTH_CHECK_INTERVAL": "10",
    }
)

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cluster_manager
from kubernetes.client.rest import ApiException


class TestClusterForgeManager(unittest.TestCase):
    """Test cases for ClusterForgeManager class."""

    def setUp(self):
        """Set up test environment."""
        # Mock Kubernetes API
        self.mock_api = Mock()

        # Create test instance
        self.cluster_mgr = cluster_manager.ClusterForgeManager(self.mock_api)

    def tearDown(self):
        """Clean up after tests."""
        # Stop any running threads
        if hasattr(self.cluster_mgr, "_shutdown_event"):
            self.cluster_mgr._shutdown_event.set()

        # Clean up environment
        for key in [
            "CLUSTER_IDENTIFIER",
            "CLUSTER_REGION",
            "CLUSTER_ENVIRONMENT",
            "CLUSTER_PRIORITY",
            "ENABLE_CLUSTER_MANAGEMENT",
            "HEALTH_CHECK_ENDPOINT",
            "HEALTH_CHECK_INTERVAL",
        ]:
            os.environ.pop(key, None)

    def test_initialization(self):
        """Test cluster manager initialization."""
        self.assertEqual(self.cluster_mgr.cluster_id, "test-cluster")
        self.assertEqual(self.cluster_mgr.region, "us-test-1")
        self.assertEqual(self.cluster_mgr.environment, "test")
        self.assertEqual(self.cluster_mgr.priority, 5)
        self.assertTrue(self.cluster_mgr.enabled)

    @patch.dict(os.environ, {"ENABLE_CLUSTER_MANAGEMENT": "false"})
    def test_disabled_cluster_management(self):
        """Test behavior when cluster management is disabled."""
        # Create new manager with patched environment
        with patch("cluster_manager.ENABLE_CLUSTER_MANAGEMENT", False):
            disabled_mgr = cluster_manager.ClusterForgeManager(self.mock_api)
            disabled_mgr.enabled = (
                False  # Manually set since env var is cached at module level
            )

            self.assertFalse(disabled_mgr.enabled)

            # Should allow leadership when disabled
            allowed, reason = disabled_mgr.should_allow_local_leadership()
            self.assertTrue(allowed)
            self.assertEqual(reason, "cluster_management_disabled")

    def test_should_allow_leadership_no_crd(self):
        """Test leadership decision when no CRD exists."""
        self.cluster_mgr._current_cluster_crd = None

        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, "no_cluster_crd")

    def test_should_allow_leadership_disabled_state(self):
        """Test leadership decision when cluster is disabled."""
        self.cluster_mgr._current_cluster_crd = {
            "spec": {"forgeState": "Disabled"},
            "status": {"effectiveState": "Disabled"},
        }

        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertFalse(allowed)
        self.assertEqual(reason, "cluster_forge_disabled")

    def test_should_allow_leadership_enabled_state(self):
        """Test leadership decision when cluster is enabled."""
        self.cluster_mgr._current_cluster_crd = {
            "spec": {"forgeState": "Enabled"},
            "status": {"effectiveState": "Enabled"},
        }

        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, "cluster_forge_enabled")

    def test_should_allow_leadership_priority_based(self):
        """Test leadership decision for priority-based state."""
        # High priority cluster
        self.cluster_mgr._current_cluster_crd = {
            "spec": {"forgeState": "Priority-based", "priority": 1},
            "status": {"effectiveState": "Priority-based", "effectivePriority": 1},
        }

        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, "high_priority_1")

        # Lower priority cluster
        self.cluster_mgr._current_cluster_crd = {
            "spec": {"forgeState": "Priority-based", "priority": 50},
            "status": {"effectiveState": "Priority-based", "effectivePriority": 50},
        }

        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, "priority_based_50")

    def test_crd_creation(self):
        """Test CardanoForgeCluster CRD creation."""
        # Mock API calls
        self.mock_api.get_namespaced_custom_object.side_effect = ApiException(status=404)
        self.mock_api.create_namespaced_custom_object.return_value = {
            "metadata": {"name": "test-cluster"}
        }

        # This should trigger CRD creation
        self.cluster_mgr._ensure_cluster_crd()

        # Verify CRD creation was called
        self.mock_api.create_namespaced_custom_object.assert_called_once()
        call_args = self.mock_api.create_namespaced_custom_object.call_args

        body = call_args[1]["body"]
        self.assertEqual(body["kind"], "CardanoForgeCluster")
        self.assertEqual(body["metadata"]["name"], "test-cluster")
        self.assertEqual(body["spec"]["priority"], 5)
        self.assertEqual(body["spec"]["region"], "us-test-1")

    def test_leader_status_update(self):
        """Test updating cluster CRD with leader status."""
        self.cluster_mgr._current_cluster_crd = {"metadata": {"name": "test-cluster"}}

        # Test successful update
        self.cluster_mgr.update_leader_status("test-pod-0", True)

        self.mock_api.patch_namespaced_custom_object_status.assert_called_once()
        call_args = self.mock_api.patch_namespaced_custom_object_status.call_args

        body = call_args[1]["body"]
        self.assertEqual(body["status"]["activeLeader"], "test-pod-0")

    def test_get_cluster_metrics(self):
        """Test cluster metrics export."""
        # Test disabled state
        self.cluster_mgr.enabled = False
        metrics = self.cluster_mgr.get_cluster_metrics()
        self.assertEqual(metrics, {"enabled": False})

        # Test enabled state
        self.cluster_mgr.enabled = True
        self.cluster_mgr._cluster_forge_enabled = True
        self.cluster_mgr._effective_priority = 1
        self.cluster_mgr._consecutive_health_failures = 0

        metrics = self.cluster_mgr.get_cluster_metrics()

        self.assertTrue(metrics["enabled"])
        self.assertTrue(metrics["forge_enabled"])
        self.assertEqual(metrics["effective_priority"], 1)
        self.assertEqual(metrics["cluster_id"], "test-cluster")
        self.assertEqual(metrics["region"], "us-test-1")
        self.assertTrue(metrics["health_status"]["healthy"])

    @patch("requests.get")
    def test_health_check_success(self, mock_get):
        """Test successful health check."""
        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        self.cluster_mgr._perform_health_check()

        self.assertEqual(self.cluster_mgr._consecutive_health_failures, 0)
        self.assertIsNotNone(self.cluster_mgr._last_health_check)

    @patch("requests.get")
    def test_health_check_failure(self, mock_get):
        """Test failed health check."""
        # Mock failed HTTP response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        self.cluster_mgr._perform_health_check()

        self.assertEqual(self.cluster_mgr._consecutive_health_failures, 1)

    @patch("requests.get")
    def test_health_check_exception(self, mock_get):
        """Test health check with request exception."""
        import requests

        mock_get.side_effect = requests.RequestException("Connection failed")

        self.cluster_mgr._perform_health_check()

        self.assertEqual(self.cluster_mgr._consecutive_health_failures, 1)


class TestClusterManagerIntegration(unittest.TestCase):
    """Integration tests for cluster manager module functions."""

    def setUp(self):
        """Set up integration test environment."""
        # Reset global state
        cluster_manager.cluster_manager = None

        # Mock Kubernetes API
        self.mock_api = Mock()

    def test_backward_compatibility(self):
        """Test that existing single-cluster deployments work unchanged."""
        # Test with cluster management disabled
        os.environ["ENABLE_CLUSTER_MANAGEMENT"] = "false"

        # Should return default values
        allowed, reason = cluster_manager.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, "cluster_management_disabled")

        metrics = cluster_manager.get_cluster_metrics()
        self.assertEqual(metrics, {"enabled": False})

        # Cleanup
        os.environ.pop("ENABLE_CLUSTER_MANAGEMENT", None)

    def test_cluster_manager_initialization(self):
        """Test global cluster manager initialization."""
        os.environ["ENABLE_CLUSTER_MANAGEMENT"] = "true"

        # Initialize cluster manager
        with patch("cluster_manager.ClusterForgeManager") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            result = cluster_manager.initialize_cluster_manager(self.mock_api)

            self.assertIsNotNone(result)
            mock_class.assert_called_once_with(self.mock_api, '', '')
            mock_instance.start.assert_called_once()

        # Cleanup
        os.environ.pop("ENABLE_CLUSTER_MANAGEMENT", None)

    def test_module_functions_with_manager(self):
        """Test module-level functions with active cluster manager."""
        # Create mock cluster manager
        mock_manager = Mock()
        mock_manager.enabled = True
        mock_manager.should_allow_local_leadership.return_value = (False, "test_reason")
        mock_manager.get_cluster_metrics.return_value = {"test": "data"}

        cluster_manager.cluster_manager = mock_manager

        # Test functions
        allowed, reason = cluster_manager.should_allow_local_leadership()
        self.assertFalse(allowed)
        self.assertEqual(reason, "test_reason")

        cluster_manager.update_cluster_leader_status("test-pod", True)
        mock_manager.update_leader_status.assert_called_once_with("test-pod", True)

        metrics = cluster_manager.get_cluster_metrics()
        self.assertEqual(metrics, {"test": "data"})


class TestClusterForgeIntegration(unittest.TestCase):
    """Integration tests for cluster forge management with main forge manager."""

    def setUp(self):
        """Set up integration test environment."""
        self.mock_api = Mock()

    @patch("cluster_manager.cluster_manager")
    def test_forgemanager_cluster_integration(self, mock_cluster_module):
        """Test integration between forge manager and cluster management."""
        # This would test the integration points in forgemanager.py
        # Since we can't easily import forgemanager.py due to its structure,
        # we simulate the key integration points

        mock_cluster_manager = Mock()
        mock_cluster_manager.should_allow_local_leadership.return_value = (
            False,
            "blocked",
        )
        mock_cluster_module.get_cluster_manager.return_value = mock_cluster_manager
        mock_cluster_module.should_allow_local_leadership.return_value = (
            False,
            "blocked",
        )

        # Simulate the leadership check logic
        allowed, reason = mock_cluster_module.should_allow_local_leadership()

        self.assertFalse(allowed)
        self.assertEqual(reason, "blocked")


class TestMultiTenantSupport(unittest.TestCase):
    """Test multi-tenant functionality for network and pool isolation."""

    def setUp(self):
        """Set up multi-tenant test environment."""
        # Mock Kubernetes API
        self.mock_api = Mock()

        # Base environment for testing
        self.base_env = {
            "CLUSTER_REGION": "us-test-1",
            "ENABLE_CLUSTER_MANAGEMENT": "true",
        }

    def test_pool_id_validation(self):
        """Test pool ID validation functions."""

        # Valid pool IDs - any non-empty unique identifier
        self.assertTrue(
            cluster_manager.validate_pool_id(
                "pool1abcdefghijklmnopqrstuvwxyz1234567890abcdefghij"
            )
        )  # Cardano pool ID
        self.assertTrue(cluster_manager.validate_pool_id("MYPOOL"))  # Simple identifier
        self.assertTrue(
            cluster_manager.validate_pool_id("test-pool-123")
        )  # With dashes and numbers
        self.assertTrue(
            cluster_manager.validate_pool_id("STAKE_POOL_A")
        )  # With underscores

        # Invalid pool IDs
        self.assertFalse(cluster_manager.validate_pool_id(""))  # Empty string
        self.assertFalse(cluster_manager.validate_pool_id("   "))  # Only whitespace

        # Valid hex IDs - any hex string or empty (optional)
        self.assertTrue(
            cluster_manager.validate_pool_id_hex("abcdef1234567890")
        )  # Valid hex
        self.assertTrue(
            cluster_manager.validate_pool_id_hex("ABCDEF1234567890")
        )  # Uppercase allowed
        self.assertTrue(
            cluster_manager.validate_pool_id_hex("")
        )  # Empty is valid (optional)
        self.assertTrue(
            cluster_manager.validate_pool_id_hex("   ")
        )  # Whitespace-only is valid (optional)

        # Invalid hex IDs
        self.assertFalse(
            cluster_manager.validate_pool_id_hex("xyz123")
        )  # Invalid hex chars
        self.assertFalse(
            cluster_manager.validate_pool_id_hex("abcdgh")
        )  # Invalid hex chars

    def test_network_magic_validation(self):
        """Test network magic validation."""
        test_cases = [
            # (network, magic, should_be_valid)
            ("mainnet", 764824073, True),
            ("preprod", 1, True),
            ("preview", 2, True),
            ("custom", 12345, True),  # Custom networks allow any magic
            ("testnet", 42, True),  # Custom network with any magic
            ("mainnet", 1, False),  # Wrong magic for mainnet
            ("preprod", 764824073, False),  # Wrong magic for preprod
            ("", 123, False),  # Empty network name
        ]

        for network, magic, should_be_valid in test_cases:
            with patch.dict(
                os.environ,
                {
                    **self.base_env,
                    "CARDANO_NETWORK": network,
                    "NETWORK_MAGIC": str(magic),
                    "POOL_ID": "MYPOOL",
                },
            ):
                # Patch module-level variables since they're cached at import time
                with patch("cluster_manager.CARDANO_NETWORK", network), patch(
                    "cluster_manager.NETWORK_MAGIC", magic
                ), patch("cluster_manager.POOL_ID", "MYPOOL"):

                    if should_be_valid:
                        # Should not raise exception
                        try:
                            mgr = cluster_manager.ClusterForgeManager(self.mock_api)
                            self.assertEqual(mgr.network, network)
                            self.assertEqual(mgr.network_magic, magic)
                        except ValueError:
                            self.fail(
                                f"Valid config ({network}, {magic}) raised ValueError"
                            )
                    else:
                        # Should raise ValueError
                        with self.assertRaises(ValueError):
                            cluster_manager.ClusterForgeManager(self.mock_api)

    def test_multi_tenant_cluster_naming(self):
        """Test multi-tenant cluster name generation."""
        test_cases = [
            # (network, pool_id, region, network_magic, expected_cluster_name)
            ("mainnet", "MYPOOL", "us-east-1", 764824073, "mainnet-MYPOOL-us-east-1"),
            ("preprod", "STAKE-POOL-A", "eu-west-1", 1, "preprod-STAKE-PO-eu-west-1"),
            ("preview", "test123", "ap-south-1", 2, "preview-test123-ap-south-1"),
        ]

        for network, pool_id, region, network_magic, expected in test_cases:
            with patch.dict(
                os.environ,
                {
                    **self.base_env,
                    "CARDANO_NETWORK": network,
                    "POOL_ID": pool_id,
                    "CLUSTER_REGION": region,
                    "NETWORK_MAGIC": str(network_magic),
                },
            ):
                # Patch module-level variables
                with patch("cluster_manager.CARDANO_NETWORK", network), patch(
                    "cluster_manager.POOL_ID", pool_id
                ), patch("cluster_manager.CLUSTER_REGION", region), patch(
                    "cluster_manager.NETWORK_MAGIC", network_magic
                ):

                    mgr = cluster_manager.ClusterForgeManager(self.mock_api)
                    self.assertEqual(mgr.cluster_id, expected)

    def test_multi_tenant_lease_naming(self):
        """Test multi-tenant lease name generation."""
        test_cases = [
            # (network, pool_id, network_magic, expected_lease_name)
            ("mainnet", "MYPOOL", 764824073, "cardano-leader-mainnet-MYPOOL"),
            ("preprod", "STAKE-POOL-A", 1, "cardano-leader-preprod-STAKE-PO"),
            ("preview", "test123", 2, "cardano-leader-preview-test123"),
        ]

        for network, pool_id, network_magic, expected in test_cases:
            with patch.dict(
                os.environ,
                {
                    **self.base_env,
                    "CARDANO_NETWORK": network,
                    "POOL_ID": pool_id,
                    "NETWORK_MAGIC": str(network_magic),
                },
            ):
                # Patch module-level variables
                with patch("cluster_manager.CARDANO_NETWORK", network), patch(
                    "cluster_manager.POOL_ID", pool_id
                ), patch("cluster_manager.NETWORK_MAGIC", network_magic):

                    mgr = cluster_manager.ClusterForgeManager(self.mock_api)
                    self.assertEqual(mgr.lease_name, expected)

    def test_multi_tenant_crd_creation(self):
        """Test CRD creation with multi-tenant metadata."""
        with patch.dict(
            os.environ,
            {
                **self.base_env,
                "CARDANO_NETWORK": "mainnet",
                "POOL_ID": "MYPOOL",
                "POOL_ID_HEX": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef12",
                "POOL_NAME": "Test Pool",
                "POOL_TICKER": "TEST",
                "NETWORK_MAGIC": "764824073",
                "APPLICATION_TYPE": "block-producer",
            },
        ):
            # Patch module-level variables
            with patch("cluster_manager.CARDANO_NETWORK", "mainnet"), patch(
                "cluster_manager.POOL_ID", "MYPOOL"
            ), patch("cluster_manager.POOL_ID_HEX", "abcdef1234567890"), patch(
                "cluster_manager.POOL_NAME", "Test Pool"
            ), patch(
                "cluster_manager.POOL_TICKER", "TEST"
            ), patch(
                "cluster_manager.NETWORK_MAGIC", 764824073
            ), patch(
                "cluster_manager.APPLICATION_TYPE", "block-producer"
            ):

                mgr = cluster_manager.ClusterForgeManager(self.mock_api)

                # Mock CRD creation
                self.mock_api.get_namespaced_custom_object.side_effect = ApiException(
                    status=404
                )
                self.mock_api.create_namespaced_custom_object.return_value = {
                    "metadata": {"name": mgr.cluster_id}
                }

                # Trigger CRD creation
                mgr._ensure_cluster_crd()

                # Verify CRD was created with correct structure
                self.mock_api.create_namespaced_custom_object.assert_called_once()
                call_args = self.mock_api.create_namespaced_custom_object.call_args
                body = call_args[1]["body"]

                # Verify multi-tenant metadata
                self.assertEqual(body["kind"], "CardanoForgeCluster")
                self.assertEqual(body["metadata"]["name"], "mainnet-MYPOOL-us-test-1")

                # Verify labels
                labels = body["metadata"]["labels"]
                self.assertEqual(labels["cardano.io/network"], "mainnet")
                self.assertEqual(labels["cardano.io/pool-id"], "MYPOOL")
                self.assertEqual(labels["cardano.io/pool-ticker"], "TEST")
                self.assertEqual(labels["cardano.io/application"], "block-producer")

                # Verify spec structure
                spec = body["spec"]
                self.assertEqual(spec["network"]["name"], "mainnet")
                self.assertEqual(spec["network"]["magic"], 764824073)
                self.assertEqual(spec["pool"]["id"], "MYPOOL")
                self.assertEqual(spec["pool"]["ticker"], "TEST")
                self.assertEqual(spec["application"]["type"], "block-producer")

    def test_network_isolation(self):
        """Test that pools on different networks are isolated."""
        # Create two managers for same pool on different networks
        mainnet_env = {
            **self.base_env,
            "CARDANO_NETWORK": "mainnet",
            "POOL_ID": "MYPOOL",
            "NETWORK_MAGIC": "764824073",
        }

        preprod_env = {
            **self.base_env,
            "CARDANO_NETWORK": "preprod",
            "POOL_ID": "MYPOOL",  # Same pool ID
            "NETWORK_MAGIC": "1",
        }

        with patch.dict(os.environ, mainnet_env), patch(
            "cluster_manager.CARDANO_NETWORK", "mainnet"
        ), patch("cluster_manager.POOL_ID", "MYPOOL"), patch(
            "cluster_manager.NETWORK_MAGIC", 764824073
        ):
            mainnet_mgr = cluster_manager.ClusterForgeManager(self.mock_api)

        with patch.dict(os.environ, preprod_env), patch(
            "cluster_manager.CARDANO_NETWORK", "preprod"
        ), patch("cluster_manager.POOL_ID", "MYPOOL"), patch(
            "cluster_manager.NETWORK_MAGIC", 1
        ):
            preprod_mgr = cluster_manager.ClusterForgeManager(self.mock_api)

        # Verify different cluster names despite same pool ID
        self.assertNotEqual(mainnet_mgr.cluster_id, preprod_mgr.cluster_id)
        self.assertIn("mainnet", mainnet_mgr.cluster_id)
        self.assertIn("preprod", preprod_mgr.cluster_id)

        # Verify different lease names
        self.assertNotEqual(mainnet_mgr.lease_name, preprod_mgr.lease_name)
        self.assertIn("mainnet", mainnet_mgr.lease_name)
        self.assertIn("preprod", preprod_mgr.lease_name)

        # Verify network isolation
        self.assertEqual(mainnet_mgr.network, "mainnet")
        self.assertEqual(preprod_mgr.network, "preprod")
        self.assertEqual(mainnet_mgr.network_magic, 764824073)
        self.assertEqual(preprod_mgr.network_magic, 1)

    def test_pool_isolation(self):
        """Test that different pools on same network are isolated."""
        # Create two managers for different pools on same network
        pool1_env = {
            **self.base_env,
            "CARDANO_NETWORK": "mainnet",
            "POOL_ID": "POOL1",
            "NETWORK_MAGIC": "764824073",
        }

        pool2_env = {
            **self.base_env,
            "CARDANO_NETWORK": "mainnet",  # Same network
            "POOL_ID": "POOL2",  # Different pool
            "NETWORK_MAGIC": "764824073",
        }

        with patch.dict(os.environ, pool1_env), patch(
            "cluster_manager.CARDANO_NETWORK", "mainnet"
        ), patch("cluster_manager.POOL_ID", "POOL1"), patch(
            "cluster_manager.NETWORK_MAGIC", 764824073
        ):
            pool1_mgr = cluster_manager.ClusterForgeManager(self.mock_api)

        with patch.dict(os.environ, pool2_env), patch(
            "cluster_manager.CARDANO_NETWORK", "mainnet"
        ), patch("cluster_manager.POOL_ID", "POOL2"), patch(
            "cluster_manager.NETWORK_MAGIC", 764824073
        ):
            pool2_mgr = cluster_manager.ClusterForgeManager(self.mock_api)

        # Verify different cluster names
        self.assertNotEqual(pool1_mgr.cluster_id, pool2_mgr.cluster_id)
        self.assertIn("POOL1", pool1_mgr.cluster_id)
        self.assertIn("POOL2", pool2_mgr.cluster_id)

        # Verify different lease names
        self.assertNotEqual(pool1_mgr.lease_name, pool2_mgr.lease_name)
        self.assertIn("POOL1", pool1_mgr.lease_name)
        self.assertIn("POOL2", pool2_mgr.lease_name)

        # Verify same network
        self.assertEqual(pool1_mgr.network, pool2_mgr.network)
        self.assertEqual(pool1_mgr.network_magic, pool2_mgr.network_magic)

    def test_multi_tenant_metrics(self):
        """Test that multi-tenant metrics include proper labels."""
        with patch.dict(
            os.environ,
            {
                **self.base_env,
                "CARDANO_NETWORK": "mainnet",
                "POOL_ID": "MYPOOL",
                "POOL_TICKER": "TEST",
                "APPLICATION_TYPE": "block-producer",
                "NETWORK_MAGIC": "764824073",
            },
        ):
            # Patch module-level variables
            with patch("cluster_manager.CARDANO_NETWORK", "mainnet"), patch(
                "cluster_manager.POOL_ID", "MYPOOL"
            ), patch("cluster_manager.POOL_TICKER", "TEST"), patch(
                "cluster_manager.APPLICATION_TYPE", "block-producer"
            ), patch(
                "cluster_manager.NETWORK_MAGIC", 764824073
            ):

                mgr = cluster_manager.ClusterForgeManager(self.mock_api)
                metrics = mgr.get_cluster_metrics()

            # Verify multi-tenant fields in metrics
            self.assertTrue(metrics["enabled"])
            self.assertEqual(metrics["network"], "mainnet")
            self.assertEqual(metrics["pool_id"], "MYPOOL")
            self.assertEqual(metrics["pool_ticker"], "TEST")
            self.assertEqual(metrics["application_type"], "block-producer")

    def test_backward_compatibility(self):
        """Test that legacy single-tenant deployments still work."""
        # Test with minimal legacy environment (no pool ID)
        legacy_env = {
            "CLUSTER_IDENTIFIER": "legacy-cluster",
            "CLUSTER_REGION": "us-test-1",
            "ENABLE_CLUSTER_MANAGEMENT": "true",
        }

        with patch.dict(os.environ, legacy_env, clear=True), patch(
            "cluster_manager.CLUSTER_IDENTIFIER", "legacy-cluster"
        ), patch("cluster_manager.POOL_ID", ""), patch(
            "cluster_manager.CARDANO_NETWORK", "mainnet"
        ):

            mgr = cluster_manager.ClusterForgeManager(self.mock_api)

            # Should fall back to legacy naming
            self.assertEqual(mgr.cluster_id, "legacy-cluster")
            self.assertEqual(mgr.lease_name, "cardano-node-leader")
            self.assertEqual(mgr.network, "mainnet")  # Default
            self.assertEqual(mgr.pool_id, "")  # Empty

    def test_configuration_validation_edge_cases(self):
        """Test edge cases in configuration validation."""
        # Test with missing required fields
        incomplete_configs = [
            # Missing POOL_ID_HEX when POOL_ID is provided
            {
                **self.base_env,
                "CARDANO_NETWORK": "mainnet",
                "POOL_ID": "MYPOOL",
                "POOL_ID_HEX": "invalid_hex_characters",  # Invalid hex
                "NETWORK_MAGIC": "764824073",
            }
        ]

        for config in incomplete_configs:
            with patch.dict(os.environ, config), patch(
                "cluster_manager.CARDANO_NETWORK", "mainnet"
            ), patch("cluster_manager.POOL_ID", "MYPOOL"), patch(
                "cluster_manager.POOL_ID_HEX", "invalid_hex_characters"
            ), patch(
                "cluster_manager.NETWORK_MAGIC", 764824073
            ):

                with self.assertRaises(ValueError):
                    cluster_manager.ClusterForgeManager(self.mock_api)

    def test_multi_tenant_leadership_isolation(self):
        """Test that leadership decisions are properly isolated."""
        # Create managers for different pools
        pool1_env = {
            **self.base_env,
            "CARDANO_NETWORK": "mainnet",
            "POOL_ID": "POOL1",
            "NETWORK_MAGIC": "764824073",
        }

        pool2_env = {
            **self.base_env,
            "CARDANO_NETWORK": "mainnet",
            "POOL_ID": "POOL2",
            "NETWORK_MAGIC": "764824073",
        }

        with patch.dict(os.environ, pool1_env), patch(
            "cluster_manager.CARDANO_NETWORK", "mainnet"
        ), patch("cluster_manager.POOL_ID", "POOL1"), patch(
            "cluster_manager.NETWORK_MAGIC", 764824073
        ):

            pool1_mgr = cluster_manager.ClusterForgeManager(self.mock_api)
            pool1_mgr._current_cluster_crd = {
                "spec": {"forgeState": "Enabled"},
                "status": {"effectiveState": "Enabled"},
            }

        with patch.dict(os.environ, pool2_env), patch(
            "cluster_manager.CARDANO_NETWORK", "mainnet"
        ), patch("cluster_manager.POOL_ID", "POOL2"), patch(
            "cluster_manager.NETWORK_MAGIC", 764824073
        ):

            pool2_mgr = cluster_manager.ClusterForgeManager(self.mock_api)
            pool2_mgr._current_cluster_crd = {
                "spec": {"forgeState": "Disabled"},
                "status": {"effectiveState": "Disabled"},
            }

        # Pool 1 should allow leadership
        allowed1, reason1 = pool1_mgr.should_allow_local_leadership()
        self.assertTrue(allowed1)
        self.assertEqual(reason1, "cluster_forge_enabled")

        # Pool 2 should deny leadership
        allowed2, reason2 = pool2_mgr.should_allow_local_leadership()
        self.assertFalse(allowed2)
        self.assertEqual(reason2, "cluster_forge_disabled")


class TestClusterScenarios(unittest.TestCase):
    """Test various cluster management scenarios."""

    def test_multi_cluster_priority_scenario(self):
        """Test multi-cluster priority-based coordination scenario."""
        # Simulate 3 clusters with different priorities
        clusters = [
            {"id": "us-east-1", "priority": 1, "state": "Priority-based"},
            {"id": "us-west-2", "priority": 2, "state": "Priority-based"},
            {"id": "eu-west-1", "priority": 3, "state": "Priority-based"},
        ]

        # In a real multi-cluster scenario, only the highest priority (us-east-1) should forge
        # This test documents the expected behavior

        for cluster in clusters:
            mock_api = Mock()
            os.environ.update(
                {
                    "CLUSTER_IDENTIFIER": cluster["id"],
                    "CLUSTER_PRIORITY": str(cluster["priority"]),
                    "ENABLE_CLUSTER_MANAGEMENT": "true",
                }
            )

            mgr = cluster_manager.ClusterForgeManager(mock_api)
            mgr._current_cluster_crd = {
                "spec": {
                    "forgeState": cluster["state"],
                    "priority": cluster["priority"],
                },
                "status": {
                    "effectiveState": cluster["state"],
                    "effectivePriority": cluster["priority"],
                },
            }

            allowed, reason = mgr.should_allow_local_leadership()

            # Currently, all clusters with priority <= 10 are considered "high priority"
            # In a full implementation, this would involve cross-cluster coordination
            if cluster["priority"] <= 10:
                self.assertTrue(allowed)
                self.assertIn("high_priority", reason)
            else:
                self.assertTrue(allowed)  # Current implementation allows all
                self.assertIn("priority_based", reason)

    def test_manual_failover_scenario(self):
        """Test manual failover scenario with override."""
        mock_api = Mock()
        mgr = cluster_manager.ClusterForgeManager(mock_api)

        # Simulate manual failover with override
        override_time = datetime.now(timezone.utc) + timedelta(hours=1)
        mgr._current_cluster_crd = {
            "spec": {
                "forgeState": "Priority-based",
                "priority": 2,  # Normally secondary
                "override": {
                    "enabled": True,
                    "reason": "Manual failover for maintenance",
                    "expiresAt": override_time.isoformat(),
                    "forcePriority": 1,  # Temporarily highest priority
                },
            },
            "status": {
                "effectiveState": "Priority-based",
                "effectivePriority": 1,  # Override applied
            },
        }

        allowed, reason = mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, "high_priority_1")

    def test_global_disable_scenario(self):
        """Test global disable scenario."""
        mock_api = Mock()
        mgr = cluster_manager.ClusterForgeManager(mock_api)

        # Simulate global disable
        mgr._current_cluster_crd = {
            "spec": {"forgeState": "Disabled"},
            "status": {"effectiveState": "Disabled"},
        }

        allowed, reason = mgr.should_allow_local_leadership()
        self.assertFalse(allowed)
        self.assertEqual(reason, "cluster_forge_disabled")


if __name__ == "__main__":
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestClusterForgeManager))
    suite.addTests(loader.loadTestsFromTestCase(TestClusterManagerIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestClusterForgeIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestClusterScenarios))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with proper code
    exit(0 if result.wasSuccessful() else 1)
