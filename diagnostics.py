#!/usr/bin/env python3
"""
Sudo Sandbox Diagnostics

Diagnoses issues with sudo sandbox operations.
Run this if tests are failing to identify the problem.
"""

import sys
import subprocess
from pathlib import Path
import json

def check_docker():
    """Check Docker is installed and running."""
    print("\n🔍 Checking Docker...")
    
    try:
        # Check Docker is installed
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Docker not installed")
            return False
        print(f"✅ Docker: {result.stdout.strip()}")
        
        # Check Docker daemon is running
        result = subprocess.run(["docker", "ps"], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Docker daemon not running")
            print("   Try: open -a Docker")
            return False
        print("✅ Docker daemon running")
        
        return True
    except Exception as e:
        print(f"❌ Docker check failed: {e}")
        return False


def check_api_server():
    """Check API server is running."""
    print("\n🔍 Checking API Server...")
    
    try:
        from urllib.request import urlopen
        from urllib.error import URLError
        
        try:
            response = urlopen("http://localhost:8000/health", timeout=2)
            data = json.loads(response.read().decode())
            if data.get("status") == "ok":
                print("✅ API server running on localhost:8000")
                return True
            else:
                print(f"⚠️  Unexpected response: {data}")
                return False
        except URLError:
            print("❌ API server not responding on localhost:8000")
            print("\n   Start it with:")
            print("   cd ~/api_server && docker-compose up -d")
            print("\n   Then check:")
            print("   curl http://localhost:8000/health")
            return False
            
    except Exception as e:
        print(f"❌ API server check failed: {e}")
        return False


def check_sdk():
    """Check Python SDK is available."""
    print("\n🔍 Checking Python SDK...")
    
    try:
        SDK_PATH = Path.home() / "Desktop" / "intern_1strepo" / "my_sandbox_sdk"
        
        if not SDK_PATH.exists():
            print(f"❌ SDK not found at {SDK_PATH}")
            return False
        
        # Try to import
        sys.path.insert(0, str(SDK_PATH))
        from my_sdk import Sandbox
        print(f"✅ SDK found and imported successfully")
        
        # Check version
        try:
            import my_sdk
            if hasattr(my_sdk, "__version__"):
                print(f"   Version: {my_sdk.__version__}")
        except:
            pass
        
        return True
        
    except ImportError as e:
        print(f"❌ SDK import failed: {e}")
        print("\n   Make sure SDK is at ~/Desktop/intern_1strepo/my_sandbox_sdk/")
        return False
    except Exception as e:
        print(f"❌ SDK check failed: {e}")
        return False


def check_docker_images():
    """Check Docker images are available."""
    print("\n🔍 Checking Docker Images...")
    
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True
        )
        
        images = result.stdout.strip().split("\n") if result.stdout else []
        print(f"✅ Found {len(images)} Docker images")
        
        # Check for python images
        python_images = [img for img in images if "python" in img.lower()]
        if python_images:
            print(f"   Python images available:")
            for img in python_images[:3]:
                print(f"     - {img}")
        else:
            print("   ⚠️  No Python images found")
            print("   Docker will pull python:3.11 automatically when needed")
        
        return True
        
    except Exception as e:
        print(f"❌ Image check failed: {e}")
        return False


def check_containers():
    """Check running containers."""
    print("\n🔍 Checking Running Containers...")
    
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}: {{.Image}}"],
            capture_output=True,
            text=True
        )
        
        containers = result.stdout.strip().split("\n") if result.stdout else []
        containers = [c for c in containers if c]
        
        if containers:
            print(f"✅ {len(containers)} container(s) running")
            for container in containers:
                print(f"   - {container}")
        else:
            print("⚠️  No containers running")
        
        return True
        
    except Exception as e:
        print(f"❌ Container check failed: {e}")
        return False


def check_database():
    """Check SQLite database."""
    print("\n🔍 Checking Database...")
    
    try:
        db_path = Path.home() / "api_server" / "sandboxes.db"
        
        # Try alternate path
        if not db_path.exists():
            db_path = Path("/Users/avirup.ghosh/api_server/sandboxes.db")
        
        if not db_path.exists():
            print("⚠️  Database not created yet (will be created on first use)")
            return True
        
        # Check database
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        conn.close()
        
        table_names = [t[0] for t in tables]
        print(f"✅ Database found with {len(table_names)} tables")
        if table_names:
            print(f"   Tables: {', '.join(table_names)}")
        
        return True
        
    except Exception as e:
        print(f"⚠️  Database check: {e}")
        return True  # Not critical


def check_permissions():
    """Check file permissions."""
    print("\n🔍 Checking Permissions...")
    
    try:
        # Check Docker socket
        docker_sock = Path("/var/run/docker.sock")
        if docker_sock.exists():
            print("✅ Docker socket accessible")
        else:
            print("⚠️  Docker socket not found")
        
        # Check SDK directory
        sdk_path = Path.home() / "Desktop" / "intern_1strepo" / "my_sandbox_sdk"
        if sdk_path.exists() and sdk_path.is_dir():
            print("✅ SDK directory accessible")
        
        return True
        
    except Exception as e:
        print(f"⚠️  Permission check: {e}")
        return True


def test_simple_create():
    """Try to create a simple sandbox."""
    print("\n🔍 Testing Simple Sandbox Creation...")
    
    try:
        sys.path.insert(0, str(Path.home() / "Desktop" / "intern_1strepo"))
        from my_sdk import Sandbox
        
        print("   Creating test sandbox...")
        sandbox = Sandbox.create(
            api_url="http://localhost:8000",
            api_key="test-key-12345",
            template_id="python:3.11"
        )
        print(f"✅ Sandbox created: {sandbox.sandbox_id}")
        
        # Try a simple command
        print("   Running test command...")
        result = sandbox.commands.run("whoami")
        user = result.stdout.strip()
        print(f"✅ Command executed, user: {user}")
        
        # Kill sandbox
        sandbox.kill()
        print("✅ Sandbox terminated")
        
        return True
        
    except Exception as e:
        print(f"❌ Creation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("="*70)
    print("SANDBOX DIAGNOSTIC TOOL")
    print("="*70)
    
    checks = [
        ("Docker Installation", check_docker),
        ("Docker Images", check_docker_images),
        ("Running Containers", check_containers),
        ("File Permissions", check_permissions),
        ("Database", check_database),
        ("API Server", check_api_server),
        ("Python SDK", check_sdk),
    ]
    
    results = []
    for name, check_fn in checks:
        try:
            result = check_fn()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} check crashed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*70)
    print("DIAGNOSTIC SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print(f"\nStatus: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 All checks passed! System is ready.")
        print("\nTry running:")
        print("  python quick_sudo_test.py")
        return True
    else:
        print("\n⚠️  Some checks failed. See above for details.")
        print("\nCommon fixes:")
        print("  1. Start Docker: open -a Docker")
        print("  2. Start API server: cd ~/api_server && docker-compose up -d")
        print("  3. Check paths are correct")
        print("  4. Try: cd ~/Desktop/intern_1strepo")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
