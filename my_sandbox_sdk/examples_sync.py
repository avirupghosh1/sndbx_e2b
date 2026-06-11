"""
Example usage of My Sandbox SDK - Synchronous
"""

from my_sdk import Sandbox


def example_basic():
    """Basic example: Create sandbox, run command, kill."""
    # Create sandbox
    sandbox = Sandbox.create(api_url="http://localhost:8000")
    print(f"Created sandbox: {sandbox.sandbox_id}")
    
    # Run a simple command
    result = sandbox.commands.run("echo 'Hello from sandbox!'")
    print(f"Exit code: {result.exit_code}")
    print(f"Output: {result.stdout}")
    
    # Kill sandbox
    sandbox.kill()
    print("Sandbox killed")


def example_with_context_manager():
    """Example using context manager (auto-cleanup)."""
    with Sandbox.create(api_url="http://localhost:8000") as sandbox:
        print(f"Sandbox {sandbox.sandbox_id} is running")
        
        # Check if running
        is_running = sandbox.is_running()
        print(f"Is running: {is_running}")
        
        # Run command with environment variables
        result = sandbox.commands.run(
            "echo $MY_VAR",
            env={"MY_VAR": "Hello World"}
        )
        print(f"Output: {result.stdout}")
    
    # Sandbox automatically killed on exit
    print("Sandbox cleaned up")


def example_commands():
    """Example: Running various commands."""
    sandbox = Sandbox.create(api_url="http://localhost:8000")
    
    try:
        # Python code execution
        result = sandbox.commands.run(
            "python3 -c \"print('Hello from Python')\""
        )
        print(result.stdout)
        
        # Running shell script
        result = sandbox.commands.run(
            "bash -c 'for i in 1 2 3; do echo $i; done'"
        )
        print(result.stdout)
        
        # Get list of running processes
        processes = sandbox.commands.list()
        print(f"Running processes: {len(processes)}")
        for proc in processes:
            print(f"  PID {proc.pid}: {proc.cmd}")
        
    finally:
        sandbox.kill()


def example_filesystem():
    """Example: File operations."""
    sandbox = Sandbox.create(api_url="http://localhost:8000")
    
    try:
        # Create directory
        sandbox.files.create_directory("/tmp/myfiles")
        
        # Write file
        info = sandbox.files.write(
            "/tmp/myfiles/hello.txt",
            "Hello, World!"
        )
        print(f"Wrote {info.bytes_written} bytes")
        
        # Read file
        content = sandbox.files.read("/tmp/myfiles/hello.txt")
        print(f"Content: {content}")
        
        # List directory
        entries = sandbox.files.list("/tmp/myfiles")
        for entry in entries:
            print(f"{entry.name} ({entry.type})")
        
        # Upload local file
        # sandbox.files.upload("local_file.txt", "/tmp/myfiles/uploaded.txt")
        
        # Download file
        # sandbox.files.download("/tmp/myfiles/hello.txt", "downloaded.txt")
        
        # Delete file
        sandbox.files.delete("/tmp/myfiles/hello.txt")
        print("File deleted")
        
    finally:
        sandbox.kill()


def example_metrics():
    """Example: Getting sandbox metrics."""
    sandbox = Sandbox.create(api_url="http://localhost:8000")
    
    try:
        # Run some work
        sandbox.commands.run("python3 -c \"sum(range(1000000))\"")
        
        # Get metrics
        metrics = sandbox.metrics()
        print(f"CPU: {metrics.cpu_usage_percent}%")
        print(f"Memory: {metrics.memory_usage_bytes} bytes")
        print(f"Disk: {metrics.disk_usage_bytes} bytes")
        print(f"Uptime: {metrics.uptime_seconds}s")
        
    finally:
        sandbox.kill()


if __name__ == "__main__":
    print("=== Basic Example ===")
    example_basic()
    
    print("\n=== Context Manager Example ===")
    example_with_context_manager()
    
    print("\n=== Commands Example ===")
    example_commands()
    
    print("\n=== Filesystem Example ===")
    example_filesystem()
    
    print("\n=== Metrics Example ===")
    example_metrics()
