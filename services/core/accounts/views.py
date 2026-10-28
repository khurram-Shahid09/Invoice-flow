import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, cast

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenBackendError, TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.state import token_backend
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from audit.service import record
from common.exceptions import ApiError

from .models import ApiToken, Membership, Organization, Role, User
from .serializers import (
    ApiTokenCreatedSerializer,
    ApiTokenSerializer,
    AuthResponseSerializer,
    LoginSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    MeSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .throttles import LoginEmailThrottle, LoginIpThrottle, RegisterThrottle
from .views_base import OrgScopedViewMixin

# --- Session tokens: short-lived access JWT in the body, rotating refresh JWT in an httpOnly cookie ---


@dataclass(frozen=True)
class _RefreshCookie:
    key: str
    path: str
    httponly: bool
    secure: bool
    samesite: Literal["Lax", "Strict", "None"]


def _cookie() -> _RefreshCookie:
    return _RefreshCookie(**cast(dict[str, Any], settings.REFRESH_COOKIE))


def _lifetime(name: str) -> int:
    return int(cast(timedelta, getattr(jwt_settings, name)).total_seconds())


def _session_response(
    user: User, refresh: RefreshToken, status_code: int = status.HTTP_200_OK
) -> Response:
    access = refresh.access_token
    response = Response(
        {
            "access": str(access),
            "access_expires_in": _lifetime("ACCESS_TOKEN_LIFETIME"),
            "user": UserSerializer(user).data,
        },
        status=status_code,
    )
    cookie = _cookie()
    response.set_cookie(
        cookie.key,
        str(refresh),
        max_age=_lifetime("REFRESH_TOKEN_LIFETIME"),
        path=cookie.path,
        httponly=cookie.httponly,
        secure=cookie.secure,
        samesite=cookie.samesite,
    )
    return response


def _clear_refresh_cookie(response: Response) -> Response:
    cookie = _cookie()
    response.delete_cookie(cookie.key, path=cookie.path, samesite=cookie.samesite)
    return response


def _revoke_all_refresh_tokens(user_id: str) -> int:
    outstanding = OutstandingToken.objects.filter(user_id=user_id, blacklistedtoken__isnull=True)
    BlacklistedToken.objects.bulk_create([BlacklistedToken(token=t) for t in outstanding])
    return len(outstanding)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [RegisterThrottle]

    @extend_schema(request=RegisterSerializer, responses={201: AuthResponseSerializer})
    def post(self, request: Request) -> Response:
        data = RegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        with transaction.atomic():
            user = User.objects.create_user(v["email"], v["password"], name=v.get("name", ""))
            org = Organization.objects.create(name=v["org_name"])
            # Whoever creates the workspace can do everything until they invite a team.
            Membership.objects.create(org=org, user=user, roles=sorted(Role.values))
            actor = f"user:{user.pk}"
            record("org.created", org=org, request=request, entity=org, actor=actor)
            record("user.registered", org=org, request=request, entity=user, actor=actor)
        return _session_response(user, RefreshToken.for_user(user), status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [LoginIpThrottle, LoginEmailThrottle]

    @extend_schema(request=LoginSerializer, responses={200: AuthResponseSerializer})
    def post(self, request: Request) -> Response:
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(
            request._request,
            email=data.validated_data["email"].strip().lower(),
            password=data.validated_data["password"],
        )
        if user is None:
            raise ApiError("invalid_credentials", "Invalid email or password.", status_code=401)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return _session_response(user, RefreshToken.for_user(user))


class RefreshView(APIView):
    """Rotates the refresh cookie. Presenting an already-rotated token is treated as theft:
    every refresh token of that user is revoked (refresh token reuse detection)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=None, responses={200: AuthResponseSerializer})
    def post(self, request: Request) -> Response:
        raw = request.COOKIES.get(_cookie().key)
        if not raw:
            raise ApiError("not_authenticated", "No session.", status_code=401)
        try:
            # Checks signature, expiry and blacklist. (Stub types the arg as Token; str is accepted.)
            old = RefreshToken(raw)  # type: ignore[arg-type]
        except TokenError:
            self._detect_reuse(raw)
            response = Response(
                {
                    "error": {
                        "code": "invalid_session",
                        "message": "Session expired. Sign in again.",
                        "details": {},
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return _clear_refresh_cookie(response)

        user = User.objects.filter(pk=old["sub"], is_active=True).first()
        if user is None:
            raise ApiError("invalid_session", "Session expired. Sign in again.", status_code=401)
        old.blacklist()
        return _session_response(user, RefreshToken.for_user(user))

    @staticmethod
    def _detect_reuse(raw: str) -> None:
        try:
            payload = token_backend.decode(raw, verify=True)  # type: ignore[arg-type]  # stub says Token  # genuine, unexpired, but rejected?
        except TokenBackendError:
            return
        if BlacklistedToken.objects.filter(token__jti=payload.get("jti")).exists():
            _revoke_all_refresh_tokens(payload["sub"])


class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        raw = request.COOKIES.get(_cookie().key)
        if raw:
            with contextlib.suppress(TokenError):
                RefreshToken(raw).blacklist()  # type: ignore[arg-type]  # accepts the encoded str
        return _clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MeSerializer})
    def get(self, request: Request) -> Response:
        user = User.objects.prefetch_related("memberships__org").get(pk=request.user.pk)
        token = request.auth if isinstance(request.auth, ApiToken) else None
        return Response(MeSerializer(user, context={"token": token}).data)


# --- Personal access tokens (scripts and integrations) ---


class TokenListView(OrgScopedViewMixin, generics.ListCreateAPIView):
    queryset = ApiToken.objects.all()
    serializer_class = ApiTokenSerializer

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)

    @extend_schema(responses={201: ApiTokenCreatedSerializer})
    def post(self, request: Request, *args, **kwargs) -> Response:
        if isinstance(request.auth, ApiToken):
            raise PermissionDenied(
                "Tokens can't create tokens. Sign in to the dashboard.", code="session_required"
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.save(org=self.org, user=request.user)
        record(
            "token.created",
            org=self.org,
            request=request,
            entity=token,
            metadata={"name": token.name},
        )
        return Response(ApiTokenCreatedSerializer(token).data, status=status.HTTP_201_CREATED)


class TokenDetailView(OrgScopedViewMixin, generics.DestroyAPIView):
    """DELETE revokes (keeps the row for the audit trail)."""

    queryset = ApiToken.objects.all()
    serializer_class = ApiTokenSerializer
    lookup_url_kwarg = "token_id"

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)

    def perform_destroy(self, instance: ApiToken) -> None:
        if instance.revoked_at is None:
            instance.revoked_at = timezone.now()
            instance.save(update_fields=["revoked_at", "updated_at"])
            record("token.revoked", org=self.org, request=self.request, entity=instance)


# --- Members ---

ADMIN_ONLY = frozenset({Role.ADMIN.value})


def _ensure_another_admin(membership: Membership) -> None:
    others = (
        Membership.objects.for_org(membership.org)
        .filter(roles__contains=[Role.ADMIN])
        .exclude(pk=membership.pk)
    )
    if membership.is_admin and not others.exists():
        raise ApiError("last_admin", "A workspace needs at least one admin.", status_code=409)


class MemberListView(OrgScopedViewMixin, generics.ListCreateAPIView):
    queryset = Membership.objects.select_related("user")
    serializer_class = MemberSerializer
    org_url_kwarg = "org_id"
    method_roles = {"POST": ADMIN_ONLY}

    def perform_create(self, serializer: BaseSerializer) -> None:
        email = serializer.validated_data.pop("email").strip().lower()
        user = User.objects.filter(email=email, is_active=True).first()
        if user is None:
            raise ApiError(
                "user_not_found",
                "No account with this email. Ask them to sign up first, then add them.",
                status_code=404,
            )
        if Membership.objects.for_org(self.org).filter(user=user).exists():
            raise ApiError("already_member", "This person is already a member.", status_code=409)
        membership = serializer.save(org=self.org, user=user)
        record(
            "member.added",
            org=self.org,
            request=self.request,
            entity=membership,
            metadata={"user_id": user.pk, "roles": membership.roles},
        )


class MemberDetailView(OrgScopedViewMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Membership.objects.select_related("user")
    org_url_kwarg = "org_id"
    lookup_url_kwarg = "member_id"
    method_roles = {"PATCH": ADMIN_ONLY, "DELETE": ADMIN_ONLY}
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        return MemberUpdateSerializer if self.request.method == "PATCH" else MemberSerializer

    def perform_update(self, serializer: BaseSerializer) -> None:
        membership = cast(Membership, serializer.instance)
        before = {"roles": membership.roles, "approval_limit": str(membership.approval_limit)}
        new_roles = serializer.validated_data.get("roles", membership.roles)
        if Role.ADMIN not in new_roles:
            _ensure_another_admin(membership)
        serializer.save()
        after = {"roles": membership.roles, "approval_limit": str(membership.approval_limit)}
        record(
            "member.updated",
            org=self.org,
            request=self.request,
            entity=membership,
            metadata={"user_id": membership.user_id, "from": before, "to": after},
        )

    def perform_destroy(self, instance: Membership) -> None:
        _ensure_another_admin(instance)
        record(
            "member.removed",
            org=self.org,
            request=self.request,
            entity=instance,
            metadata={"user_id": instance.user_id, "roles": instance.roles},
        )
        instance.delete()
