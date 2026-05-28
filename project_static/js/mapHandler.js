// Add the themes to the menu bar

$('#themes').append('<a href="#" class="theme dropdown-item">All</a>');

for (let i=0; i < MmtMap.themes.length; i++) {
    let themes = MmtMap.themes;
    let theme = '<a href="#" class="theme dropdown-item ' + themes[i].name +  '" data-key="' + themes[i].id + '" data-color="' + themes[i].color +'" style="color: '+ themes[i].color +'">' + themes[i].name + '</a>';
    $('#themes').append(theme);
}

// Add the tags to the menu bar, in the correct tag lists

for (let i=0; i < MmtMap.tagLists.length; i++) {
    let tl = MmtMap.tagLists[i];
    $(tl.id).append('<a href="#" class="tag dropdown-item">All</a>');
    tl.tags.forEach((tag) => {
        $(tl.id).append('<a href="#" class="tag dropdown-item" ' +'data-tag="' + tag +'">' + tag + '</a>');
    });
}



// If there are switchable layers, add a #maps dropdown to the menu bar

if (MmtMap.switchableLayers[0] != "") {

    let mapLayerMenu = '<li class="nav-item dropdown" id="map_layers"><a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" role="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">Map Layers</a><div class="dropdown-menu" id="maps" aria-labelledby="navbarDropdown"></div></li>';

    $('.menu_links').append(mapLayerMenu);
}


// Instantiate the map using the settings from the MmtMap object

let map = new mapboxgl.Map({
    container: 'map',
    center: MmtMap.settings.mapCenter,
    zoom: MmtMap.settings.zoom,
    minZoom: MmtMap.settings.minZoom,
    maxZoom: MmtMap.settings.maxZoom,
    attributionControl: true,
    logoPosition: 'top-left',
    scrollZoom: true,
    dragPan: true,
    pitch: MmtMap.settings.pitch,
    bearing: MmtMap.settings.bearing,
    antialias: true
});

if (MmtMap.settings.maxBounds) {
    map.setMaxBounds(MmtMap.settings.maxBounds);
}


// Load the map style and add the switchable layers to the menu bar. These things are together as the style definition needs to be loaded in order to populate the switchable layers menu

MmtMap.addStyle();

$.get(MmtMap.style, function(data) {

    let style = data;

    // If the default map style is being used, add the key to the sources and glyphs urls
    if (MmtMap.style == '/static/js/default_map_style.json') {
        style.sources['Ordnance Survey Open Zoomstack'].url = style.sources['Ordnance Survey Open Zoomstack'].url + MmtMap.baseMapStyleKey;
        style.glyphs = style.glyphs + MmtMap.baseMapStyleKey;
    }

    map.setStyle(style);

    // Add links for the switchable layers

    for (let i=0; i < style.layers.length; i++) {
        if (MmtMap.switchableLayers.includes(style.layers[i].id)) {
            let linkText = style.layers[i].id.charAt(0).toUpperCase() + style.layers[i].id.slice(1);
            let link = '<a class="dropdown-item switchable_layer visible" data-layer_id="' + style.layers[i].id +'" href="#">' + linkText +'</a>'
            $('#maps').append(link);
        }
    }

    // Make the layers switchable

    $('.switchable_layer').click(function(e) {
        e.preventDefault();
        let layer_id = $(this).data('layer_id');
        if ($(this).hasClass('visible')) { 
            map.setLayoutProperty(layer_id, 'visibility', 'none');
            $(this).removeClass('visible')
        } else {
            map.setLayoutProperty(layer_id, 'visibility', 'visible');
            $(this).addClass('visible');
        }
    });

});

// Add geolocation control

map.addControl(new mapboxgl.GeolocateControl({
    positionOptions: {
        enableHighAccuracy: true
    },
    trackUserLocation: true
}));

// Add the navigation and scale controls

let nav = new mapboxgl.NavigationControl({
    visualizePitch: true
});


let scale = new mapboxgl.ScaleControl({
    maxWidth: 80,
    unit: MmtMap.settings.scale
});

map.addControl(scale, 'bottom-left');

map.addControl(nav, 'top-right');


// Add the Memorymapper logo control

class MemorymapperLogoControl {
    onAdd(map) {
        this._map = map;
        this._container = document.createElement('div');
        this._container.className = 'mapboxgl-ctrl';
        this._container.innerHTML = '<a href="https://memorymapper.github.io" target="_blank"><img src="/static/img/memorymapper-logo.png" alt="MemoryMapper Logo" style="height: 20px; width: auto;"></a>';
        return this._container;
    }
     
    onRemove() {
        this._container.parentNode.removeChild(this._container);
        this._map = undefined;
    }
}

let logoControl = new MemorymapperLogoControl();

map.addControl(logoControl, 'bottom-right');



// Then load the interactive features


map.on('load', function() { 

    map.addSource('interactive', {
        type: 'vector',
        url: '/tiles/interactive.json'
    });

    map.addLayer({
        'id': 'points',
        'source': 'interactive',
        'source-layer': 'points',
        'type': 'circle',
        'paint': {
            'circle-color': MmtMap.themeStyleExpressions,
            'circle-radius': ["interpolate", ["linear"], ["zoom"], 
                14, ['*', 6, ['get', 'weight']],
                19, ['*', 12, ['get', 'weight']]
            ],
            'circle-opacity': ["case", ["boolean", ["feature-state", "hover"], false], 0.9, ["boolean", ["feature-state", "active"], false], 0.95, 0.7],
            'circle-stroke-width': 2,
            'circle-pitch-alignment': 'map',
            'circle-stroke-color': ["case", ["boolean", ["feature-state", "hover"], false], '#595a6d', ["boolean", ["feature-state", "active"], false], '#595a6d', MmtMap.themeStyleExpressions]
        }
    });

    map.addLayer({
        'id': 'polygons',
        'source': 'interactive',
        'source-layer': 'polygons',
        'type': 'fill',
        'paint': {
            'fill-color': MmtMap.themeStyleExpressions,
            'fill-opacity': ["case", ["boolean", ["feature-state", "hover"], false], 0.95, ["boolean", ["feature-state", "active"], false], 0.95, 0.7],
        }
    });

    map.addLayer({
        'id': 'polygon_outlines',
        'source': 'interactive',
        'source-layer': 'polygons',
        'type': 'line',
        'paint': {
            'line-color': ["case", ["boolean", ["feature-state", "hover"], false], '#595a6d', ["boolean", ["feature-state", "active"], false], '#595a6d', MmtMap.themeStyleExpressions],
            'line-width': ["interpolate", ["linear"], ["zoom"], 
                14, 1, 
                19, 4
            ],
            'line-opacity': ["interpolate", ["linear"], ["zoom"], 
                14, 0.3, 
                19, 1
            ]
        }
    });

    map.addLayer({
        'id': 'lines',
        'source': 'interactive',
        'source-layer': 'lines',
        'type': 'line',
        'paint': {
            'line-color': ["case", ["boolean", ["feature-state", "hover"], false], '#595a6d', ["boolean", ["feature-state", "active"], false], '#595a6d', MmtMap.themeStyleExpressions],
            'line-width': ["interpolate", ["linear"], ["zoom"], 
                15.5, ['*', 5, ['get', 'weight']],
                16.5, ['*', 10, ['get', 'weight']],
                17.5, ['*', 20, ['get', 'weight']], 
                18.5, ['*', 40, ['get', 'weight']]
            ],
            'line-opacity': ["case", ["boolean", ["feature-state", "hover"], false], 0.95, ["boolean", ["feature-state", "active"], false], 0.95, 0.7],
        },
        'layout': {
            'line-cap': 'round'
        }
    });

    
    map.addLayer({
        'id': 'points_labels',
        'source': 'interactive',
        'source-layer': 'points',
        'type': 'symbol',
        'layout': {
            'symbol-placement': 'point',
            'text-field': ['get', 'name'],
            'text-font': [MmtMap.settings.font],
            'text-size': [
                'interpolate', ['linear'], ['zoom'],
                14, ['*', 8, ['get', 'weight']],
                18, ['*', 16, ['get', 'weight']]
            ],
            'text-anchor': 'left',
            'text-justify': 'left',
            'text-offset': [1,0],
        },
        'paint': {
            'text-halo-color': 'rgba(255,255,255,0.8)',
            'text-halo-width': ['*', 2, ['get', 'weight']],
            'text-opacity': ["interpolate", ["linear"], ["zoom"],
                9.5, 0.5,
                18.5, 1
            ]
        }
    });

    map.addLayer({
        'id': 'polygon_labels',
        'source': 'interactive',
        'source-layer': 'polygons',
        'type': 'symbol',
        'layout': {
            'symbol-placement': 'point',
            'text-field': ['get', 'name'],
            'text-font': [MmtMap.settings.font],
            'text-size': [
                'interpolate', ['linear'], ['zoom'],
                14, ['*', 8, ['get', 'weight']],
                18, ['*', 16, ['get', 'weight']]
            ],
            'text-anchor': 'center',
            'text-justify': 'auto',
            'symbol-sort-key': ['get', 'weight']
        },
        'paint': {
            'text-color': '#2c2c2c',
            'text-halo-color': 'rgba(255,255,255,0.8)',
            'text-halo-width': ['*', 2, ['get', 'weight']],
            'text-opacity': ["interpolate", ["linear"], ["zoom"],
                12.5, 0.5,
                18.5, 1
            ]
        }
    });


    map.addLayer({
        'id': 'line_labels',
        'source': 'interactive',
        'source-layer': 'lines',
        'type': 'symbol',
        'layout': {
            'symbol-placement': 'point',
            'text-field': ['get', 'name'],
            'text-font': [MmtMap.settings.font],
            'text-size': [
                'interpolate', ['linear'], ['zoom'],
                14, ['*', 8, ['get', 'weight']],
                18, ['*', 16, ['get', 'weight']]
            ],
            'text-anchor': 'center',
            'text-justify': 'auto',
            'symbol-sort-key': ['get', 'weight']
        },
        'paint': {
            'text-color': '#2c2c2c',
            'text-halo-color': 'rgba(255,255,255,0.8)',
            'text-halo-width': ['*', 2, ['get', 'weight']],
            'text-opacity': ["interpolate", ["linear"], ["zoom"],
                12.5, 0.5,
                18.5, 1
            ]
        }
    });

    // LocationPoints from mmt_motm
    map.addLayer({
        'id': 'locations',
        'source': 'interactive',
        'source-layer': 'locations',
        'type': 'circle',
        'paint': {
            'circle-color': [
                'match', ['get', 'icon'],
                'fa-map-marker-alt', '#27ae60',
                'fa-university', '#2980b9',
                'fa-route', '#e67e22',
                'fa-user', '#8e44ad',
                'fa-clock', '#7f8c8d',
                'fa-road', '#c0392b',
                'fa-language', '#16a085',
                'fa-palette', '#e84393',
                'fa-box-open', '#f39c12',
                'fa-sitemap', '#2c3e50',
                '#e74c3c'
            ],
            'circle-radius': ["interpolate", ["linear"], ["zoom"],
                6, 4,
                14, 8,
                19, 14
            ],
            'circle-opacity': 0.8,
            'circle-stroke-width': 2,
            'circle-stroke-color': '#ffffff',
            'circle-pitch-alignment': 'map'
        }
    });

    map.addLayer({
        'id': 'locations_labels',
        'source': 'interactive',
        'source-layer': 'locations',
        'type': 'symbol',
        'layout': {
            'symbol-placement': 'point',
            'text-field': ['get', 'name'],
            'text-font': [MmtMap.settings.font],
            'text-size': ["interpolate", ["linear"], ["zoom"],
                6, 10,
                14, 12,
                18, 16
            ],
            'text-anchor': 'left',
            'text-justify': 'left',
            'text-offset': [1, 0],
        },
        'paint': {
            'text-color': '#2c2c2c',
            'text-halo-color': 'rgba(255,255,255,0.8)',
            'text-halo-width': 2,
            'text-opacity': ["interpolate", ["linear"], ["zoom"],
                6, 0.5,
                18.5, 1
            ]
        }
    });

    // Event lines from mmt_motm (start_location → end_location)
    map.addLayer({
        'id': 'event_lines',
        'source': 'interactive',
        'source-layer': 'event_lines',
        'type': 'line',
        'paint': {
            'line-color': '#e74c3c',
            'line-width': ["interpolate", ["linear"], ["zoom"],
                6, 1.5,
                14, 3,
                19, 5
            ],
            'line-opacity': 0.6
        }
    });

});


// Enable interactions

// Polygons

map.on('mousemove', 'polygons', function(e) {
    if (MmtMap.hoverInteractions.touch == false) {
        MmtMap.hoverInteractions.togglePopup('polygons');
        feature = e.features[0];
        MmtMap.hoverInteractions.hoverFeatureId = e.features[0].properties.id;
        MmtMap.hoverInteractions.addHoverProps('interactive', 'polygons', feature, MmtMap.hoverInteractions.hoverFeatureId, e.lngLat);
    }
});

map.on('mouseleave', 'polygons', function() {
    if (MmtMap.hoverInteractions.hoverFeatureId) {
        map.setFeatureState({source: 'interactive', sourceLayer: 'polygons', id: MmtMap.hoverInteractions.hoverFeatureId}, {hover: false});
    }
    MmtMap.hoverInteractions.hoverFeatureId = null;
    map.getCanvas().style.cursor = '';
    MmtMap.hoverInteractions.smallPopup.remove();
});

// Points

map.on('mousemove', 'points', function(e) {
    if (MmtMap.hoverInteractions.touch == false) {
        MmtMap.hoverInteractions.togglePopup('points');
        feature = e.features[0];
        MmtMap.hoverInteractions.hoverFeatureId = e.features[0].properties.id;
        MmtMap.hoverInteractions.addHoverProps('interactive', 'points', feature, MmtMap.hoverInteractions.hoverFeatureId, e.lngLat);
    }
});

map.on('mouseleave', 'points', function() {
    if (MmtMap.hoverInteractions.hoverFeatureId) {
        map.setFeatureState({source: 'interactive', sourceLayer: 'points', id: MmtMap.hoverInteractions.hoverFeatureId}, {hover: false});
    }
    MmtMap.hoverInteractions.hoverFeatureId = null;
    map.getCanvas().style.cursor = '';
    MmtMap.hoverInteractions.smallPopup.remove();
});


// Lines

map.on('mousemove', 'lines', function(e) {
    if (MmtMap.hoverInteractions.touch == false) {
        MmtMap.hoverInteractions.togglePopup('lines');
        feature = e.features[0];
        MmtMap.hoverInteractions.hoverFeatureId = e.features[0].properties.id;
        MmtMap.hoverInteractions.addHoverProps('interactive', 'lines', feature, MmtMap.hoverInteractions.hoverFeatureId, e.lngLat);
    }
});

map.on('mouseleave', 'lines', function() {
    if (MmtMap.hoverInteractions.hoverFeatureId) {
        map.setFeatureState({source: 'interactive', sourceLayer: 'lines', id: MmtMap.hoverInteractions.hoverFeatureId}, {hover: false});
    }
    MmtMap.hoverInteractions.hoverFeatureId = null;
    map.getCanvas().style.cursor = '';
    MmtMap.hoverInteractions.smallPopup.remove();
});


// Click interactions

map.on('click', 'points', function(e) {
    MmtMap.hoverInteractions.togglePopup('points');
    MmtMap.clickInteractions.clickFeature('interactive', 'points', e.features[0], e.features[0].properties.id, e.lngLat);
});

map.on('click', 'polygons', function(e) {
    MmtMap.hoverInteractions.togglePopup('polygons');
    MmtMap.clickInteractions.clickFeature('interactive', 'polygons', e.features[0], e.features[0].properties.id, e.lngLat);
});

map.on('click', 'lines', function(e) {
    MmtMap.hoverInteractions.togglePopup('lines');
    MmtMap.clickInteractions.clickFeature('interactive', 'lines', e.features[0], e.features[0].properties.id, e.lngLat);
});

// Locations (mmt_motm LocationPoints)

map.on('mouseenter', 'locations', function() {
    map.getCanvas().style.cursor = 'pointer';
});

map.on('mouseleave', 'locations', function() {
    map.getCanvas().style.cursor = '';
});

map.on('click', 'locations', function(e) {
    var props = e.features[0].properties;
    window.location.href = '/motm/locations/' + props.id + '/';
});

// Event lines (mmt_motm Events)

map.on('mouseenter', 'event_lines', function() {
    map.getCanvas().style.cursor = 'pointer';
});

map.on('mouseleave', 'event_lines', function() {
    map.getCanvas().style.cursor = '';
});

map.on('click', 'event_lines', function(e) {
    var props = e.features[0].properties;
    window.location.href = '/motm/events/' + props.id + '/';
});

