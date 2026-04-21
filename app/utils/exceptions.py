"""Custom exception classes for the Student Profile Agent."""


class StudentProfileBaseError(Exception):
    """Base exception for all Student Profile Agent errors."""

    def __init__(self, message: str = "An unexpected error occurred", status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class DatabaseError(StudentProfileBaseError):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(message=message, status_code=500)


class NotFoundError(StudentProfileBaseError):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str = "Resource"):
        super().__init__(message=f"{resource} not found", status_code=404)


class ValidationError(StudentProfileBaseError):
    """Raised when request validation fails beyond Pydantic checks."""

    def __init__(self, message: str = "Validation failed"):
        super().__init__(message=message, status_code=422)


class PromptInjectionError(StudentProfileBaseError):
    """Raised when potential prompt injection content is detected."""

    def __init__(self, message: str = "Potential prompt injection detected"):
        super().__init__(message=message, status_code=422)


class ServiceAuthError(StudentProfileBaseError):
    """Raised when inter-service authentication fails."""

    def __init__(self, message: str = "Service authentication failed"):
        super().__init__(message=message, status_code=401)


class DocumentParsingError(StudentProfileBaseError):
    """Raised when document parsing fails."""

    def __init__(self, message: str = "Document parsing failed"):
        super().__init__(message=message, status_code=422)


class LLMExtractionError(StudentProfileBaseError):
    """Raised when LLM extraction fails after retries."""

    def __init__(self, message: str = "LLM extraction failed"):
        super().__init__(message=message, status_code=502)
