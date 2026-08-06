import sys
import win32service
import win32serviceutil
import win32event

import subprocess
import os
import time
from pathlib import Path

from logging_config import setup_logger

if len(sys.argv) > 1 and sys.argv[1] == "install":
    sys.argv[0] = "bbj_gateway_service.py"

BASE_DIR = Path(__file__).resolve().parent

PYTHON = BASE_DIR / "venv" / "Scripts" / "python.exe"

START = BASE_DIR / "gateway_launcher.py"

DEBUG_FILE = BASE_DIR / "service_debug.txt"

STDOUT_FILE = BASE_DIR / "service_stdout.log"

STDERR_FILE = BASE_DIR / "service_stderr.log"


logger = setup_logger(
    logger_name="windows-service",
    log_filename="windows_service.log"
)


class BBJSenseGatewayService(
    win32serviceutil.ServiceFramework
):

    _svc_name_ = "BBJSenseGateway"

    _svc_display_name_ = "BBJ Sense Gateway"

    _svc_description_ = (
        "BBJ Sense Industrial Gateway Service"
    )


    def __init__(self, args):

        win32serviceutil.ServiceFramework.__init__(
            self,
            args
        )

        self.stop_event = win32event.CreateEvent(
            None,
            0,
            0,
            None
        )

        self.gateway_process = None



    def SvcStop(self):

        logger.info(
            "Service stop requested"
        )


        self.ReportServiceStatus(
            win32service.SERVICE_STOP_PENDING
        )


        try:

            if self.gateway_process:

                logger.info(
                    "Stopping gateway PID=%s",
                    self.gateway_process.pid
                )

                self.gateway_process.terminate()


        except Exception as e:

            logger.exception(
                "Error stopping gateway: %s",
                e
            )


        win32event.SetEvent(
            self.stop_event
        )


        logger.info(
            "Service stopped"
        )



    def SvcDoRun(self):

        try:

            with open(
                DEBUG_FILE,
                "a"
            ) as f:

                f.write(
                    "\nSvcDoRun reached\n"
                )


            logger.info(
                "BBJ Sense Gateway Service starting"
            )


            logger.info(
                "Python=%s",
                PYTHON
            )


            logger.info(
                "Start script=%s",
                START
            )


            if not PYTHON.exists():

                raise FileNotFoundError(
                    f"Python missing: {PYTHON}"
                )


            if not START.exists():

                raise FileNotFoundError(
                    f"Startup script missing: {START}"
                )


            os.chdir(
                BASE_DIR
            )


            stdout = open(
                STDOUT_FILE,
                "a",
                buffering=1
            )


            stderr = open(
                STDERR_FILE,
                "a",
                buffering=1
            )


            self.gateway_process = subprocess.Popen(
                [
                    str(PYTHON),
                    "-u",
                    str(START)
                ],
                cwd=str(BASE_DIR),
                stdout=stdout,
                stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW
            )


            logger.info(
                "Gateway started PID=%s",
                self.gateway_process.pid
            )


            with open(
                DEBUG_FILE,
                "a"
            ) as f:

                f.write(
                    f"Gateway PID={self.gateway_process.pid}\n"
                )


            #
            # Tell Windows service manager
            #
            self.ReportServiceStatus(
                win32service.SERVICE_RUNNING
            )


            while True:


                result = win32event.WaitForSingleObject(
                    self.stop_event,
                    5000
                )


                if result == win32event.WAIT_OBJECT_0:

                    break



                if self.gateway_process.poll() is not None:


                    logger.error(
                        "Gateway stopped unexpectedly"
                    )


                    with open(
                        DEBUG_FILE,
                        "a"
                    ) as f:

                        f.write(
                            "Gateway stopped unexpectedly\n"
                        )


                    break



        except Exception as e:


            logger.exception(
                "Service failed: %s",
                e
            )


            with open(
                DEBUG_FILE,
                "a"
            ) as f:

                f.write(
                    f"ERROR: {str(e)}\n"
                )


            raise


if __name__ == "__main__":

    win32serviceutil.HandleCommandLine(
        BBJSenseGatewayService
    )