/**
 * Category icon → color mapping for map rendering.
 * Lifecycle colors must match Event.LIFECYCLE_CONFIG in mmt_motm/models.py.
 * Concept category colors are used for location dot styling.
 */
var MMT_CATEGORY_COLORS = {
    // Lifecycle stage icons (source: Event.LIFECYCLE_CONFIG in mmt_motm/models.py)
    'fa-baby-carriage': '#3498db',
    'fa-person-walking': '#e74c3c',
    'fa-house-flag': '#2ecc71',
    'fa-route': '#9b59b6',
    'fa-flag': '#95a5a6',
    // Concept category icons (used by location dots)
    'fa-map-marker-alt': '#504cf1',
    'fa-university': '#3cee42',
    'fa-route': '#fc4743',
    'fa-user': '#52e1f4',
    'fa-clock': '#eee33e',
    'fa-road': '#5b6752',
    'fa-language': '#ec74fe',
    'fa-palette': '#a1a8ac',
    'fa-box-open': '#aa4098',
    'fa-sitemap': '#94b63d'
};

var MMT_DEFAULT_COLOR = '#888888';

function mmtCategoryColor(icon) {
    return MMT_CATEGORY_COLORS[icon] || '#e74c3c';
}

/**
 * Build a Mapbox GL JS 'match' expression for icon-based coloring.
 * Returns: ['match', ['get', 'icon'], 'fa-xxx', '#color', ..., '#default']
 */
function mmtCategoryColorMatch() {
    var expr = ['match', ['get', 'icon']];
    for (var icon in MMT_CATEGORY_COLORS) {
        expr.push(icon, MMT_CATEGORY_COLORS[icon]);
    }
    expr.push(MMT_DEFAULT_COLOR);
    return expr;
}
