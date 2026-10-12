(function (window) {
    var selected = new Map();

    function getState() {
        return window.MmtMapState;
    }

    function canToggle() {
        var state = getState();
        return Boolean(state && state.map);
    }

    function keyFor(item) {
        return item.type + ':' + item.id;
    }

    function idFilter(ids) {
        if (ids.length === 0) return ['==', 1, 0];
        return ['in', ['get', 'id'], ['literal', ids]];
    }

    function applyFilters() {
        var state = getState();
        if (!state || !state.map) return;

        var items = Array.from(selected.values());
        var locationIds = new Set();
        var eventIds = new Set();

        items.forEach(function (item) {
            if (item.type === 'place') locationIds.add(item.id);
            (item.location_ids || []).forEach(function (id) { locationIds.add(id); });
            (item.event_ids || []).forEach(function (id) { eventIds.add(id); });
            if (item.type === 'event') eventIds.add(item.id);
        });

        var locationFilter = items.length ? idFilter(Array.from(locationIds)) : null;
        ['locations', 'locations_labels'].forEach(function (layerId) {
            try {
                if (state.map.getLayer(layerId)) state.map.setFilter(layerId, locationFilter);
            } catch (error) {
                // Mapbox can briefly reject layer access while the style loads.
            }
        });

        state.selectionFilter = items.length ? idFilter(Array.from(eventIds)) : null;
        state.applyEventFilter();
        renderLegend();
    }

    function renderLegend() {
        var legend = document.getElementById('selection-legend');
        var itemsContainer = document.getElementById('selection-legend-items');
        if (!legend || !itemsContainer) return;

        itemsContainer.innerHTML = '';
        selected.forEach(function (item, key) {
            var row = document.createElement('div');
            row.className = 'map-selection-legend-item';

            var label = document.createElement('span');
            label.textContent = item.label;
            row.appendChild(label);

            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'map-selection-remove';
            remove.title = 'Remove ' + item.label;
            remove.setAttribute('aria-label', 'Remove ' + item.label);
            remove.innerHTML = '<i class="fas fa-times" aria-hidden="true"></i>';
            remove.addEventListener('click', function () {
                selected.delete(key);
                applyFilters();
                var checkbox = document.querySelector(
                    '[data-map-selection-key="' + CSS.escape(key) + '"]'
                );
                if (checkbox) checkbox.checked = false;
            });
            row.appendChild(remove);
            itemsContainer.appendChild(row);
        });

        legend.hidden = selected.size === 0;
    }

    window.MmtMapSelection = {
        canToggle: canToggle,
        isSelected: function (item) {
            return selected.has(keyFor(item));
        },
        toggle: function (item, checked) {
            var key = keyFor(item);
            if (checked) {
                selected.set(key, item);
            } else {
                selected.delete(key);
            }
            applyFilters();
        },
        refresh: applyFilters,
        clear: function () {
            selected.clear();
            applyFilters();
        }
    };
})(window);
