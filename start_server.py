# start_server.py
import os
import subprocess
import sys

PORT = 5002

# ----------------------------
# Step 1: Kill processes on the port
# ----------------------------
print(f"[INFO] Checking for processes on port {PORT}...")
if os.name == "nt":  # Windows
    try:
        # Get PIDs listening on the port
        result = subprocess.run(
            f'netstat -ano | findstr {PORT}', capture_output=True, text=True, shell=True
        )
        lines = result.stdout.strip().splitlines()
        pids = set()
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                pids.add(parts[-1])
        if pids:
            for pid in pids:
                print(f"[INFO] Killing PID {pid}...")
                subprocess.run(f"taskkill /PID {pid} /F", shell=True)
        else:
            print("[INFO] No process found on port.")
    except Exception as e:
        print("[ERROR] Could not check/kill processes:", e)
else:
    print("[ERROR] This script is designed for Windows only.")

# ----------------------------
# Step 2: Start Flask server
# ----------------------------
print("[INFO] Starting Flask server...")
try:
    subprocess.run([sys.executable, "server.py"])
except Exception as e:
    print("[ERROR] Failed to start server:", e)
