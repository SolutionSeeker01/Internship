import os
import logging
from logging.handlers import RotatingFileHandler

# Flag to track if logging has been configured to prevent duplicates on reloads
_logging_configured = False


def setup_logging() -> None:
    """
    Configures centralized logging for the entire application.
    
    Sets up a root logger that writes INFO logs to the console and DEBUG logs
    to a rotating log file in the Backend/logs/ directory. Prevents duplicate
    handlers from being added upon hot-reloads.
    """
    global _logging_configured
    if _logging_configured:
        return

    root_logger = logging.getLogger()
    
    # If handlers are already present, we skip initialization to avoid double logs during reload
    if root_logger.hasHandlers():
        _logging_configured = True
        return

    # Automatically create the logs directory inside the utils folder
    utils_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(utils_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(log_format)

    # 1. Console Handler - set to INFO level
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # 2. File Handler - set to DEBUG level for more details, rotates at 10MB
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=10 * 1024 * 1024, 
        backupCount=5, 
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # Configure root logger
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    _logging_configured = True
    root_logger.info("Centralized logging system configured successfully.")


def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance by name.
    
    Args:
        name (str): Typically __name__ of the module.
        
    Returns:
        logging.Logger: Configured logger instance.
    """
    return logging.getLogger(name)
