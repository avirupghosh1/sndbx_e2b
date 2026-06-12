import sys
import os
import time
from pathlib import Path
import csv
import subprocess

from datetime import datetime


SDK_PATH = Path(__file__).parent / "my_sandbox_sdk"
if SDK_PATH.exists():
    sys.path.insert(0, str(SDK_PATH))

from my_sdk import Sandbox, AsyncSandbox

def main():
    # result = subprocess.run("docker ps -a", shell=True, capture_output=True, text=True)
    # print(result.stdout)
    sandbox = Sandbox.create(
        api_url="http://localhost:8000", 
        api_key="test-key-12345", # example authentication not done properly yet, dummy value
        template_id="node:18", 
        request_timeout=900.0,
        )
    # cont = 0
    # cont2 = 0
    # iterations = 20

    # for i in range(iterations):
    #     if (i % 2):
    #         template_id = "node:18"
    #     else:
    #         template_id = "python:3.11"

    #     now1 = datetime.now()
    #     sandbox = Sandbox.create(
    #         api_url="http://localhost:8000",
    #         api_key="test-key-12345",
    #         template_id=template_id,
    #         request_timeout=900.0,
    #     )
    #     now2 = datetime.now()
    #     cont += float(now2.timestamp() - now1.timestamp())

    #     now3 = datetime.now()
    #     sandbox.files.write("/tmp/sdk_test.txt", "Hello from SDK!")
    #     now4 = datetime.now()
    #     cont2 += float(now4.timestamp() - now3.timestamp())

    #     sandbox.kill()
    #     print(f"Iteration {i+1} completed.")

    # avg_boot = cont / iterations
    # avg_file = cont2 / iterations

    # csvf = "results.csv"
    # file_exists = os.path.isfile(csvf)
    # engine = os.environ.get('SANDBOX_ENGINE')
    # if(engine!="firecracker"):
    #     engine = os.environ.get('SANDBOX_ISOLATION')
    
    # with open(csvf, "a", newline="") as f:
    #     writer = csv.DictWriter(f, fieldnames=[
    #         "timestamp", "engine", "iterations", "avg_boot_s", "avg_file_write_s"
    #     ])
    #     if not file_exists:
    #         writer.writeheader()
    #     writer.writerow({
    #         "timestamp": datetime.now().isoformat(),
    #         "engine": engine,
    #         "iterations": iterations,
    #         "avg_boot_s": round(avg_boot, 3),
    #         "avg_file_write_s": round(avg_file, 3),
    #     })

    # print(f"\nResults written to {csvf}")
    # print(f"Avg boot time:       {avg_boot:.3f}s")
    # print(f"Avg file write time: {avg_file:.3f}s")

    # #making files
   
    # # print(f"File write took {(now4-now3)} seconds")
    sandbox.files.write("/tmp/my_test.py", "print('This is a test file created by the SDK.')")
    sandbox.commands.run("mkdir -p /tmp/test_dir")
    result = sandbox.commands.run("uname -a", timeout=30.0)
    print("Sandbox uname:", result.stdout.strip())
    # # # Streaming: print each chunk as the API delivers it (flush so you see it immediately).
    # # Without a TTY, shells often block-buffer stdout; stdbuf -oL forces line buffering so
    # # each "echo" line can arrive before the next sleep (GNU coreutils; present on node images).
    # # stream_cmd = (
    # #     "stdbuf -oL sh -c 'for i in 1 2 3; do echo step$i; sleep 1; done'"
    # # )
    # # print("--- stream (should appear ~1s apart) ---", flush=True)
    # # for ev in sandbox.commands.run_stream(stream_cmd, timeout=60.0):
    # #     t = ev.get("type")
    # #     if t == "stdout":
    # #         print(ev.get("chunk", ""), end="", flush=True) #KEEPS FLUSHING IMMEDIATELY
    # #     elif t == "stderr":
    # #         print(ev.get("chunk", ""), end="", file=sys.stderr, flush=True)
    # #     elif t == "error":
    # #         print(f"\n[stream error] {ev.get('message')}", flush=True)
    # #     elif t == "exit":
    # #         print(f"\n[exit code] {ev.get('exit_code')}", flush=True)
    # # print(sandbox.files.list("/tmp"))
    # #creating snapshot after setup

    # # # result = subprocess.run("docker ps -a", shell=True, capture_output=True, text=True)
    # # # print(result.stdout)
    # # #running python file using the SDK's helper method
    # resu = sandbox.files.read("/tmp/my_test.py")
    # # repr() only returns a string — print it to see exact leading chars (e.g. \\x00 vs "0").
    # print("repr(file):", repr(resu))
    # print("File content read from sandbox:", resu)
    # print(sandbox.commands.run_python(resu).stdout.strip())
    # print(1)
    # #deleting files and sandbox
    # # sandbox.files.delete("/tmp/sdk_test.txt")
    # # # time.sleep(20)
    snp= sandbox.create_snapshot() 
    sandbox.kill()
    # # # result = subprocess.run("docker ps -a", shell=True, capture_output=True, text=True)
    # # # print(result.stdout)
    sd2= Sandbox.create(
         api_url="http://localhost:8000", 
        api_key="test-key-12345", # example authentication not done properly yet, dummy value
        template_id="python:3.11", # similar to e2b passing a template, we specify a base image here; in the future we can support more complex templates with files, env vars, etc.
        request_timeout=900.0,
        from_snapshot_image=snp.image_ref, # creating new sandbox from sna
    )

    print(sd2.files.list("/tmp")) 
    sd2.kill()# verify we have the same files as the snapshot
    print("Sandbox deleted.")
main()