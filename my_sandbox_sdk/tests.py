"""
Quick start tests for My Sandbox SDK.

Run these tests after setting up your API server.
"""

import pytest
import asyncio
from my_sdk import Sandbox, AsyncSandbox, SandboxException, SandboxNotFoundException


# Set your API server URL here
API_URL = "http://localhost:8000"


class TestSandboxSync:
    """Tests for synchronous SDK."""
    
    def test_create_sandbox(self):
        """Test creating a sandbox."""
        try:
            sandbox = Sandbox.create(api_url=API_URL)
            assert sandbox.sandbox_id
            assert sandbox.api_url == API_URL
            sandbox.kill()
        except SandboxException as e:
            pytest.skip(f"API server not available: {e}")
    
    def test_run_command(self):
        """Test running a command."""
        try:
            with Sandbox.create(api_url=API_URL) as sandbox:
                result = sandbox.commands.run("echo 'hello'")
                assert result.exit_code == 0
                assert "hello" in result.stdout
        except SandboxException:
            pytest.skip("API server not available")
    
    def test_sandbox_info(self):
        """Test getting sandbox info."""
        try:
            sandbox = Sandbox.create(api_url=API_URL)
            info = sandbox.info()
            assert info.sandbox_id == sandbox.sandbox_id
            sandbox.kill()
        except SandboxException:
            pytest.skip("API server not available")


class TestSandboxAsync:
    """Tests for asynchronous SDK."""
    
    @pytest.mark.asyncio
    async def test_create_sandbox_async(self):
        """Test creating a sandbox asynchronously."""
        try:
            sandbox = await AsyncSandbox.create(api_url=API_URL)
            assert sandbox.sandbox_id
            await sandbox.kill()
        except SandboxException:
            pytest.skip("API server not available")
    
    @pytest.mark.asyncio
    async def test_run_command_async(self):
        """Test running a command asynchronously."""
        try:
            async with await AsyncSandbox.create(api_url=API_URL) as sandbox:
                result = await sandbox.commands.run("echo 'hello async'")
                assert result.exit_code == 0
                assert "hello" in result.stdout
        except SandboxException:
            pytest.skip("API server not available")
    
    @pytest.mark.asyncio
    async def test_concurrent_commands(self):
        """Test running concurrent commands."""
        try:
            sandbox = await AsyncSandbox.create(api_url=API_URL)
            
            results = await asyncio.gather(
                sandbox.commands.run("echo '1'"),
                sandbox.commands.run("echo '2'"),
                sandbox.commands.run("echo '3'"),
            )
            
            assert len(results) == 3
            assert all(r.exit_code == 0 for r in results)
            
            await sandbox.kill()
        except SandboxException:
            pytest.skip("API server not available")


# Quick manual test
if __name__ == "__main__":
    print("Running manual tests...")
    print("Make sure your API server is running at", API_URL)
    
    try:
        print("\n1. Creating sandbox...")
        sandbox = Sandbox.create(api_url=API_URL)
        print(f"   Created: {sandbox.sandbox_id}")
        
        print("\n2. Running command...")
        result = sandbox.commands.run("echo 'Hello from My Sandbox SDK!'")
        print(f"   Output: {result.stdout.strip()}")
        print(f"   Exit code: {result.exit_code}")
        
        print("\n3. Getting sandbox info...")
        info = sandbox.info()
        print(f"   State: {info.state}")
        print(f"   Created at: {info.created_at}")
        
        print("\n4. Killing sandbox...")
        sandbox.kill()
        print("   Killed!")
        
        print("\nAll tests passed!")
        
    except SandboxException as e:
        print(f"Error: {e}")
        print("Make sure your API server is running at", API_URL)
