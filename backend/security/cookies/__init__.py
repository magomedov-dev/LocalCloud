from __future__ import annotations

from security.cookies.dto import AuthCookieNames, CookieOptions
from security.cookies.enums import AuthCookieName, CookieErrorCode, CookieSameSite
from security.cookies.exceptions import CookieError
from security.cookies.service import (
    build_cookie_expires,
    clear_access_token_cookie,
    clear_auth_cookies,
    clear_refresh_token_cookie,
    delete_auth_cookie,
    get_access_token_from_cookies,
    get_auth_cookie_names,
    get_cookie_options,
    get_cookie_value,
    get_refresh_token_from_cookies,
    require_access_token_from_cookies,
    require_refresh_token_from_cookies,
    set_access_token_cookie,
    set_auth_cookie,
    set_auth_cookies,
    set_refresh_token_cookie,
)
from security.cookies.validators import (
    normalize_cookie_domain,
    normalize_cookie_path,
    normalize_samesite,
    validate_cookie_name,
    validate_cookie_value,
    validate_max_age_seconds,
)

__all__ = [
    "CookieSameSite",
    "CookieErrorCode",
    "AuthCookieName",
    "CookieError",
    "CookieOptions",
    "AuthCookieNames",
    "get_auth_cookie_names",
    "get_cookie_options",
    "set_access_token_cookie",
    "set_refresh_token_cookie",
    "set_auth_cookies",
    "set_auth_cookie",
    "clear_access_token_cookie",
    "clear_refresh_token_cookie",
    "clear_auth_cookies",
    "delete_auth_cookie",
    "get_access_token_from_cookies",
    "get_refresh_token_from_cookies",
    "require_access_token_from_cookies",
    "require_refresh_token_from_cookies",
    "get_cookie_value",
    "build_cookie_expires",
    "validate_cookie_name",
    "validate_cookie_value",
    "validate_max_age_seconds",
    "normalize_samesite",
    "normalize_cookie_domain",
    "normalize_cookie_path",
]
