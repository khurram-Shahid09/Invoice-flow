from django.urls import path

from . import views

urlpatterns = [
    path("documents", views.UploadView.as_view(), name="document-upload"),
    path("invoices", views.InvoiceListView.as_view(), name="invoice-list"),
    path("invoices/<str:invoice_id>", views.InvoiceDetailView.as_view(), name="invoice-detail"),
    path(
        "invoices/<str:invoice_id>/pages/<int:number>",
        views.PageImageView.as_view(),
        name="invoice-page",
    ),
    path(
        "invoices/<str:invoice_id>/fields", views.InvoiceFieldsView.as_view(), name="invoice-fields"
    ),
    path(
        "invoices/<str:invoice_id>/decision",
        views.InvoiceDecisionView.as_view(),
        name="invoice-decision",
    ),
    path("invoices/<str:invoice_id>/retry", views.InvoiceRetryView.as_view(), name="invoice-retry"),
]
