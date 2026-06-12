"""GPU-free stand-in for a real worker (wan_load.py / moments_flux.py): prints
progress lines on a cadence so the proc-runner's streaming + supervision can be
tested without a model or a GPU. argv: [steps] [delay_s]."""
import sys
import time

steps = int(sys.argv[1]) if len(sys.argv) > 1 else 5
delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
for i in range(steps):
    print(f"step {i + 1}/{steps} progress={(i + 1) / steps:.2f}", flush=True)
    time.sleep(delay)
print("worker complete", flush=True)
