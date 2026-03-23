"""Classify navigation results as allowed/blocked/warning/etc."""
from __future__ import annotations

from app.models.models import ResultType

# Known Zscaler block-page indicators
_BLOCK_STRINGS = [
    "access denied",
    "this site is blocked",
    "zscaler",
    "security policy",
    "web policy violation",
    "your organization's policy",
    "the url you requested has been blocked",
    "internet security by zscaler",
    "blocked by your organization",
    "url filtering rule",
    "firewall rule",
]

_WARNING_STRINGS = [
    "caution",
    "warning",
    "proceed with caution",
    "this connection is not private",
    "your connection is not private",
    "net::err_cert",
    "ssl_error",
    "security warning",
]


def classify_result(
    nav: dict,
    page_text: str = "",
) -> ResultType:
    """Classify a navigation result dict from BrowserManager.goto().

    nav keys: url, title, status, error, latency_ms
    """
    error = (nav.get("error") or "").lower()
    title = (nav.get("title") or "").lower()
    status = nav.get("status", 0)
    text_lower = page_text.lower()

    # Hard errors
    if "timeout" in error or "navigation timeout" in error:
        return ResultType.TIMEOUT
    if "net::err_name_not_resolved" in error:
        return ResultType.DNS_FAILURE
    if error and ("net::err" in error or "failed" in error):
        return ResultType.LOAD_FAILURE

    # Block page detection
    combined = title + " " + text_lower
    for sig in _BLOCK_STRINGS:
        if sig in combined:
            return ResultType.BLOCKED

    # Warning detection
    for sig in _WARNING_STRINGS:
        if sig in combined:
            return ResultType.WARNING

    # HTTP error codes
    if status >= 400:
        return ResultType.FAILED

    # Redirect detection (significant domain change)
    if status in (301, 302, 303, 307, 308):
        return ResultType.REDIRECTED

    return ResultType.ALLOWED


def classify_private_app(
    nav: dict,
    page_text: str,
    expected_title: str = "",
    expected_selector_present: bool = True,
) -> ResultType:
    """Classify a private app navigation result."""
    base = classify_result(nav, page_text)
    if base in (ResultType.BLOCKED, ResultType.TIMEOUT, ResultType.DNS_FAILURE,
                ResultType.LOAD_FAILURE, ResultType.FAILED):
        return base

    # Check title expectation
    title = (nav.get("title") or "").lower()
    if expected_title and expected_title.lower() not in title:
        return ResultType.WARNING

    return base


def should_screenshot(result_type: ResultType) -> bool:
    return result_type in (
        ResultType.BLOCKED,
        ResultType.WARNING,
        ResultType.FAILED,
        ResultType.TIMEOUT,
        ResultType.DNS_FAILURE,
        ResultType.LOAD_FAILURE,
        ResultType.DOWNLOAD_BLOCKED,
    )
