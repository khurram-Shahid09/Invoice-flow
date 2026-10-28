from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions
from rest_framework.request import Request

from .models import ApiToken, Membership, User

LAST_USED_RESOLUTION = timedelta(minutes=1)  # avoid a DB write on every request


class PersonalAccessTokenAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer pat_...``. Anything else is left to the next authenticator (JWT).

    A token is bound to one org; it stops working when revoked, expired, or when its user
    is deactivated or no longer a member of that org.
    """

    keyword = "Bearer"

    def authenticate(self, request: Request) -> tuple[User, ApiToken] | None:
        header = authentication.get_authorization_header(request).decode("latin-1").split()
        if (
            len(header) != 2
            or header[0] != self.keyword
            or not header[1].startswith(ApiToken.PREFIX)
        ):
            return None

        token = (
            ApiToken.objects.select_related("user", "org")
            .filter(token_hash=ApiToken.hash(header[1]))
            .first()
        )
        now = timezone.now()
        if token is None or not token.is_usable(now) or not token.user.is_active:
            raise exceptions.AuthenticationFailed("Invalid or expired token.", code="invalid_token")
        if not Membership.objects.filter(org=token.org, user=token.user).exists():
            raise exceptions.AuthenticationFailed("Invalid or expired token.", code="invalid_token")

        if token.last_used_at is None or now - token.last_used_at > LAST_USED_RESOLUTION:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
        return token.user, token

    def authenticate_header(self, request: Request) -> str:
        return self.keyword
