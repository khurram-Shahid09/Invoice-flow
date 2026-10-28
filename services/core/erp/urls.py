from django.urls import path

from . import views

urlpatterns = [
    path("erp/connection", views.ErpConnectionView.as_view(), name="erp-connection"),
    path("erp/connection/test", views.ErpConnectionTestView.as_view(), name="erp-connection-test"),
    path("erp/sync", views.ErpSyncView.as_view(), name="erp-sync"),
    path("erp/sync-runs", views.SyncRunListView.as_view(), name="erp-sync-runs"),
    path("vendors", views.VendorListView.as_view(), name="vendor-list"),
    path("vendors/<str:vendor_id>", views.VendorDetailView.as_view(), name="vendor-detail"),
]
