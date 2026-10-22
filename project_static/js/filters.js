// Filter features by tag

$('.tag').click(function(e) {
    e.preventDefault();
    let tag = $(this).data('tag');
    if (tag != undefined) {
        map.setFilter('polygons', ['in', tag, ['get', 'tag_str']]);
        map.setFilter('polygon_outlines', ['in', tag, ['get', 'tag_str']]);
        map.setFilter('points', ['in', tag, ['get', 'tag_str']]);
        map.setFilter('points_labels', ['in', tag, ['get', 'tag_str']]);
        map.setFilter('polygon_labels', ['in', tag, ['get', 'tag_str']]);
        map.setFilter('line_labels', ['in', tag, ['get', 'tag_str']]);
        map.setFilter('lines', ['in', tag, ['get', 'tag_str']]);
    } else {
        map.setFilter('polygons');
        map.setFilter('polygon_outlines');
        map.setFilter('points');
        map.setFilter('points_labels');
        map.setFilter('polygon_labels');
        map.setFilter('lines');
        map.setFilter('line_labels');
    }
})