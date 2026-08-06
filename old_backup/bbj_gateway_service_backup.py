import sys
import subprocess
import time
from pathlib import Path
from typing import Optional

import win32event
import win32service
import win32serviceutil

from logging_config import setup_logger


BASE_DIR = Path(__file__).resolve().parent

PYTHON_EXE = BASE_DIR / "venv" / "Scripts" / "python.exe"

START_SCRIPT = BASE_DIR / "start_gateway.py"


logger = setup_logger(
    logger_name="windows-service",
    log_filename="windows_service.log",
)


class BBJSenseGatewayService(
    win32serviceutil.ServiceFramework
):

    _svc_name_ = "BBJSenseGateway"

    _svc_display_name_ = (
        "BBJ Sense Gateway"
    )

    _svc_description_ = (
        "BBJ Sense Industrial Gateway Service"
    )


    def __init__(self, args):

        super().__init__(args)

        self.stop_event = win32event.CreateEvent(
            None,
            0,
            0,
            None
        )

        self.process: Optional[subprocess.Popen] = None



    def SvcStop(self):

        logger.info(
            "Windows service stop requested"
        )

        self.ReportServiceStatus(
            win32service.SERVICE_STOP_PENDING
        )

        if self.process:

            try:
                self.process.terminate()

            except Exception:
                pass


        win32event.SetEvent(
            self.stop_event
        )



    def SvcDoRun(self):

        logger.info(
            "BBJ Sense Gateway service starting"
        )


        logger.info(
            "Python: %s",
            PYTHON_EXE
        )


        logger.info(
            "Startup script: %s",
            START_SCRIPT
        )


        self.process = subprocess.Popen(
            [
                str(PYTHON_EXE),
                "-u",
                str(START_SCRIPT)
            ],
            cwd=str(BASE_DIR)
        )


        logger.info(
            "Gateway PID=%s",
            self.process.pid
        )


        while True:

            rc = win32event.WaitForSingleObject(
                self.stop_event,
                5000
            )

            if rc == win32event.WAIT_OBJECT_0:
                break


            if self.process.poll() is not None:

                logger.error(
                    "Gateway stopped unexpectedly"
                )

                break



if __name__ == "__main__":

    win32serviceutil.HandleCommandLine(
        BBJSenseGatewayService
    )