#!/usr/bin/env python3

import os
import stat
import sys

def test_socket_detection():
    """Test socket detection logic"""
    NODE_SOCKET = "/ipc/node.socket"
    
    print(f"Testing socket detection for: {NODE_SOCKET}")
    
    # Check if socket exists
    socket_exists = os.path.exists(NODE_SOCKET)
    print(f"Socket exists: {socket_exists}")
    
    if socket_exists:
        try:
            # Check if it's actually a socket
            is_socket = stat.S_ISSOCK(os.stat(NODE_SOCKET).st_mode)
            print(f"Is valid socket: {is_socket}")
            
            if is_socket:
                print("✅ Socket detection: PASS - Node should be considered ready")
                return True
            else:
                print("❌ Socket detection: FAIL - File exists but not a socket")
                return False
        except Exception as e:
            print(f"❌ Socket detection: ERROR - {e}")
            return False
    else:
        print("⚠️ Socket detection: Node not ready - socket missing")
        return False

def test_process_discovery():
    """Test process discovery logic"""
    import psutil
    
    CARDANO_NODE_PROCESS_NAME = "cardano-node"
    print(f"Testing process discovery for: {CARDANO_NODE_PROCESS_NAME}")
    
    found_processes = []
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            if proc.info["name"] == CARDANO_NODE_PROCESS_NAME:
                found_processes.append(f"By name: PID {proc.info['pid']}")
            elif proc.info["cmdline"] and any(CARDANO_NODE_PROCESS_NAME in arg for arg in proc.info["cmdline"]):
                found_processes.append(f"By cmdline: PID {proc.info['pid']} - {' '.join(proc.info['cmdline'][:3])}")
    except Exception as e:
        print(f"❌ Process discovery: ERROR - {e}")
        return False
    
    if found_processes:
        print("✅ Process discovery: FOUND")
        for proc in found_processes:
            print(f"  - {proc}")
        return True
    else:
        print("⚠️ Process discovery: NOT FOUND - Expected in cross-container setup")
        return False

def test_startup_phase_logic():
    """Test the startup phase detection logic"""
    print("Testing startup phase logic...")
    
    socket_ready = test_socket_detection()
    process_found = test_process_discovery()
    
    # According to our fixed logic:
    # - If socket doesn't exist -> startup phase
    # - If socket exists and is valid -> startup phase complete
    # - Process discovery failure is OK in cross-container setup
    
    if socket_ready:
        print("✅ Startup phase logic: Node should be READY for leadership election")
        return True
    else:
        print("⚠️ Startup phase logic: Node still in STARTUP phase")
        return False

if __name__ == "__main__":
    print("🔍 Testing Cardano Forge Manager fixes...")
    print("=" * 50)
    
    socket_test = test_socket_detection()
    print()
    
    process_test = test_process_discovery() 
    print()
    
    startup_test = test_startup_phase_logic()
    print()
    
    print("=" * 50)
    if socket_test and startup_test:
        print("✅ Overall: Fixes should resolve the main loop issue")
        sys.exit(0)
    else:
        print("❌ Overall: Issues may persist")
        sys.exit(1)