from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "common"

    def ready(self) -> None:
        from django.conf import settings

        from config.sentry import init_sentry

        # API, workers and commands all load this app: one place to start error reporting.
        init_sentry(settings.SENTRY_DSN_API, settings.SENTRY_ENVIRONMENT)
