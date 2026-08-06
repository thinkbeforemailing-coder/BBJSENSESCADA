import subprocess
import time
import sys
import signal
from pathlib import Path
from typing import Dict


from logging_config import setup_logger


BASE_DIR = Path(__file__).resolve().parent


VENV_PYTHON = (
    BASE_DIR
    / "venv"
    / "Scripts"
    / "python.exe"
)


POLLING_SCRIPT = (
    BASE_DIR
    / "dynamic_modbus_poller.py"
)


HEALTH_SCRIPT = (
    BASE_DIR
    / "gateway_health_reporter.py"
)


CHECK_INTERVAL = 5


logger = setup_logger(
    logger_name="startup-manager",
    log_filename="startup_manager.log",
)


running = True



def validate():

    files = [
        VENV_PYTHON,
        POLLING_SCRIPT,
        HEALTH_SCRIPT
    ]

    for f in files:
        if not f.exists():
            raise FileNotFoundError(
                f"Missing file: {f}"
            )

def start_process(
        name: str,
        script: Path
):

    logger.info(
        "Starting %s",
        name
    )

    logger.info(
        "Child Python=%s",
        VENV_PYTHON
    )

    return subprocess.Popen(
        [
            str(VENV_PYTHON),
            "-u",
            str(script)
        ],
        cwd=str(BASE_DIR),
        creationflags=subprocess.CREATE_NO_WINDOW
    )

def stop_handler(signum, frame):

    global running

    running = False



def main():

    validate()


    logger.info(
        "BBJ Sense Gateway Startup Manager"
    )

    logger.info(
        "Python executable: %s",
        VENV_PYTHON
    )

    print("DEBUG VENV PYTHON =", VENV_PYTHON)

    signal.signal(
        signal.SIGINT,
        stop_handler
    )


    signal.signal(
        signal.SIGTERM,
        stop_handler
    )


    processes: Dict[str, subprocess.Popen] = {}


    processes["Telemetry Poller"] = start_process(
        "Telemetry Poller",
        POLLING_SCRIPT
    )


    processes["Health Reporter"] = start_process(
        "Health Reporter",
        HEALTH_SCRIPT
    )


    logger.info(
        "All gateway components started successfully"
    )



    while running:


        for name, process in list(processes.items()):

            code = process.poll()


            if code is not None:

                logger.error(
                    "%s stopped. Exit code=%s",
                    name,
                    code
                )


                processes[name] = start_process(
                    name,
                    POLLING_SCRIPT
                    if name == "Telemetry Poller"
                    else HEALTH_SCRIPT
                )


        time.sleep(
            CHECK_INTERVAL
        )



    logger.info(
        "Stopping gateway"
    )


    for process in processes.values():

        if process.poll() is None:

            process.terminate()



if __name__ == "__main__":

    main()