import subprocess
import sys
import time
from pathlib import Path
from typing import Dict

from logging_config import setup_logger


BASE_DIR = Path(__file__).resolve().parent

POLLING_SCRIPT = BASE_DIR / "dynamic_modbus_poller.py"
HEALTH_SCRIPT = BASE_DIR / "gateway_health_reporter.py"

PROCESS_CHECK_INTERVAL_SECONDS = 5
PROCESS_RESTART_DELAY_SECONDS = 3

logger = setup_logger(
    logger_name="startup-manager",
    log_filename="startup_manager.log",
)


def validate_script(script_path: Path) -> None:
    """Ensure a required gateway script exists."""
    if not script_path.exists():
        raise FileNotFoundError(
            f"Required script not found: {script_path}"
        )


def start_process(
    process_name: str,
    script_path: Path,
) -> subprocess.Popen:
    """Start a gateway subprocess using the active Python."""
    logger.info(
        "Starting %s using %s",
        process_name,
        script_path.name,
    )

    process = subprocess.Popen(
        [
            sys.executable,
            str(script_path),
        ],
        cwd=str(BASE_DIR),
    )

    logger.info(
        "%s started | PID=%s",
        process_name,
        process.pid,
    )

    return process


def stop_process(
    process_name: str,
    process: subprocess.Popen,
) -> None:
    """Stop a child process safely."""
    if process.poll() is not None:
        return

    logger.info("Stopping %s...", process_name)

    process.terminate()

    try:
        process.wait(timeout=10)

    except subprocess.TimeoutExpired:
        logger.warning(
            "%s did not stop normally; forcing shutdown",
            process_name,
        )

        process.kill()
        process.wait(timeout=5)

    logger.info("%s stopped", process_name)


def main() -> None:
    validate_script(POLLING_SCRIPT)
    validate_script(HEALTH_SCRIPT)

    logger.info("BBJ Sense Gateway Startup Manager")
    logger.info("Gateway directory: %s", BASE_DIR)
    logger.info("Python executable: %s", sys.executable)

    process_definitions = {
        "Telemetry Poller": POLLING_SCRIPT,
        "Health Reporter": HEALTH_SCRIPT,
    }

    processes: Dict[str, subprocess.Popen] = {}

    try:
        for process_name, script_path in (
            process_definitions.items()
        ):
            processes[process_name] = start_process(
                process_name=process_name,
                script_path=script_path,
            )

        logger.info(
            "All gateway components started successfully"
        )

        while True:
            for process_name, script_path in (
                process_definitions.items()
            ):
                process = processes[process_name]
                return_code = process.poll()

                if return_code is None:
                    continue

                logger.error(
                    "%s stopped unexpectedly | exit_code=%s",
                    process_name,
                    return_code,
                )

                logger.info(
                    "Restarting %s after %s seconds",
                    process_name,
                    PROCESS_RESTART_DELAY_SECONDS,
                )

                time.sleep(
                    PROCESS_RESTART_DELAY_SECONDS
                )

                processes[process_name] = start_process(
                    process_name=process_name,
                    script_path=script_path,
                )

            time.sleep(
                PROCESS_CHECK_INTERVAL_SECONDS
            )

    except KeyboardInterrupt:
        logger.info(
            "Shutdown requested by user"
        )

    except Exception as error:
        logger.exception(
            "Gateway startup manager failed: %s",
            error,
        )

    finally:
        for process_name, process in processes.items():
            try:
                stop_process(
                    process_name=process_name,
                    process=process,
                )
            except Exception as error:
                logger.exception(
                    "Failed to stop %s cleanly: %s",
                    process_name,
                    error,
                )

        logger.info(
            "BBJ Sense Gateway stopped"
        )


if __name__ == "__main__":
    main()