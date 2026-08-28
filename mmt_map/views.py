import json

# Django core
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.db import connection
from django.views.decorators.cache import cache_page
from django.utils import translation
from django.core.cache import cache

# Other Python modules
from psycopg2 import sql
import requests

# Third Party Django apps
from constance import config

# Memory Map Toolkit
from .models import Theme, TagList, MapLayer
from mmt_motm.models import Event
from .vector_tile_helpers import tileIsValid, tileToEnvelope


def index(request):
	"""Base map"""

	themes = Theme.objects.all()
	tag_lists = TagList.objects.filter(published=True).order_by('order')

	bounds = None
	
	if (config.BOUNDS_SW_LONGITUDE != 0.0) and (config.BOUNDS_SW_LATITUDE != 0.0) and (config.BOUNDS_NE_LATITUDE != 0.0) and (config.BOUNDS_NE_LONGITUDE != 0.0):

		bounds = [[config.BOUNDS_SW_LONGITUDE,config.BOUNDS_SW_LATITUDE],[config.BOUNDS_NE_LONGITUDE,config.BOUNDS_NE_LATITUDE]]

	# Year range for event time slider
	from django.db.models import Min, Max
	from mmt_motm.models import Timespan
	yr = Timespan.objects.aggregate(
		min_yr=Min('start__year'), max_yr=Max('end__year'))
	year_min = yr['min_yr'] or 1900
	year_max = yr['max_yr'] or 2000

	# JSON-encode numeric values to prevent locale-specific decimal separator issues
	context = {
		'themes': themes, 
		'bounds': json.dumps(bounds) if bounds else None,
		'tag_lists': tag_lists,
		'year_min': year_min, 
		'year_max': year_max,
		# JSON-encode all numeric config values
		'map_center': json.dumps([float(config.MAP_CENTER_LONGITUDE), float(config.MAP_CENTER_LATITUDE)]),
		'zoom': json.dumps(float(config.ZOOM)),
		'max_zoom': json.dumps(float(config.MAX_ZOOM)),
		'min_zoom': json.dumps(float(config.MIN_ZOOM)),
		'pitch': json.dumps(float(config.PITCH)),
		'bearing': json.dumps(float(config.BEARING)),
	}
	
	return render(request, 'mmt_map/index.html', context)


def text_only_feature_list(request):
	"""A text only overview page listing all available sections of the site."""
	from mmt_motm.models import Person, LocationPoint, Event, Interview, Extraction, Concept
	counts = {
		'persons': Person.objects.count(),
		'locations': LocationPoint.objects.count(),
		'events': Event.objects.count(),
		'interviews': Interview.objects.count(),
		'extractions': Extraction.objects.count(),
		'concepts': Concept.objects.count(),
	}
	return render(request, 'mmt_motm/text_only.html', counts)


# Vector tiles are optionally cached to stop the database being spammed too heavily.
def vector_tile(request, z, x, y, tile_format):
	"""
	Returns a vector tile. Uses raw SQL because GeoDjango can't return vector tiles (though to my mind it should). Tiles are optionally cached so as to make large maps more performant, at the expense of updates not being visible immediately. Adapted from https://github.com/pramsey/minimal-mvt, though refactored so the query is built without using string.format()!
	"""
	
	tile = {
		'zoom': int(z),
		'x': int(x),
		'y': int(y),
		'format': tile_format
	}

	if not tileIsValid(tile):
		return HttpResponse('<p>Tile request not valid</p>', status=400)

	# Get the current language code for translation
	# Try to get from request, or use default
	lang_code = translation.get_language() or request.LANGUAGE_CODE or 'en'
	
	# Create a cache key that includes the language
	cache_key = f"vector_tile_{lang_code}_{z}_{x}_{y}_{tile_format}"
	cached_response = cache.get(cache_key)
	
	if cached_response:
		response = HttpResponse(cached_response)
		response['Access-Control-Allow-Origin'] = '*'
		response['Content-type'] = 'application/vnd.mapbox-vector-tile'
		response['X-From-Cache'] = 'true'
		return response

	env = tileToEnvelope(tile)

	DENSIFY_FACTOR = 4
	env['segSize'] = (env['xmax'] - env['xmin'])/DENSIFY_FACTOR

	# The query has to be built manually to return the geometries as vector tiles. Must be changed if you update the models
	# Note: {table_translation} will be replaced with the translation table name (e.g., mmt_map_point_translation)

	sql_tmpl = """
		WITH 
		"bounds" AS (
			SELECT ST_Segmentize(ST_MakeEnvelope(%(xmin)s, %(ymin)s, %(xmax)s, %(ymax)s, 3857),%(segSize)s) AS "geom", 
				   ST_Segmentize(ST_MakeEnvelope(%(xmin)s, %(ymin)s, %(xmax)s, %(ymax)s, 3857),%(segSize)s)::box2d AS "b2d"
		),
		"mvtgeom" AS (
			SELECT ST_AsMVTGeom(ST_Transform("t"."geom", 3857), "bounds"."b2d") AS "geom", 
				   "t"."id", COALESCE("tr"."name", "t"."id"::text) AS "name", "t"."weight", "t"."theme_id", "t"."tag_str", "t"."thumbnail_url", "t"."uuid",
				   "mmt_map_document"."slug", "t"."attachments"
			FROM  {table} "t" 
				LEFT JOIN {table_translation} "tr"
					ON "tr"."master_id" = "t"."id" AND "tr"."language_code" = %(lang_code)s
				LEFT JOIN mmt_map_document
					ON mmt_map_document.point_id = "t".id,
			"bounds"
			WHERE ST_Intersects("t"."geom", ST_Transform("bounds"."geom", 4326)) AND "t"."published" = TRUE
		) 
		SELECT ST_AsMVT("mvtgeom".*, {layerName}) FROM "mvtgeom"
	"""

	# Map the geometry types to PostGIS database tables and layer names for consumption by MapboxGL

	layers = {
		'points': {
			'table': 'mmt_map_point',
			'table_translation': 'mmt_map_point_translation',
			'layerName': "points"
		},
		'polygons': {
			'table': 'mmt_map_polygon',
			'table_translation': 'mmt_map_polygon_translation',
			'layerName': "polygons"
		},
		'lines': {
			'table': 'mmt_map_line',
			'table_translation': 'mmt_map_line_translation',
			'layerName': "lines"
		},
		'mulipoints': {
			'table': 'mmt_map_multipoint',
			'table_translation': 'mmt_map_multipoint_translation',
			'layerName': "multipoints"
		}
	}

	# Build the HttpResponse

	response = HttpResponse()
	response['Access-Control-Allow-Origin'] = '*'
	response['Content-type'] = 'application/vnd.mapbox-vector-tile'

	# Loop over the layers and concatenate them into the response

	for layer, attrs in layers.items():

		query = sql.SQL(sql_tmpl).format(
			table=sql.Identifier(attrs['table']), 
			table_translation=sql.Identifier(attrs['table_translation']),
			layerName=sql.Literal(attrs['layerName'])
		)

		params = {
			'xmin': env['xmin'], 
			'ymin': env['ymin'], 
			'xmax': env['xmax'], 
			'ymax': env['ymax'], 
			'segSize': env['segSize'],
			'lang_code': lang_code
		}

		with connection.cursor() as cursor:
			cursor.execute(query, params)
			pbf = cursor.fetchone()[0]
	
		response.write(pbf.tobytes())

	# Add MOTM layers (LocationPoints, Event lines)
	_append_motm_layers(response, env, lang_code)

	# Cache the response content (not the HttpResponse object)
	response_content = response.content
	cache.set(cache_key, response_content, 60 * config.CACHE_TIMEOUT)

	# Return the tile

	return response


def _append_motm_layers(response, env, lang_code):
	
	params = {
		'xmin': env['xmin'], 'ymin': env['ymin'],
		'xmax': env['xmax'], 'ymax': env['ymax'],
		'segSize': env['segSize'],
		'lang_code': lang_code,
	}

	# LocationPoints with dominant lifecycle icon from events
	_lc_case = Event.lifecycle_sql_case()
	loc_sql = f"""
		WITH
		"bounds" AS (
			SELECT ST_Segmentize(ST_MakeEnvelope(%(xmin)s, %(ymin)s, %(xmax)s, %(ymax)s, 3857),%(segSize)s) AS "geom",
				   ST_Segmentize(ST_MakeEnvelope(%(xmin)s, %(ymin)s, %(xmax)s, %(ymax)s, 3857),%(segSize)s)::box2d AS "b2d"
		),
		"mvtgeom" AS (
			SELECT ST_AsMVTGeom(ST_Transform("t"."location", 3857), "bounds"."b2d") AS "geom",
				   "t"."id", "t"."current_name" AS "name",
				   (
			       SELECT {_lc_case}
				       FROM "mmt_motm_event" "e"
				       WHERE ("e"."start_location_id" = "t"."id"
				              OR "e"."end_location_id" = "t"."id")
				       GROUP BY "e"."lifecycle"
				       ORDER BY COUNT(*) DESC
				       LIMIT 1
				   ) AS "icon"
			FROM "mmt_motm_locationpoint" "t",
			"bounds"
			WHERE "t"."location" IS NOT NULL
			  AND ST_Intersects("t"."location", ST_Transform("bounds"."geom", 4326))
		)
		SELECT ST_AsMVT("mvtgeom".*, 'locations') FROM "mvtgeom"
	"""
	with connection.cursor() as cursor:
		cursor.execute(loc_sql, params)
		pbf = cursor.fetchone()[0]
	response.write(pbf.tobytes())

	# Event lines (start_location → end_location) with lifecycle icon
	evt_sql = f"""
		WITH
		"bounds" AS (
			SELECT ST_Segmentize(ST_MakeEnvelope(%(xmin)s, %(ymin)s, %(xmax)s, %(ymax)s, 3857),%(segSize)s) AS "geom",
				   ST_Segmentize(ST_MakeEnvelope(%(xmin)s, %(ymin)s, %(xmax)s, %(ymax)s, 3857),%(segSize)s)::box2d AS "b2d"
		),
		"mvtgeom" AS (
			SELECT ST_AsMVTGeom(
				ST_Transform(ST_MakeLine("sl"."location", "el"."location"), 3857),
				"bounds"."b2d"
			) AS "geom",
			"e"."id",
			COALESCE("et"."description", "e"."id"::text) AS "name",
			COALESCE(EXTRACT(YEAR FROM "ts"."start"), EXTRACT(YEAR FROM "ts"."end"))::int AS "year",
			{_lc_case} AS "icon"
			FROM "mmt_motm_event" "e"
			LEFT JOIN "mmt_motm_event_translation" "et"
				ON "et"."master_id" = "e"."id" AND "et"."language_code" = %(lang_code)s
			JOIN "mmt_motm_locationpoint" "sl" ON "e"."start_location_id" = "sl"."id"
			JOIN "mmt_motm_locationpoint" "el" ON "e"."end_location_id" = "el"."id"
			LEFT JOIN "mmt_motm_timespan" "ts" ON "e"."timespan_id" = "ts"."id",
			"bounds"
			WHERE "sl"."location" IS NOT NULL
			  AND "el"."location" IS NOT NULL
			  AND "e"."start_location_id" != "e"."end_location_id"
			  AND ST_Intersects(ST_MakeLine("sl"."location", "el"."location"), ST_Transform("bounds"."geom", 4326))
		)
		SELECT ST_AsMVT("mvtgeom".*, 'event_lines') FROM "mvtgeom"
	"""
	with connection.cursor() as cursor:
		cursor.execute(evt_sql, params)
		pbf = cursor.fetchone()[0]
	response.write(pbf.tobytes())

	return response


def tile_json(request):
	"""Returns a tileJSON object describing the vector tiles hosted in the Memory Map toolkit database."""

	if request.is_secure():
		scheme = 'https'
	else:
		scheme = request.scheme

	host = request.get_host()

	json = {
		'tileJSON': '2.2.0',
		'name': 'Memory Map Toolkit Interactive Features',
		'tiles': [
			scheme + '://' + host + '/tiles/{z}/{x}/{y}.pbf'
		],
	}

	return JsonResponse(json)

def style_json(request):
	"""Returns the base map style for the main map for use in the admin site"""

	# This works by getting the base map style, then appending the raster layers to the returned
	# styleJSON object

	maptiler_key = config.MAPTILER_KEY
	style_url = config.MAPTILER_STYLE

	params = {'key': maptiler_key}

	r = requests.get(style_url, params=params)

	if r.status_code == requests.codes.ok:
		style = r.json()

		for layer in MapLayer.objects.all().order_by('order'):
			style['sources'][layer.slug] = {
				'type': 'raster',
				'url': layer.tilejson_url,
				'tileSize': 256
			}
			
			layer_def = {
				'id': layer.slug,
				'type': 'raster',
				'source': layer.slug,
				'visibility': 'visible'
			}

			style['layers'].append(layer_def)
		
		return JsonResponse(style)
	
	else:
		return JsonResponse({'ok': False})

	


