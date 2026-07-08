class PlatformException(Exception):
    """
    Root exception for all custom exceptions raised within the trading platform.
    
    All platform-specific domain, validation, database, and broker errors
    must inherit from this base class.
    """
    status_code: int = 500
    error_code: str = "INTERNAL_PLATFORM_ERROR"
    default_message: str = "An unexpected internal error occurred."

    def __init__(self, diagnostic_message: str = None, client_message: str = None, original_exception: Exception = None):
        # 'diagnostic_message' acts as the internal detailed description (for logs and debug stack traces)
        diag_msg = diagnostic_message or self.default_message
        super().__init__(diag_msg)
        self.diagnostic_message = diag_msg
        
        # 'client_message' is safe to return to the public API client
        self.client_message = client_message or self.default_message
        self.original_exception = original_exception


class BrokerAdapterException(PlatformException):
    """
    Exception raised when an integration with an external broker fails.
    
    This includes communication failures, API access issues, or errors returned
    by broker SDKs/endpoints.
    """
    status_code: int = 502
    error_code: str = "BROKER_ERROR"
    default_message: str = "Failed to communicate with the external broker."


class DatabaseException(PlatformException):
    """
    Exception raised when a database operation fails.
    
    This abstracts low-level SQLAlchemy, PostgreSQL, or connection errors.
    """
    status_code: int = 500
    error_code: str = "DATABASE_ERROR"
    default_message: str = "A database persistence error occurred."


class ResourceNotFoundException(PlatformException):
    """
    Exception raised when a requested resource (user, instrument, watchlist, etc.)
    cannot be found in the system.
    """
    status_code: int = 404
    error_code: str = "RESOURCE_NOT_FOUND"
    default_message: str = "The requested resource could not be found."


class ValidationException(PlatformException):
    """
    Exception raised when request parameters, credentials, configurations, 
    or internal domain models fail semantic validation.
    """
    status_code: int = 400
    error_code: str = "VALIDATION_ERROR"
    default_message: str = "Invalid input, configuration, or parameters."
