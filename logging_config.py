import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"

MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024
BACKUP_LOG_COUNT = 5

LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | "
    "%(name)s | %(message)s"
)


def setup_logger(
    logger_name: str,
    log_filename: str,
    level: int = logging.INFO,
) -> logging.Logger:
    """
    Create a logger that writes to both:

    1. Command Prompt console
    2. Rotating log file

    Each log file is limited to 5 MB.
    Five backup files are retained.
    """

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False

    # Prevent duplicate handlers if the logger is initialized again.
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    log_file_path = LOG_DIR / log_filename

    file_handler = RotatingFileHandler(
        filename=log_file_path,
        maxBytes=MAX_LOG_SIZE_BYTES,
        backupCount=BACKUP_LOG_COUNT,
        encoding="utf-8",
    )

    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger