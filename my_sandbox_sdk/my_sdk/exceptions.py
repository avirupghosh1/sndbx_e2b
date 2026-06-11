"""
Exception classes for My Sandbox SDK.
"""


class SandboxException(Exception):
    """Base exception for all SDK errors."""
    pass


class SandboxNotFoundException(SandboxException):
    """Raised when sandbox is not found or no longer running."""
    pass


class CommandException(SandboxException):
    """Raised when command execution fails."""
    pass


class FileNotFoundException(SandboxException):
    """Raised when file or directory is not found in sandbox."""
    pass


class AuthenticationException(SandboxException):
    """Raised when API authentication fails."""
    pass


class TimeoutException(SandboxException):
    """Raised when operation times out."""
    pass


class InvalidArgumentException(SandboxException):
    """Raised when invalid arguments are provided."""
    pass


class APIException(SandboxException):
    """Raised when API returns an error."""
    
    def __init__(self, status_code: int, message: str, response_body: str = ""):
        self.status_code = status_code
        self.message = message
        self.response_body = response_body
        super().__init__(f"API Error ({status_code}): {message}\n{response_body}")


class NotEnoughSpaceException(SandboxException):
    """Raised when there is not enough disk space."""
    pass


class OperationInProgressException(SandboxException):
    """Raised when trying to perform operation while another is in progress."""
    pass
