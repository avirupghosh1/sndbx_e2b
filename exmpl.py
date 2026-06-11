import os
import time
from e2b import Sandbox
from openai import OpenAI

# Ensure API keys are set
if not os.getenv("E2B_API_KEY") or not os.getenv("OPENAI_API_KEY"):
    raise EnvironmentError("Please set E2B_API_KEY and OPENAI_API_KEY.")

# Initialize OpenAI client
client = OpenAI()

# Start E2B sandbox
sandbox = Sandbox.start(template="python3")
print(f"Sandbox started: {sandbox.id}")

# Agent goal
goal = "Find the first 10 prime numbers and save them to primes.txt"

# Agent loop
try:
    context = f"Goal: {goal}\n"
    for step in range(5):  # Limit steps to avoid infinite loops
        print(f"\n--- Step {step+1} ---")

        # Ask LLM what to do next
        prompt = f"""
You are an autonomous Python agent running in a sandbox.
{context}
Decide the next Python code to run to achieve the goal.
Only output Python code, no explanations.
"""
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        code_to_run = llm_response.choices[0].message.content.strip()
        print("Generated code:\n", code_to_run)

        # Run code in sandbox
        run_result = sandbox.run_code(code_to_run)

        # Show output
        print("STDOUT:", run_result.stdout)
        print("STDERR:", run_result.stderr)

        # Update context with results
        context += f"\nCode run:\n{code_to_run}\nOutput:\n{run_result.stdout}\nErrors:\n{run_result.stderr}\n"

        # Check if goal is done
        if "primes.txt" in sandbox.list_files():
            print("✅ Goal achieved! File created.")
            file_content = sandbox.download_file("primes.txt").decode()
            print("File content:", file_content)
            break

        time.sleep(1)

finally:
    sandbox.stop()
    print("Sandbox stopped.")
