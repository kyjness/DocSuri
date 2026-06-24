"""Retry predicate for Bedrock API calls.

Classifies errors into retryable (throttle, timeout, 5xx)
vs non-retryable (auth, validation).
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerError",
    "InternalServerException",
    "ModelTimeoutException",
    "TooManyRequestsException",
}

NON_RETRYABLE_ERROR_CODES = {
    "ValidationException",
    "AccessDeniedException",
    "ResourceNotFoundException",
    "ModelNotReadyException",
}


def is_retryable(exc: Exception) -> bool:
    """Determine if an exception is retryable for backoff giveup predicate.

    Returns True if the error should be retried, False to give up.
    """
    # botocore.exceptions.ClientError (import-free check)
    exc_type_name = type(exc).__name__
    if exc_type_name == "ClientError" and hasattr(exc, "response"):
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in NON_RETRYABLE_ERROR_CODES:
            return False
        if error_code in RETRYABLE_ERROR_CODES:
            return True
        return True

    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True

    if hasattr(exc, "__cause__") and exc.__cause__:
        return is_retryable(exc.__cause__)

    return False
