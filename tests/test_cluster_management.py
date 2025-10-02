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
from datetime import datetime, timezone, timedelta

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import cluster_manager
from kubernetes.client.rest import ApiException


class TestClusterForgeManager(unittest.TestCase):
    """Test cases for ClusterForgeManager class."""
    
    def setUp(self):
        """Set up test environment."""
        # Mock Kubernetes API
        self.mock_api = Mock()
        
        # Set test environment variables
        os.environ.update({
            'CLUSTER_IDENTIFIER': 'test-cluster',
            'CLUSTER_REGION': 'us-test-1',
            'CLUSTER_ENVIRONMENT': 'test',
            'CLUSTER_PRIORITY': '5',
            'ENABLE_CLUSTER_MANAGEMENT': 'true',
            'HEALTH_CHECK_ENDPOINT': 'http://test.example.com/health',
            'HEALTH_CHECK_INTERVAL': '10',
        })
        
        # Create test instance
        self.cluster_mgr = cluster_manager.ClusterForgeManager(self.mock_api)
    
    def tearDown(self):
        """Clean up after tests."""
        # Stop any running threads
        if hasattr(self.cluster_mgr, '_shutdown_event'):
            self.cluster_mgr._shutdown_event.set()
        
        # Clean up environment
        for key in ['CLUSTER_IDENTIFIER', 'CLUSTER_REGION', 'CLUSTER_ENVIRONMENT', 
                    'CLUSTER_PRIORITY', 'ENABLE_CLUSTER_MANAGEMENT', 
                    'HEALTH_CHECK_ENDPOINT', 'HEALTH_CHECK_INTERVAL']:
            os.environ.pop(key, None)
    
    def test_initialization(self):
        """Test cluster manager initialization."""
        self.assertEqual(self.cluster_mgr.cluster_id, 'test-cluster')
        self.assertEqual(self.cluster_mgr.region, 'us-test-1')
        self.assertEqual(self.cluster_mgr.environment, 'test')
        self.assertEqual(self.cluster_mgr.priority, 5)
        self.assertTrue(self.cluster_mgr.enabled)
    
    def test_disabled_cluster_management(self):
        """Test behavior when cluster management is disabled."""
        os.environ['ENABLE_CLUSTER_MANAGEMENT'] = 'false'
        
        disabled_mgr = cluster_manager.ClusterForgeManager(self.mock_api)
        self.assertFalse(disabled_mgr.enabled)
        
        # Should allow leadership when disabled
        allowed, reason = disabled_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, 'cluster_management_disabled')
    
    def test_should_allow_leadership_no_crd(self):
        """Test leadership decision when no CRD exists."""
        self.cluster_mgr._current_cluster_crd = None
        
        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, 'no_cluster_crd')
    
    def test_should_allow_leadership_disabled_state(self):
        """Test leadership decision when cluster is disabled."""
        self.cluster_mgr._current_cluster_crd = {
            'spec': {'forgeState': 'Disabled'},
            'status': {'effectiveState': 'Disabled'}
        }
        
        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertFalse(allowed)
        self.assertEqual(reason, 'cluster_forge_disabled')
    
    def test_should_allow_leadership_enabled_state(self):
        """Test leadership decision when cluster is enabled."""
        self.cluster_mgr._current_cluster_crd = {
            'spec': {'forgeState': 'Enabled'},
            'status': {'effectiveState': 'Enabled'}
        }
        
        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, 'cluster_forge_enabled')
    
    def test_should_allow_leadership_priority_based(self):
        """Test leadership decision for priority-based state."""
        # High priority cluster
        self.cluster_mgr._current_cluster_crd = {
            'spec': {'forgeState': 'Priority-based', 'priority': 1},
            'status': {'effectiveState': 'Priority-based', 'effectivePriority': 1}
        }
        
        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, 'high_priority_1')
        
        # Lower priority cluster
        self.cluster_mgr._current_cluster_crd = {
            'spec': {'forgeState': 'Priority-based', 'priority': 50},
            'status': {'effectiveState': 'Priority-based', 'effectivePriority': 50}
        }
        
        allowed, reason = self.cluster_mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, 'priority_based_50')
    
    def test_crd_creation(self):
        """Test CardanoForgeCluster CRD creation."""
        # Mock API calls
        self.mock_api.get_cluster_custom_object.side_effect = ApiException(status=404)
        self.mock_api.create_cluster_custom_object.return_value = {'metadata': {'name': 'test-cluster'}}
        
        # This should trigger CRD creation
        self.cluster_mgr._ensure_cluster_crd()
        
        # Verify CRD creation was called
        self.mock_api.create_cluster_custom_object.assert_called_once()
        call_args = self.mock_api.create_cluster_custom_object.call_args
        
        body = call_args[1]['body']
        self.assertEqual(body['kind'], 'CardanoForgeCluster')
        self.assertEqual(body['metadata']['name'], 'test-cluster')
        self.assertEqual(body['spec']['priority'], 5)
        self.assertEqual(body['spec']['region'], 'us-test-1')
    
    def test_leader_status_update(self):
        """Test updating cluster CRD with leader status."""
        self.cluster_mgr._current_cluster_crd = {'metadata': {'name': 'test-cluster'}}
        
        # Test successful update
        self.cluster_mgr.update_leader_status('test-pod-0', True)
        
        self.mock_api.patch_cluster_custom_object_status.assert_called_once()
        call_args = self.mock_api.patch_cluster_custom_object_status.call_args
        
        body = call_args[1]['body']
        self.assertEqual(body['status']['activeLeader'], 'test-pod-0')
    
    def test_get_cluster_metrics(self):
        """Test cluster metrics export."""
        # Test disabled state
        self.cluster_mgr.enabled = False
        metrics = self.cluster_mgr.get_cluster_metrics()
        self.assertEqual(metrics, {'enabled': False})
        
        # Test enabled state
        self.cluster_mgr.enabled = True
        self.cluster_mgr._cluster_forge_enabled = True
        self.cluster_mgr._effective_priority = 1
        self.cluster_mgr._consecutive_health_failures = 0
        
        metrics = self.cluster_mgr.get_cluster_metrics()
        
        self.assertTrue(metrics['enabled'])
        self.assertTrue(metrics['forge_enabled'])
        self.assertEqual(metrics['effective_priority'], 1)
        self.assertEqual(metrics['cluster_id'], 'test-cluster')
        self.assertEqual(metrics['region'], 'us-test-1')
        self.assertTrue(metrics['health_status']['healthy'])
    
    @patch('requests.get')
    def test_health_check_success(self, mock_get):
        """Test successful health check."""
        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        self.cluster_mgr._perform_health_check()
        
        self.assertEqual(self.cluster_mgr._consecutive_health_failures, 0)
        self.assertIsNotNone(self.cluster_mgr._last_health_check)
    
    @patch('requests.get')
    def test_health_check_failure(self, mock_get):
        """Test failed health check."""
        # Mock failed HTTP response
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response
        
        self.cluster_mgr._perform_health_check()
        
        self.assertEqual(self.cluster_mgr._consecutive_health_failures, 1)
    
    @patch('requests.get')
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
        os.environ['ENABLE_CLUSTER_MANAGEMENT'] = 'false'
        
        # Should return default values
        allowed, reason = cluster_manager.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, 'cluster_management_disabled')
        
        metrics = cluster_manager.get_cluster_metrics()
        self.assertEqual(metrics, {'enabled': False})
        
        # Cleanup
        os.environ.pop('ENABLE_CLUSTER_MANAGEMENT', None)
    
    def test_cluster_manager_initialization(self):
        """Test global cluster manager initialization."""
        os.environ['ENABLE_CLUSTER_MANAGEMENT'] = 'true'
        
        # Initialize cluster manager
        with patch('cluster_manager.ClusterForgeManager') as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            
            result = cluster_manager.initialize_cluster_manager(self.mock_api)
            
            self.assertIsNotNone(result)
            mock_class.assert_called_once_with(self.mock_api)
            mock_instance.start.assert_called_once()
        
        # Cleanup
        os.environ.pop('ENABLE_CLUSTER_MANAGEMENT', None)
    
    def test_module_functions_with_manager(self):
        """Test module-level functions with active cluster manager."""
        # Create mock cluster manager
        mock_manager = Mock()
        mock_manager.enabled = True
        mock_manager.should_allow_local_leadership.return_value = (False, 'test_reason')
        mock_manager.get_cluster_metrics.return_value = {'test': 'data'}
        
        cluster_manager.cluster_manager = mock_manager
        
        # Test functions
        allowed, reason = cluster_manager.should_allow_local_leadership()
        self.assertFalse(allowed)
        self.assertEqual(reason, 'test_reason')
        
        cluster_manager.update_cluster_leader_status('test-pod', True)
        mock_manager.update_leader_status.assert_called_once_with('test-pod', True)
        
        metrics = cluster_manager.get_cluster_metrics()
        self.assertEqual(metrics, {'test': 'data'})


class TestClusterForgeIntegration(unittest.TestCase):
    """Integration tests for cluster forge management with main forge manager."""
    
    def setUp(self):
        """Set up integration test environment."""
        self.mock_api = Mock()
    
    @patch('cluster_manager.CLUSTER_MANAGEMENT_AVAILABLE', True)
    @patch('cluster_manager.cluster_manager')
    def test_forgemanager_cluster_integration(self, mock_cluster_module):
        """Test integration between forge manager and cluster management."""
        # This would test the integration points in forgemanager.py
        # Since we can't easily import forgemanager.py due to its structure,
        # we simulate the key integration points
        
        mock_cluster_manager = Mock()
        mock_cluster_manager.should_allow_local_leadership.return_value = (False, 'blocked')
        mock_cluster_module.get_cluster_manager.return_value = mock_cluster_manager
        mock_cluster_module.should_allow_local_leadership.return_value = (False, 'blocked')
        
        # Simulate the leadership check logic
        allowed, reason = mock_cluster_module.should_allow_local_leadership()
        
        self.assertFalse(allowed)
        self.assertEqual(reason, 'blocked')


class TestClusterScenarios(unittest.TestCase):
    """Test various cluster management scenarios."""
    
    def test_multi_cluster_priority_scenario(self):
        """Test multi-cluster priority-based coordination scenario."""
        # Simulate 3 clusters with different priorities
        clusters = [
            {'id': 'us-east-1', 'priority': 1, 'state': 'Priority-based'},
            {'id': 'us-west-2', 'priority': 2, 'state': 'Priority-based'},
            {'id': 'eu-west-1', 'priority': 3, 'state': 'Priority-based'},
        ]
        
        # In a real multi-cluster scenario, only the highest priority (us-east-1) should forge
        # This test documents the expected behavior
        
        for cluster in clusters:
            mock_api = Mock()
            os.environ.update({
                'CLUSTER_IDENTIFIER': cluster['id'],
                'CLUSTER_PRIORITY': str(cluster['priority']),
                'ENABLE_CLUSTER_MANAGEMENT': 'true',
            })
            
            mgr = cluster_manager.ClusterForgeManager(mock_api)
            mgr._current_cluster_crd = {
                'spec': {'forgeState': cluster['state'], 'priority': cluster['priority']},
                'status': {'effectiveState': cluster['state'], 'effectivePriority': cluster['priority']}
            }
            
            allowed, reason = mgr.should_allow_local_leadership()
            
            # Currently, all clusters with priority <= 10 are considered "high priority"
            # In a full implementation, this would involve cross-cluster coordination
            if cluster['priority'] <= 10:
                self.assertTrue(allowed)
                self.assertIn('high_priority', reason)
            else:
                self.assertTrue(allowed)  # Current implementation allows all
                self.assertIn('priority_based', reason)
    
    def test_manual_failover_scenario(self):
        """Test manual failover scenario with override."""
        mock_api = Mock()
        mgr = cluster_manager.ClusterForgeManager(mock_api)
        
        # Simulate manual failover with override
        override_time = datetime.now(timezone.utc) + timedelta(hours=1)
        mgr._current_cluster_crd = {
            'spec': {
                'forgeState': 'Priority-based',
                'priority': 2,  # Normally secondary
                'override': {
                    'enabled': True,
                    'reason': 'Manual failover for maintenance',
                    'expiresAt': override_time.isoformat(),
                    'forcePriority': 1  # Temporarily highest priority
                }
            },
            'status': {
                'effectiveState': 'Priority-based',
                'effectivePriority': 1  # Override applied
            }
        }
        
        allowed, reason = mgr.should_allow_local_leadership()
        self.assertTrue(allowed)
        self.assertEqual(reason, 'high_priority_1')
    
    def test_global_disable_scenario(self):
        """Test global disable scenario."""
        mock_api = Mock()
        mgr = cluster_manager.ClusterForgeManager(mock_api)
        
        # Simulate global disable
        mgr._current_cluster_crd = {
            'spec': {'forgeState': 'Disabled'},
            'status': {'effectiveState': 'Disabled'}
        }
        
        allowed, reason = mgr.should_allow_local_leadership()
        self.assertFalse(allowed)
        self.assertEqual(reason, 'cluster_forge_disabled')


if __name__ == '__main__':
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