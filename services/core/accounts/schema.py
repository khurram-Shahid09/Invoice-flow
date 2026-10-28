"""OpenAPI (drf-spectacular) description of the personal access token scheme."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class PersonalAccessTokenScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.authentication.PersonalAccessTokenAuthentication"
    name = "personalAccessToken"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": "Personal access token (`pat_...`) from Settings → Tokens. For scripts and integrations (n8n, scanners).",
        }
