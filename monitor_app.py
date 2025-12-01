import time
import subprocess
import re

def run_adb(cmd):
    return subprocess.getoutput(f"adb -s emulator-5554 shell {cmd}")

print("Starting monitor...")
package = "org.fdroid.fdroid"
activity = "org.fdroid.fdroid.views.main.MainActivity"

# Launch app
print(f"Launching {package}...")
run_adb(f"am start -n {package}/{activity}")

for i in range(20):
    time.sleep(1)
    pid = run_adb(f"pidof {package}")
    
    # Get focus
    dumpsys = run_adb("dumpsys window displays")
    focus_match = re.search(r"mCurrentFocus=Window\{.* ([\S]+)\}", dumpsys)
    focus = focus_match.group(1) if focus_match else "Unknown"
    
    print(f"[{i}s] PID: {pid.strip()}, Focus: {focus}")

print("Monitor finished.")
