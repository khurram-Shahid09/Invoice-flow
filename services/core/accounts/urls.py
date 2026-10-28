from django.urls import path

from . import views

urlpatterns = [
    path("auth/register", views.RegisterView.as_view(), name="auth-register"),
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/refresh", views.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("me", views.MeView.as_view(), name="me"),
    path("tokens", views.TokenListView.as_view(), name="token-list"),
    path("tokens/<str:token_id>", views.TokenDetailView.as_view(), name="token-detail"),
    path("orgs/<str:org_id>/members", views.MemberListView.as_view(), name="member-list"),
    path(
        "orgs/<str:org_id>/members/<str:member_id>",
        views.MemberDetailView.as_view(),
        name="member-detail",
    ),
]
