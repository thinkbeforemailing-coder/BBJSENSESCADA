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


processes = []

running = True


# ==============================
# START CHILD PROCESS
# ==============================

def start_process(name, script):

    if not script.exists():

        logger.error(
            "%s script not found: %s",
            name,
            script
        )

        return


    logger.info(
        "Starting %s",
        name
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


    processes.append(process)


    logger.info(
        "%s started PID=%s",
        name,
        process.pid
    )


# ==============================
# STOP HANDLER
# ==============================

def stop_handler(signum, frame):

    global running

    logger.info(
        "Stop signal received"
    )

    running = False


    for process in processes:

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


    start_process(
        "Telemetry Poller",
        POLLING_SCRIPT
    )


    start_process(
        "Health Reporter",
        HEALTH_SCRIPT
    )


    logger.info(
        "All gateway components started"
    )


    while running:

        time.sleep(5)


    logger.info(
        "BBJ Sense Gateway stopped"
    )



if __name__ == "__main__":
    main()