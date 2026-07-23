import subprocess
import os

os.chdir(r"c:\Users\lefte\Documents\antigravity\video-downloader")

env = dict(os.environ)
env["GIT_TERMINAL_PROMPT"] = "0"
env["GCM_INTERACTIVE"] = "never"

lock_file = os.path.join(".git", "index.lock")
if os.path.exists(lock_file):
    try: os.remove(lock_file)
    except: pass

print("--- GIT COMMIT ---")
r3 = subprocess.run(["git", "commit", "-am", "feat: v1.4 final updates and Media Tools improvements"], capture_output=True, text=True, env=env)
print("COMMIT STDOUT:", r3.stdout)
print("COMMIT STDERR:", r3.stderr)

print("--- GIT PUSH ---")
r4 = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, env=env)
print("PUSH STDOUT:", r4.stdout)
print("PUSH STDERR:", r4.stderr)
