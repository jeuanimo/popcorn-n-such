from . import base as base_settings

for setting_name in dir(base_settings):
	if setting_name.isupper():
		globals()[setting_name] = getattr(base_settings, setting_name)

DEBUG = True

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
X_FRAME_OPTIONS = "SAMEORIGIN"

# Shipping defaults — overridden by Operational Settings GUI or env vars
SHIPPING_PROVIDER = "pitney_bowes"
SHIPPING_FROM_NAME = "Popcorn N Such"
SHIPPING_FROM_ADDRESS_LINE_1 = "123 Popcorn Way"
SHIPPING_FROM_ADDRESS_LINE_2 = ""
SHIPPING_FROM_CITY = "Belleville"
SHIPPING_FROM_STATE = "IL"
SHIPPING_FROM_POSTAL_CODE = "62208"
SHIPPING_FROM_COUNTRY = "US"
SHIPPING_DEFAULT_WEIGHT_OZ = 16
ESTIMATED_SHIPPING_CENTS = 899
FREE_SHIPPING_THRESHOLD_CENTS = 7500
