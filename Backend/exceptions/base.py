class PlatformException(Exception):
    """
    Root exception for all custom exceptions raised within the trading platform.
    
    All platform-specific domain, validation, database, and broker errors
    must inherit from this base class.
    """
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception


class BrokerAdapterException(PlatformException):
    """
    Exception raised when an integration with an external broker fails.
    
    This includes communication failures, API access issues, or errors returned
    by broker SDKs/endpoints.
    """
    pass


class DatabaseException(PlatformException):
    """
    Exception raised when a database operation fails.
    
    This abstracts low-level SQLAlchemy, PostgreSQL, or connection errors.
    """
    pass


class ResourceNotFoundException(PlatformException):
    """
    Exception raised when a requested resource (user, instrument, watchlist, etc.)
    cannot be found in the system.
    """
    pass


class ValidationException(PlatformException):
    """
    Exception raised when request parameters, credentials, configurations, 
    or internal domain models fail semantic validation.
    """
    pass
