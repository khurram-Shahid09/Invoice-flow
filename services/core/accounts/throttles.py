from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class LoginIpThrottle(AnonRateThrottle):
    scope = "login_ip"


class RegisterThrottle(AnonRateThrottle):
    scope = "register"


class LoginEmailThrottle(SimpleRateThrottle):
    """Per-account limit, whatever the source IP: stops password guessing against one user."""

    scope = "login_email"

    def get_cache_key(self, request, view):
        email = (
            str(request.data.get("email", "")).strip().lower() if hasattr(request, "data") else ""
        )
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": email}
