from django.urls import path

from . import views

app_name = "sharing"

urlpatterns = [
    path("s/<str:token>/", views.ShareLinkRedirectView.as_view(), name="share"),
    path("s/<str:token>/qr.png", views.ShareLinkQRCodeDownloadView.as_view(), name="share-qr"),
]

