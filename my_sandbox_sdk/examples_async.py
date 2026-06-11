"""
Example usage of My Sandbox SDK - Asynchronous
"""

import asyncio
from my_sdk import AsyncSandbox


async def example_basic():
    """Basic async example: Create sandbox, run command, kill."""
    # Create sandbox
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    print(f"Created sandbox: {sandbox.sandbox_id}")
    
    # Run a simple command
    result = await sandbox.commands.run("echo 'Hello from async sandbox!'")
    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")
    
    # Kill sandbox
    await sandbox.kill()
    print("Sandbox killed")


async def example_with_context_manager():
    """Example using async context manager (auto-cleanup)."""
    async with await AsyncSandbox.create(api_url="http://localhost:8000") as sandbox:
        print(f"Sandbox {sandbox.sandbox_id} is running")
        
        # Check if running
        is_running = await sandbox.is_running()
        print(f"Is running: {is_running}")
        
        # Run command with environment variables
        result = await sandbox.commands.run(
            "echo $MY_VAR",
            env={"MY_VAR": "Hello World"}
        )
        print(f"Output: {result.stdout}")
    
    # Sandbox automatically killed on exit
    print("Sandbox cleaned up")


async def example_concurrent_commands():
    """Example: Running multiple commands concurrently."""
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    
    try:
        # Run multiple commands concurrently
        results = await asyncio.gather(
            sandbox.commands.run("echo 'Command 1'"),
            sandbox.commands.run("echo 'Command 2'"),
            sandbox.commands.run("echo 'Command 3'"),
        )
        
        for i, result in enumerate(results, 1):
            print(f"Command {i}: {result.stdout}")
        
    finally:
        await sandbox.kill()


async def example_filesystem():
    """Example: Async file operations."""
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    
    try:
        # Create directory
        await sandbox.files.create_directory("/tmp/myfiles")
        
        # Write file
        info = await sandbox.files.write(
            "/tmp/myfiles/hello.txt",
            "Hello from async!"
        )
        print(f"Wrote {info.bytes_written} bytes")
        
        # Read file
        content = await sandbox.files.read("/tmp/myfiles/hello.txt")
        print(f"Content: {content}")
        
        # List directory
        entries = await sandbox.files.list("/tmp/myfiles")
        for entry in entries:
            print(f"{entry.name} ({entry.type})")
        
        # Delete file
        await sandbox.files.delete("/tmp/myfiles/hello.txt")
        print("File deleted")
        
    finally:
        await sandbox.kill()


async def example_metrics():
    """Example: Getting sandbox metrics asynchronously."""
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    
    try:
        # Run some work
        await sandbox.commands.run("python3 -c \"sum(range(1000000))\"")
        
        # Get metrics
        metrics = await sandbox.metrics()
        print(f"CPU: {metrics.cpu_usage_percent}%")
        print(f"Memory: {metrics.memory_usage_bytes} bytes")
        print(f"Disk: {metrics.disk_usage_bytes} bytes")
        print(f"Uptime: {metrics.uptime_seconds}s")
        
    finally:
        await sandbox.kill()


async def main():
    """Run all async examples."""
    print("=== Basic Async Example ===")
    await example_basic()
    
    print("\n=== Async Context Manager Example ===")
    await example_with_context_manager()
    
    print("\n=== Concurrent Commands Example ===")
    await example_concurrent_commands()
    
    print("\n=== Async Filesystem Example ===")
    await example_filesystem()
    
    print("\n=== Async Metrics Example ===")
    await example_metrics()


if __name__ == "__main__":
    asyncio.run(main())
