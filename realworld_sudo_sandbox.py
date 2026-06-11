#!/usr/bin/env python3
"""
Real-World Sandbox Sudo Example: Web Server Setup

This script demonstrates a real-world scenario:
- Install a web server (nginx) requiring root
- Configure system settings requiring root
- Run privileged services
- Set up user accounts for the service

Perfect example of why sudo operations in sandboxes matter!
"""

import sys
import time
from pathlib import Path

SDK_PATH = Path(__file__).parent / "my_sandbox_sdk"
if SDK_PATH.exists():
    sys.path.insert(0, str(SDK_PATH))

from my_sdk import Sandbox


def main():
    print("\n" + "="*70)
    print("Real-World Example: Web Server Setup with Sudo")
    print("="*70)
    
    print("\n📦 Creating sandbox for web server...")
    sandbox = Sandbox.create(
        api_url="http://localhost:8000",
        api_key="test-key-12345",
        template_id="python:3.11"
    )
    print(f"✅ Sandbox: {sandbox.sandbox_id}")
    
    try:
        # Step 1: Update package manager
        print("\n[1/7] Updating package manager...")
        result = sandbox.commands.run("apt-get update -qq", timeout=30)
        if result.exit_code != 0:
            print(f"⚠️  Update output: {result.stderr[:100]}")
        else:
            print("✅ Package manager updated")
        
        # Step 2: Install nginx (requires root)
        print("\n[2/7] Installing nginx web server...")
        result = sandbox.commands.run(
            "apt-get install -y nginx -qq",
            timeout=60
        )
        if result.exit_code == 0:
            print("✅ Nginx installed")
        else:
            print(f"⚠️  Status: {result.exit_code}")
        
        # Step 3: Install other utilities (requires root)
        print("\n[3/7] Installing curl and vim...")
        result = sandbox.commands.run(
            "apt-get install -y curl vim -qq",
            timeout=60
        )
        print("✅ Utilities installed")
        
        # Step 4: Create app user for running services
        print("\n[4/7] Creating app service user...")
        result = sandbox.commands.run("useradd -m -s /bin/bash appserver")
        if result.exit_code == 0:
            print("✅ App user created")
        
        # Step 5: Set up directories (requires root)
        print("\n[5/7] Setting up app directories...")
        commands_to_run = [
            "mkdir -p /var/www/app",
            "chown -R appserver:appserver /var/www/app",
            "mkdir -p /var/log/app",
            "chown -R appserver:appserver /var/log/app"
        ]
        for cmd in commands_to_run:
            result = sandbox.commands.run(cmd)
            if result.exit_code != 0:
                print(f"   ⚠️  {cmd}: {result.stderr}")
        print("✅ Directories set up")
        
        # Step 6: Create a simple web config
        print("\n[6/7] Creating web server configuration...")
        config = """
server {
    listen 8080;
    server_name localhost;
    root /var/www/app;
    
    location / {
        try_files $uri $uri/ =404;
    }
}
"""
        result = sandbox.commands.run(
            f"echo '{config}' > /etc/nginx/sites-available/app"
        )
        print("✅ Configuration created")
        
        # Step 7: Enable site and test configuration
        print("\n[7/7] Enabling site and testing nginx...")
        commands_to_run = [
            "ln -sf /etc/nginx/sites-available/app /etc/nginx/sites-enabled/app",
            "rm -f /etc/nginx/sites-enabled/default",
            "nginx -t"  # Test configuration
        ]
        for cmd in commands_to_run:
            result = sandbox.commands.run(cmd)
            if result.exit_code == 0:
                print(f"   ✅ {cmd.split()[0]}")
            else:
                print(f"   ⚠️  {cmd}: {result.stderr[:100]}")
        
        # Verify setup
        print("\n" + "-"*70)
        print("VERIFICATION")
        print("-"*70)
        
        # Check nginx is installed
        print("\n✔️  Nginx version:")
        result = sandbox.commands.run("nginx -v 2>&1")
        print(f"   {result.stdout.strip() if result.stdout else result.stderr.strip()}")
        
        # Check users exist
        print("\n✔️  System users created:")
        result = sandbox.commands.run("grep -E 'appserver|appuser' /etc/passwd")
        for line in result.stdout.strip().split('\n'):
            if line:
                user = line.split(':')[0]
                print(f"   - {user}")
        
        # Check directories
        print("\n✔️  App directories:")
        result = sandbox.commands.run("ls -la /var/www/ | grep app")
        print(f"   {result.stdout.strip()}")
        
        # Check permissions
        print("\n✔️  Directory permissions:")
        result = sandbox.commands.run("ls -la /var/www/app | head -1")
        print(f"   {result.stdout.strip()}")
        
        # What could be done next
        print("\n" + "-"*70)
        print("NEXT STEPS (What you could do)")
        print("-"*70)
        print("""
✅ This sandbox now has:
   • Nginx web server installed
   • App user 'appserver' created
   • Directories configured with proper permissions
   • Configuration file ready
   
You could now:
   1. Start nginx: sandbox.commands.run('service nginx start')
   2. Deploy code to /var/www/app
   3. Run database migrations
   4. Configure firewall rules
   5. Set up SSL certificates
   6. Start monitoring services
   
All while maintaining full root access for privileged operations!
        """)
        
    finally:
        print("\n" + "="*70)
        print("Cleaning up...")
        sandbox.kill()
        print("✅ Sandbox terminated")
    
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
