import time
import signal
import subprocess
import sys
import os
from pathlib import Path

from logging_config import setup_logger


# ==============================
# BASE CONFIGURATION
# ==============================

BASE_DIR = Path(__file__).resolve().parent

PYTHON = Path(sys.executable)

POLLING_SCRIPT = BASE_DIR / "dynamic_modbus_poller.py"
HEALTH_SCRIPT = BASE_DIR / "gateway_health_reporter.py"

WATCHDOG_INTERVAL_SECONDS = 5


# ==============================
# LOGGER INITIALIZATION
# ==============================

logger = setup_logger(
    logger_name="startup-manager",
    log_filename="startup_manager.log",
)


print("######## BBJ START GATEWAY ACTIVE ########", flush=True)
print("FILE:", __file__, flush=True)
print("PYTHON:", sys.executable, flush=True)
print("PID:", os.getpid(), flush=True)


logger.info(
    "ACTIVE START_GATEWAY FILE=%s",
    __file__
)

logger.info(
    "ACTIVE PYTHON=%s",
    sys.executable
)


components = [
    {
        "name": "Telemetry Poller",
        "script": POLLING_SCRIPT,
        "process": None,
        "restart_count": 0,
    },
    {
        "name": "Health Reporter",
        "script": HEALTH_SCRIPT,
        "process": None,
        "restart_count": 0,
    },
]

running = True


# ==============================
# START / RESTART CHILD PROCESS
# ==============================

def start_process(component):

    script = component["script"]

    if not script.exists():

        logger.error(
            "%s script not found: %s",
            component["name"],
            script
        )

        return


    logger.info(
        "Starting %s",
        component["name"]
    )

    logger.info(
        "Python executable: %s",
        PYTHON
    )

    logger.info(
        "Script: %s",
        script
    )


    creation_flags = 0

    if sys.platform.startswith("win"):
        creation_flags = subprocess.CREATE_NO_WINDOW


    process = subprocess.Popen(
        [
            str(PYTHON),
            "-u",
            str(script)
        ],
        cwd=str(BASE_DIR),
        creationflags=creation_flags
    )


    component["process"] = process


    logger.info(
        "%s started PID=%s",
        component["name"],
        process.pid
    )


# ==============================
# WATCHDOG
# ==============================

def check_components():

    for component in components:

        process = component["process"]

        if process is None:
            continue

        exit_code = process.poll()

        if exit_code is None:
            continue


        component["restart_count"] += 1

        logger.error(
            "%s exited unexpectedly | exit_code=%s | "
            "restarting | restart_count=%s",
            component["name"],
            exit_code,
            component["restart_count"],
        )

        start_process(component)


# ==============================
# STOP HANDLER
# ==============================

def stop_handler(signum, frame):

    global running

    logger.info(
        "Stop signal received"
    )

    running = False


    for component in components:

        process = component["process"]

        if process is None:
            continue

        try:

            logger.info(
                "Stopping PID=%s",
                process.pid
            )

            process.terminate()


        except Exception:

            logger.exception(
                "Stop error"
            )



# ==============================
# MAIN
# ==============================

def main():

    signal.signal(
        signal.SIGTERM,
        stop_handler
    )

    signal.signal(
        signal.SIGINT,
        stop_handler
    )


    logger.info(
        "================================"
    )

    logger.info(
        "BBJ Sense Gateway Starting"
    )

    logger.info(
        "Main Python: %s",
        sys.executable
    )

    logger.info(
        "Base directory: %s",
        BASE_DIR
    )

    logger.info(
        "================================"
    )


    for component in components:
        start_process(component)


    logger.info(
        "All gateway components started"
    )


    while running:

        time.sleep(WATCHDOG_INTERVAL_SECONDS)

        if running:
            check_components()


    logger.info(
        "BBJ Sense Gateway stopped"
    )



if __name__ == "__main__":
    main()
