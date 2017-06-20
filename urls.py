from django.conf.urls import patterns, url
import views
from . import APP_NAME

urlpatterns = patterns('',
   url(r'^$', views.import_layer, name='%s.home' % APP_NAME),
   url(r'^import/$', views.import_layer, name='%s.import_layer' % APP_NAME),
   url(r'^import/status/$', views.import_layer_status, name='%s.import_layer_status' % APP_NAME),
)
