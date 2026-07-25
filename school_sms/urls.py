"""
URL configuration for school_sms project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from .views import landing_page, admin_grand_dashboard, about_page
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

urlpatterns = [
    path('', landing_page, name='landing_page'),
    path('about/', about_page, name= 'about'),
    path("admin/mega-dashboard/", admin_grand_dashboard, name="admin_grand_dashboard"),
    path('dashboard/', include(('dashboards.urls', 'dashboards'), namespace='dashboards')),
    path('admin/', admin.site.urls),
    path('auth/', include(('accounts.urls', 'accounts'), namespace='accounts')), 
    path('mpay/', include(('mpay.urls', 'mpay'), namespace='mpay')),
    path('brillspay/', include(('mpay.urls', 'mpay'), namespace='brillspay')),
    path('pickup/', include(('pickup.urls', 'pickup'), namespace='pickup')),
    path('payroll/', include(('payroll.urls', 'payroll'), namespace='payroll')),
    path('loans/', include(('loans.urls', 'loans'), namespace='loans')),
    path('leaves/', include(('leaves.urls', 'leaves'), namespace='leaves')),
    # path('sms/', include('sms.urls')),
    # path('management/', include('management.urls')),
]

# Media file serving for both DEBUG=True and DEBUG=False
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

# Static file serving for DEBUG=True (WhiteNoise handles it when DEBUG=False)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom Error Handlers
handler404 = 'django.views.defaults.page_not_found'
handler500 = 'django.views.defaults.server_error'
handler403 = 'django.views.defaults.permission_denied'
handler400 = 'django.views.defaults.bad_request'


