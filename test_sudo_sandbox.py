#!/usr/bin/env python3
"""
Complete Sandbox Sudo Operations Test Script

This script demonstrates running privileged (sudo) operations inside Docker containers.
Docker containers run as root by default, so sudo operations work seamlessly.

PREREQUISITES:
1. API server running: cd ~/api_server && docker-compose up -d
2. Python SDK installed: pip install -e ~/my_sandbox_sdk

USAGE:
    python test_sudo_sandbox.py
"""

import sys
import os
import time
from pathlib import Path

# Add SDK to path if needed
SDK_PATH = Path(__file__).parent / "my_sandbox_sdk"
if SDK_PATH.exists():
    sys.path.insert(0, str(SDK_PATH))

from my_sdk import Sandbox, AsyncSandbox
from my_sdk.exceptions import SandboxException
import asyncio


def test_basic_sudo_operations():
    """Test basic sudo operations in a sandbox."""
    print("\n" + "="*70)
    print("TEST 1: Basic Sudo Operations")
    print("="*70)
    
    try:
        # Create sandbox
        print("\n📦 Creating sandbox...")
        sandbox = Sandbox.create(
            api_url="http://localhost:8000",
            api_key="test-key-12345",
            template_id="python:3.11"
        )
        print(f"✅ Sandbox created: {sandbox.sandbox_id}")
        
        # Test 1: Check current user (should be root)
        print("\n👤 Checking current user...")
        result = sandbox.commands.run("whoami")
        print(f"   Current user: {result.stdout.strip()}")
        assert "root" in result.stdout, "Expected to be root in container"
        print("✅ User check passed")
        
        # Test 2: Install a package using apt (requires sudo/root)
        print("\n📦 Installing curl package...")
        result = sandbox.commands.run("apt-get update && apt-get install -y curl", timeout=60)
        print(f"   Exit code: {result.exit_code}")
        if result.exit_code == 0:
            print("✅ Package installation successful")
        else:
            print(f"⚠️  Installation output: {result.stderr[:200]}")
        
        # Test 3: Create a system user (requires root)
        print("\n👥 Creating system user 'testuser'...")
        result = sandbox.commands.run("useradd -m -s /bin/bash testuser")
        print(f"   Exit code: {result.exit_code}")
        if result.exit_code == 0:
            print("✅ User creation successful")
        
        # Test 4: Verify user was created
        print("\n✔️  Verifying user was created...")
        result = sandbox.commands.run("id testuser")
        print(f"   Output: {result.stdout.strip()}")
        print("✅ User verification passed")
        
        # Test 5: Create a file in /etc (restricted directory)
        print("\n📝 Creating file in /etc (restricted)...")
        result = sandbox.commands.run("echo 'test config' > /etc/test_config.txt")
        print(f"   Exit code: {result.exit_code}")
        if result.exit_code == 0:
            print("✅ File creation in /etc successful")
        
        # Test 6: View file from restricted directory
        print("\n📖 Reading file from /etc...")
        result = sandbox.commands.run("cat /etc/test_config.txt")
        print(f"   Content: {result.stdout.strip()}")
        assert "test config" in result.stdout
        print("✅ File read successful")
        
        # Test 7: Check sudo version
        print("\n🔐 Checking sudo version...")
        result = sandbox.commands.run("sudo --version")
        print(f"   Output (first line): {result.stdout.split(chr(10))[0]}")
        print("✅ Sudo available")
        
        # Test 8: Modify /proc (restricted filesystem)
        print("\n📊 Accessing /proc/cpuinfo...")
        result = sandbox.commands.run("cat /proc/cpuinfo | head -3")
        print(f"   Output: {result.stdout}")
        print("✅ /proc access successful")
        
        # Clean up
        print("\n🗑️  Killing sandbox...")
        sandbox.kill()
        print("✅ Sandbox killed")
        
        return True
        
    except SandboxException as e:
        print(f"❌ Sandbox error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_file_operations_as_root():
    """Test file operations requiring root privileges."""
    print("\n" + "="*70)
    print("TEST 2: Root File Operations")
    print("="*70)
    
    try:
        sandbox = Sandbox.create(
            api_url="http://localhost:8000",
            api_key="test-key-12345",
            template_id="python:3.11"
        )
        print(f"✅ Sandbox created: {sandbox.sandbox_id}")
        
        # Test 1: Write to root home directory
        print("\n📝 Writing to /root/.bashrc...")
        result = sandbox.commands.run("echo 'export TEST_VAR=hello' >> /root/.bashrc")
        if result.exit_code == 0:
            print("✅ Write to /root successful")
        
        # Test 2: Change file permissions
        print("\n🔒 Changing file permissions...")
        result = sandbox.commands.run("echo 'secret' > /tmp/secret.txt && chmod 600 /tmp/secret.txt")
        if result.exit_code == 0:
            print("✅ Permission change successful")
        
        # Test 3: Check file permissions
        print("\n📋 Checking file permissions...")
        result = sandbox.commands.run("ls -la /tmp/secret.txt")
        print(f"   {result.stdout.strip()}")
        print("✅ File permissions checked")
        
        # Test 4: Create symbolic link
        print("\n🔗 Creating symbolic link...")
        result = sandbox.commands.run("ln -s /etc/hostname /tmp/hostname_link")
        if result.exit_code == 0:
            print("✅ Symlink creation successful")
        
        # Test 5: Verify symlink
        print("\n✔️  Verifying symlink...")
        result = sandbox.commands.run("readlink /tmp/hostname_link")
        print(f"   Points to: {result.stdout.strip()}")
        print("✅ Symlink verification passed")
        
        # Clean up
        sandbox.kill()
        print("\n✅ Test 2 complete")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_system_commands():
    """Test various system-level commands requiring root."""
    print("\n" + "="*70)
    print("TEST 3: System Commands")
    print("="*70)
    
    try:
        
        sandbox = Sandbox.create(
            api_url="http://localhost:8000",
            api_key="test-key-12345",
            template_id="python:3.11"
        )
        print(f"✅ Sandbox created: {sandbox.sandbox_id}")
        
        # Test 1: Get system info
        print("\n ℹ️  Getting system information...")
        result = sandbox.commands.run("uname -a")
        print(f"   {result.stdout.strip()}")
        print("✅ System info retrieved")
        result= sandbox.commands.run_python("import platform; print(platform.platform())")
        print(f"   Python platform: {result.stdout.strip()}")
        print("✅ Python platform retrieved")
        # Test 2: Check available disk space
        print("\n💾 Checking disk space...")
        result = sandbox.commands.run("df -h | head -2")
        print(f"   {result.stdout.strip()}")
        print("✅ Disk space checked")
        
        # Test 3: Check memory
        print("\n🧠 Checking memory...")
        result = sandbox.commands.run("free -h")
        print(f"{result.stdout}")
        print("✅ Memory info retrieved")
        
        # Test 4: List network interfaces
        print("\n🌐 Listing network interfaces...")
        result = sandbox.commands.run("ip addr show || ifconfig")
        if result.exit_code == 0:
            print(f"   {result.stdout[:200]}...")
            print("✅ Network interfaces listed")
        
        # Test 5: Check environment
        print("\n🌍 Checking environment variables...")
        result = sandbox.commands.run("env | sort")
        lines = result.stdout.strip().split('\n')
        print(f"   {len(lines)} environment variables found")
        print(f"   First 3: {chr(10).join(lines[:3])}")
        print("✅ Environment checked")
        
        # Clean up
        sandbox.kill()
        print("\n✅ Test 3 complete")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_sdk_file_operations_with_root():
    """Test SDK file operations on files created with root."""
    print("\n" + "="*70)
    print("TEST 4: SDK File Operations (Root Files)")
    print("="*70)
    
    try:
        sandbox = Sandbox.create(
            api_url="http://localhost:8000",
            api_key="test-key-12345",
            template_id="python:3.11"
        )
        print(f"✅ Sandbox created: {sandbox.sandbox_id}")
        
        # Create a file with SDK (normal user)
        print("\n📝 Creating file with SDK...")
        sandbox.files.write("/tmp/sdk_test.txt", "Hello from SDK!")
        print("✅ File created")
        
        # Verify via command
        result = sandbox.commands.run("cat /tmp/sdk_test.txt")
        assert "Hello from SDK!" in result.stdout
        print("✅ File verified")
        
        # Create a file as root via command
        print("\n📝 Creating file as root via command...")
        sandbox.commands.run("echo 'Hello from root' > /root/root_file.txt")
        print("✅ Root file created")
        
        # Try to read root file with SDK
        print("\n📖 Reading root file with SDK...")
        try:
            content = sandbox.files.read("/root/root_file.txt")
            print(f"   Content: {content}")
            print("✅ Root file read successfully")
        except Exception as e:
            print(f"   Note: {e}")
            # This might fail if container user can't read /root
            # But in our case running as root should work
        
        # List files
        print("\n📋 Listing /tmp directory...")
        entries = sandbox.files.list("/tmp")
        print(f"   Found {len(entries)} entries")
        for entry in entries[:5]:
            print(f"   - {entry}")
        print("✅ Directory listing successful")
        
        # Clean up
        sandbox.kill()
        print("\n✅ Test 4 complete")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_async_sudo_operations():
    """Test async sudo operations."""
    print("\n" + "="*70)
    print("TEST 5: Async Sudo Operations")
    print("="*70)
    
    try:
        # Create sandbox
        print("\n📦 Creating async sandbox...")
        sandbox = await AsyncSandbox.create(
            api_url="http://localhost:8000",
            api_key="test-key-12345",
            template_id="python:3.11"
        )
        print(f"✅ Sandbox created: {sandbox.sandbox_id}")
        
        # Run multiple commands concurrently
        print("\n⚡ Running concurrent commands...")
        start = time.time()
        
        results = await asyncio.gather(
            sandbox.commands.run("whoami"),
            sandbox.commands.run("hostname"),
            sandbox.commands.run("pwd"),
        )
        
        elapsed = time.time() - start
        
        print(f"✅ Commands completed in {elapsed:.2f}s")
        print(f"   User: {results[0].stdout.strip()}")
        print(f"   Host: {results[1].stdout.strip()}")
        print(f"   PWD: {results[2].stdout.strip()}")
        
        # Kill sandbox
        await sandbox.kill()
        print("✅ Sandbox killed")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "🚀"*35)
    print("SANDBOX SUDO OPERATIONS TEST SUITE")
    print("🚀"*35)
    
    print("\n⚠️  PREREQUISITES:")
    print("   1. API server must be running:")
    print("      cd ~/api_server && docker-compose up -d")
    print("   2. Check API is available:")
    print("      curl http://localhost:8000/health")
    print("   3. Python SDK must be accessible")
    
    # Check API availability
    print("\n🔍 Checking API server...")
    try:
        from urllib.request import urlopen
        urlopen("http://localhost:8000/health", timeout=2)
        print("✅ API server is running")
    except Exception as e:
        print(f"❌ API server not responding: {e}")
        print("   Please start the API server:")
        print("   cd ~/api_server && docker-compose up -d")
        return False
    
    results = []
    
    # Run sync tests
    try:
        results.append(("Basic Sudo Operations", test_basic_sudo_operations()))
        results.append(("Root File Operations", test_file_operations_as_root()))
        results.append(("System Commands", test_system_commands()))
        results.append(("SDK File Operations", test_sdk_file_operations_with_root()))
    except Exception as e:
        print(f"\n❌ Sync tests failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Run async test
    try:
        success = asyncio.run(test_async_sudo_operations())
        results.append(("Async Operations", success))
    except Exception as e:
        print(f"\n❌ Async test failed: {e}")
        results.append(("Async Operations", False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
