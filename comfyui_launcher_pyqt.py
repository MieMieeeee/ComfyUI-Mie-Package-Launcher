import os
import sys
from utils.common import SingletonLock
from ui_qt.qt_app import PyQtLauncher

if __name__ == "__main__":
    lock = SingletonLock("comfyui_launcher_pyqt.lock")
    if not lock.acquire():
        sys.exit(0)
    try:
        app = PyQtLauncher()
        app.run()
    finally:
        lock.release()
