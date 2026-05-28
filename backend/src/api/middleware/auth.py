"""A11 — 全局密码门禁中间件。

仅在 ``server.access_password`` 配置非空时生效。空字符串等于不开启门禁。

行为：
- ``/api/health`` 永远豁免（健康检查不能被门挡住，否则反代/容器健康探针会乱报警）
- ``/docs`` / ``/openapi.json`` / ``/redoc`` / ``/`` 等非 ``/api/`` 路径直通
- ``OPTIONS`` 预检请求直通（CORS 不带 Authorization header）
- 必须带 ``Authorization: Bearer <token>``，否则 401 ``auth_required``
- token 不匹配 → 401 ``auth_invalid``，并记录该 IP 失败时间戳
- 单 IP 在 ``failed_login_lockout_seconds`` 滑动窗口内累计 ≥ ``failed_login_max_attempts`` 次失败后，
  即使带正确 token 也直接 429 ``rate_limited``，直到失败时间戳过期

非线性时间窗：用 deque 存失败时间戳，每次访问时清掉过期项再判定计数。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import get_system_config

EXEMPT_PATHS = {
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """对所有 ``/api/*`` 请求执行 Bearer token 校验 + 单 IP 失败计数锁定。"""

    def __init__(self, app):  # noqa: D401 — Starlette signature
        super().__init__(app)
        # IP -> 失败时间戳队列；用 deque 截断窗口
        self._failures: Dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):  # noqa: D401
        cfg = get_system_config().server

        # 空 access_password = 不开启门禁
        if not cfg.access_password:
            return await call_next(request)

        path = request.url.path

        # OPTIONS 预检请求不带 Authorization header，必须放行让 CORS 中间件处理
        if request.method == "OPTIONS":
            return await call_next(request)

        # 健康检查 + 文档端点豁免；非 /api/* 直通（让前端静态资源走得过去）
        if path in EXEMPT_PATHS:
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        if self._is_locked(client_ip, cfg):
            return JSONResponse(
                {"status": "error", "error": "rate_limited", "message": "too many failed attempts; locked"},
                status_code=429,
            )

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"status": "error", "error": "auth_required", "message": "Authorization Bearer token is required"},
                status_code=401,
            )

        token = auth_header[len("Bearer "):].strip()
        if token != cfg.access_password:
            self._record_failure(client_ip, cfg)
            return JSONResponse(
                {"status": "error", "error": "auth_invalid", "message": "invalid token"},
                status_code=401,
            )

        # 成功认证后清空该 IP 的失败计数（避免长期陷入临界）
        self._failures.pop(client_ip, None)
        return await call_next(request)

    # ─── 失败计数 ──────────────────────────────────────

    def _is_locked(self, ip: str, cfg) -> bool:
        """判定 ip 是否在锁定状态。会顺手清掉过期失败时间戳。"""

        self._evict_expired(ip, cfg)
        return len(self._failures.get(ip, ())) >= int(cfg.failed_login_max_attempts)

    def _record_failure(self, ip: str, cfg) -> None:
        self._evict_expired(ip, cfg)
        self._failures[ip].append(time.time())

    def _evict_expired(self, ip: str, cfg) -> None:
        cutoff = time.time() - float(cfg.failed_login_lockout_seconds)
        bucket = self._failures.get(ip)
        if not bucket:
            return
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            self._failures.pop(ip, None)
