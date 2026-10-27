from app.errors import AppError


class LLMError(AppError):
    status_code = 502
    code = "llm_error"


class LLMAuthError(LLMError):
    code = "llm_auth"


class LLMQuotaError(LLMError):
    status_code = 429
    code = "llm_quota"


class LLMTimeoutError(LLMError):
    status_code = 504
    code = "llm_timeout"


class LLMRejectedError(LLMError):
    code = "llm_rejected_input"


class LLMBadResponseError(LLMError):
    code = "llm_bad_response"


class SearchError(AppError):
    status_code = 502
    code = "search_failed"


class SearchAuthError(SearchError):
    code = "search_auth"


class SearchTemporaryError(SearchError):
    code = "search_temporary"
