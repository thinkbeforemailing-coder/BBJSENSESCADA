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

# nssm's own stop escalation (AppStopMethodConsole/Window/Threads, checked
# via `nssm get "BBJ Sense Gateway" AppStopMethod...`) is 1500ms per method
# with none skipped -- roughly 4.5s total before it hard-kills this very
# process regardless of what we're doing. If we wait longer than that per
# child, nssm can terminate *us* mid-wait in the genuinely-stuck case,
# silencing the critical alert below before it ever gets logged. Kept
# short and safely under that budget even with two children waited
# sequentially; a healthy process exits in milliseconds, so this only
# costs time when something is actually wrong.
CHILD_STOP_TIMEOUT_SECONDS = 1


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


    # Wait for each child to actually exit before this process (and
    # therefore the service restart) is considered complete. Without this,
    # a child stuck in an uncancelable wait (e.g. a hung serial driver, see
    # the 2026-08-07 COM-port zombie incident) survives as an orphan still
    # holding hardware resources, and the replacement instance started by
    # the next restart silently fails every operation against them.
    for component in components:

        process = component["process"]

        if process is None:
            continue

        try:

            process.wait(timeout=CHILD_STOP_TIMEOUT_SECONDS)

            logger.info(
                "PID=%s (%s) exited cleanly",
                process.pid,
                component["name"],
            )

        except subprocess.TimeoutExpired:

            # On Windows, Popen.kill() is just an alias for terminate()
            # (both call TerminateProcess), so retrying with kill() here
            # would not do anything different -- confirmed during the
            # 2026-08-07 incident, where Stop-Process -Force, taskkill /F,
            # and Win32_Process.Terminate() all failed identically against
            # a process blocked in a driver-level wait. There is nothing
            # more this process can do; surface it loudly instead of
            # silently letting a replacement start and collide with it.
            logger.critical(
                "PID=%s (%s) did NOT exit within %ss of terminate() -- "
                "likely stuck in an uncancelable driver-level wait. It may "
                "still hold a hardware handle (e.g. a serial port) that "
                "will block the next instance from working even though "
                "the service restart appears to succeed. Manual "
                "intervention required (see "
                "bbj-com-port-zombie-incident memory for the fix that "
                "worked last time: disable/re-enable the device in "
                "Device Manager).",
                process.pid,
                component["name"],
                CHILD_STOP_TIMEOUT_SECONDS,
            )

        except Exception:

            logger.exception(
                "Error waiting for PID=%s to stop",
                process.pid,
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
