# Django core
from django.urls import path, re_path

# 3rd Party Modules

# Memory Map Toolkit
from . import views

# Routes wrapped in i18n_patterns (language-prefixed, template-rendered)
urlpatterns = [
	path('', views.index, name='index'),
	path('text-only/', views.text_only_feature_list, name='text_only'),
]

# API routes NOT wrapped in i18n_patterns (shared across all languages)
api_urlpatterns = [
	re_path(r'tiles/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\.(?P<tile_format>\w+)$', views.vector_tile, name='vector_tile'),
    re_path(r'tiles/interactive\.json', views.tile_json, name='tile_json'),
    re_path(r'tiles/style\.json', views.style_json, name='style_json') # The base map style - for use in the admin
]