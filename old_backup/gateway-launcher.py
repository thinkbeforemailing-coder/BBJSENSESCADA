import subprocess
import time
import signal
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


PYTHON = BASE_DIR / "venv" / "Scripts" / "python.exe"

START = BASE_DIR / "start_gateway.py"


process = None


def stop_handler(signum, frame):

    global process

    print("Stopping BBJ Gateway")

    if process:

        process.terminate()

    sys.exit(0)



signal.signal(
    signal.SIGTERM,
    stop_handler
)


signal.signal(
    signal.SIGINT,
    stop_handler
)



print("BBJ Gateway Launcher Started")


process = subprocess.Popen(
    [
        str(PYTHON),
        "-u",
        str(START)
    ],
    cwd=str(BASE_DIR)
)



print(
    "Gateway PID:",
    process.pid
)



while True:

    status = process.poll()


    if status is not None:

        print(
            "Gateway stopped:",
            status
        )

        break


    time.sleep(5)