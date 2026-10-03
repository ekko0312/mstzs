"""Safe, single-attempt JSON requests for the cloud account and study service."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class CloudServiceError(RuntimeError):
    """A message safe to display without exposing credentials or server bodies."""

    def __init__(self, message: str, *, kind: str = "service", status: int | None = None,
                 write_may_have_succeeded: bool = False):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.write_may_have_succeeded = write_may_have_succeeded


def _http_message(status: int, auth: bool) -> tuple[str, str]:
    if auth and status in (400, 401):
        return "登录失败，请检查邮箱、密码及邮箱验证状态后重试。", "authentication"
    if status == 401:
        return "登录状态已失效，请退出登录后重新登录。", "authentication"
    if status == 403:
        return "云端访问被拒绝，请重新登录；若持续失败，请联系管理员检查 Supabase 项目状态。", "permission"
    if status == 429:
        return "云端请求过于频繁，请稍等片刻后重试。", "rate_limit"
    if status >= 500:
        return "云端数据服务暂时不可用，请稍后重试；若持续失败，请联系管理员检查 Supabase 项目状态。", "unavailable"
    if status == 404:
        return "云端数据服务暂时不可用，请联系管理员检查 Supabase 项目状态。", "configuration"
    return "云端请求未完成，请刷新后重试；若持续失败，请联系管理员检查 Supabase 项目状态。", "service"


def request_json(request: urllib.request.Request, *, timeout: int = 20,
                 auth: bool = False):
    """Return JSON, translating transport failures into safe actionable messages.

    A failed write is deliberately not retried: the server may have accepted it
    before the connection was interrupted.
    """
    is_write = not auth and request.get_method() not in ("GET", "HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        message, kind = _http_message(status, auth)
        uncertain = is_write and status >= 500
        if uncertain:
            message += " 本次保存状态尚未确认，请先查看最近作答记录，避免重复提交。"
        raise CloudServiceError(message, kind=kind, status=status,
                                write_may_have_succeeded=uncertain) from None
    except (urllib.error.URLError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        timed_out = isinstance(reason, TimeoutError)
        message = (
            "连接云端数据服务超时，请稍后重试；若持续失败，请联系管理员检查 Supabase 项目状态。"
            if timed_out else
            "无法连接云端数据服务，请稍后重试；若持续失败，请联系管理员检查 Supabase 项目状态。"
        )
        if is_write:
            message += " 本次保存状态尚未确认，请先查看最近作答记录，避免重复提交。"
        raise CloudServiceError(message, kind="timeout" if timed_out else "connection",
                                write_may_have_succeeded=is_write) from None
    except ValueError:
        # Request/header validation errors may contain the URL or API key.
        raise CloudServiceError("云端连接异常，请联系管理员检查 Supabase 项目状态后重试。",
                                kind="configuration",
                                write_may_have_succeeded=is_write) from None

    if not raw:
        return []
    try:
        result = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        message = "云端返回了无法识别的数据，请稍后重试；若持续失败，请联系管理员检查 Supabase 项目状态。"
        if is_write:
            message += " 本次保存状态尚未确认，请先查看最近作答记录，避免重复提交。"
        raise CloudServiceError(message, kind="response",
                                write_may_have_succeeded=is_write) from None
    if not isinstance(result, (dict, list)):
        raise CloudServiceError("云端返回的数据格式异常，请稍后重试。", kind="response",
                                write_may_have_succeeded=is_write)
    return result


def auth_request(url: str, key: str, action: str, email: str, password: str) -> dict:
    """Submit a login or registration request without displaying server details."""
    data = json.dumps({"email": email, "password": password}).encode("utf-8")
    try:
        request = urllib.request.Request(
            f"{url.rstrip('/')}/auth/v1/{action}", data=data, method="POST",
            headers={"apikey": key, "Content-Type": "application/json"},
        )
    except ValueError:
        raise CloudServiceError("云端账号服务连接异常，请联系管理员检查 Supabase 项目状态。",
                                kind="configuration") from None
    try:
        result = request_json(request, timeout=20, auth=True)
    except CloudServiceError as exc:
        if action == "signup" and exc.status in (400, 401):
            raise CloudServiceError("注册失败，请检查邮箱和密码；若已注册，请直接登录。",
                                    kind="authentication", status=exc.status) from None
        raise
    if not isinstance(result, dict):
        raise CloudServiceError("云端账号服务返回异常，请稍后重新登录。", kind="response")
    return result
