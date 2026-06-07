from __future__ import annotations

from dataclasses import dataclass

from security.cookies.enums import CookieSameSite


@dataclass(frozen=True, slots=True)
class CookieOptions:
    """Параметры безопасности и области действия cookie.

    Хранит настройки, которые используются при установке и удалении
    authentication cookie.

    Attributes:
        secure: Передавать cookie только по HTTPS.
        httponly: Запретить доступ к cookie из JavaScript.
        samesite: Политика SameSite для защиты от CSRF.
        domain: Домен, для которого доступна cookie. Если ``None``, домен не
            передаётся явно.
        path: URL-путь, для которого доступна cookie.
    """

    secure: bool
    httponly: bool
    samesite: CookieSameSite
    domain: str | None
    path: str

    def to_set_cookie_kwargs(self) -> dict[str, object]:
        """Преобразует параметры в kwargs для установки cookie.

        Returns:
            Словарь аргументов, совместимый с методом установки cookie. Если
            ``domain`` не задан, он не включается в результат.
        """

        kwargs: dict[str, object] = {
            "secure": self.secure,
            "httponly": self.httponly,
            "samesite": self.samesite,
            "path": self.path,
        }

        if self.domain is not None:
            kwargs["domain"] = self.domain

        return kwargs

    def to_delete_cookie_kwargs(self) -> dict[str, object]:
        """Преобразует параметры в kwargs для удаления cookie.

        Returns:
            Словарь аргументов, совместимый с методом удаления cookie.
        """

        return self.to_set_cookie_kwargs()


@dataclass(frozen=True, slots=True)
class AuthCookieNames:
    """Имена authentication cookie.

    Attributes:
        access: Имя cookie для access token.
        refresh: Имя cookie для refresh token.
    """

    access: str
    refresh: str
