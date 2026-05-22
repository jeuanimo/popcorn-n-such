from django.urls import path

from .views import (
    AboutView,
    ContactView,
    CorporateGiftsView,
    FAQView,
    FundraisingLandingView,
    HomeView,
    SiteContentCreateView,
    SiteContentDeleteView,
    SiteContentListView,
    SiteContentUpdateView,
    StartFundraiserView,
    health_check,
)

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("", HomeView.as_view(), name="home"),
    path("fundraising/", FundraisingLandingView.as_view(), name="fundraising-landing"),
    path("fundraising/start/", StartFundraiserView.as_view(), name="start-fundraiser"),
    path("corporate-gifts/", CorporateGiftsView.as_view(), name="corporate-gifts"),
    path("about/", AboutView.as_view(), name="about"),
    path("contact/", ContactView.as_view(), name="contact"),
    path("faq/", FAQView.as_view(), name="faq"),
    path("site-config/", SiteContentListView.as_view(), name="site-config-list"),
    path("site-config/new/", SiteContentCreateView.as_view(), name="site-config-create"),
    path("site-config/<int:pk>/edit/", SiteContentUpdateView.as_view(), name="site-config-edit"),
    path("site-config/<int:pk>/delete/", SiteContentDeleteView.as_view(), name="site-config-delete"),
]
