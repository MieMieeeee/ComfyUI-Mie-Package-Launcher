import os
import threading
import subprocess
from core.launcher_cmd import build_launch_params


def cli_start(app):
    """
    Spawn ComfyUI subprocess without GUI dependencies.
    
    Returns:
        subprocess.Popen object if ComfyUI started successfully, None otherwise.
    """
    cmd, env, run_cwd, py, main = build_launch_params(app)
    
    # Validate paths
    if not py.exists():
        print(f"Error: Python executable not found at {py}")
        return None
    
    if not main.exists():
        print(f"Error: ComfyUI main.py not found at {main}")
        return None
    
    print("Starting ComfyUI...")
    
    try:
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                cmd, env=env, cwd=run_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=si,
            )
        else:
            process = subprocess.Popen(cmd, env=env, cwd=run_cwd)
    except Exception as e:
        print(f"Error starting ComfyUI: {e}")
        return None
    
    threading.Event().wait(2)
    
    if process.poll() is None:
        print(f"ComfyUI started successfully (PID: {process.pid})")
        return process
    else:
        print("ComfyUI process exited immediately")
        return None
