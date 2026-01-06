from .base import *  # noqa

DEBUG = True
ALLOWED_HOSTS = ALLOWED_HOSTS or ["127.0.0.1", "localhost"]

# In local dev, keep security relaxed
CSRF_TRUSTED_ORIGINS = []
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
