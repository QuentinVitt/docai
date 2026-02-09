class LLMError(Exception):
    """
    Base class for all LLM-related errors. 4xx and 5xx errors raise LLMClientError and LLMServerErrors.
    6xx errors are custom errors raised by the system.
    """

    # code 600: LLMClientNotFound - LLMClient is not a supported provider
    # code 601: Unexpected error
    # code 602: couldn't convert LLM content to provider content
    # code 603: faulty response from LLMCall received
    # code 604: faulty LLMExecutionPlan - No LLMTarget specified
    # code 605: Error for configuring the semaphore for concurrent requests
    # code 606: Tool not found
    # code 607: Failed to transform content to provider content

    def __init__(self, status_code: int, response: str = ""):
        self.status_code = status_code
        self.response = response
        super().__init__(f"code {self.status_code} -> {self.response}")


class LLMClientError(LLMError):
    """Raised when an error occurs while interacting with an LLMClient."""

    # code 400: Bad Request
    # code 401: Authentication Error
    # code 403: Permission Denied
    # code 404: Not Found Error
    # code 408: Request Timeout
    # code 409: Confflict Error
    # code 422: Unprocessable Entity
    # code 429: Rate Limit Exceeded


class LLMServerError(LLMError):
    """Raised when an error occurs on the server side while interacting with an LLMClient."""

    # code 500: Internal Server Error
    # code 501: Not Implemented
    # code 502: Bad Gateway
    # code 503: Service Unavailable
    # code 504: Gateway Timeout
    # code 505: HTTP Version Not Supported
    # code 506: Variant Also Negotiates
    # code 507: Insufficient Storage
    # code 508: Loop Detected
    # code 510: Not Extended
    # code 511: Network Authentication Required
    # code 512: Bandwidth Limit Exceeded
