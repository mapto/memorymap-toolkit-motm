/**
 * Single source of truth for category icon → color mapping.
 * Used by detail-page maps (_map_init.html) and the main map (mapHandler.js).
 */
var MMT_CATEGORY_COLORS = {
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
