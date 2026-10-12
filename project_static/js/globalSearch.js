(function () {
    var searchInput = document.getElementById('map_search');
    var loadingIndicator = document.getElementById('map-search-loading');
    var resultsBox = document.getElementById('person-search-results');
    if (!searchInput || !resultsBox) return;

    var searchUrl = searchInput.dataset.searchUrl;
    var labels = {
        people: resultsBox.dataset.labelPeople,
        places: resultsBox.dataset.labelPlaces,
        events: resultsBox.dataset.labelEvents,
        concepts: resultsBox.dataset.labelConcepts
    };
    var requestNumber = 0;
    var debounceTimer;
    var searchForm = searchInput.closest('form');
    var categories = [
        { key: 'people', label: labels.people, checkable: true },
        { key: 'places', label: labels.places, checkable: true },
        { key: 'events', label: labels.events, checkable: true },
        { key: 'concepts', label: labels.concepts, checkable: false }
    ];

    function appendHeading(label) {
        var heading = document.createElement('div');
        heading.className = 'list-group-item list-group-item-secondary small';
        heading.textContent = label;
        resultsBox.appendChild(heading);
    }

    function appendResult(item, checkable) {
        var row = document.createElement('div');
        row.className = 'list-group-item search-suggestion d-flex align-items-center';

        if (checkable && window.MmtMapSelection && window.MmtMapSelection.canToggle()) {
            var checkbox = document.createElement('input');
            var selectionKey = item.type + ':' + item.id;
            checkbox.type = 'checkbox';
            checkbox.className = 'mr-2 search-suggestion-toggle';
            checkbox.checked = window.MmtMapSelection.isSelected(item);
            checkbox.dataset.mapSelectionKey = selectionKey;
            checkbox.setAttribute('aria-label', item.label);
            checkbox.addEventListener('click', function (event) {
                event.stopPropagation();
            });
            checkbox.addEventListener('change', function () {
                window.MmtMapSelection.toggle(item, checkbox.checked);
            });
            row.appendChild(checkbox);
        }

        var link = document.createElement('a');
        link.className = 'list-group-item-action flex-grow-1';
        link.href = item.url;
        link.textContent = item.label;
        row.appendChild(link);
        resultsBox.appendChild(row);
    }

    function setLoading(isLoading) {
        if (loadingIndicator) {
            loadingIndicator.style.display = isLoading ? 'inline-block' : 'none';
            loadingIndicator.setAttribute('aria-hidden', isLoading ? 'false' : 'true');
        }
        searchInput.setAttribute('aria-busy', isLoading ? 'true' : 'false');
    }

    function renderResults(data) {
        setLoading(false);
        resultsBox.innerHTML = '';
        var hasResults = false;
        categories.forEach(function (category) {
            var items = data[category.key] || [];
            if (items.length === 0) return;
            hasResults = true;
            appendHeading(category.label);
            items.forEach(function (item) {
                appendResult(item, category.checkable);
            });
        });
        resultsBox.style.display = hasResults ? 'block' : 'none';
    }

    function fetchResults(query) {
        var currentRequest = ++requestNumber;
        fetch(searchUrl + '?q=' + encodeURIComponent(query))
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (currentRequest === requestNumber) renderResults(data);
            })
            .catch(function () {
                if (currentRequest === requestNumber) {
                    setLoading(false);
                    resultsBox.style.display = 'none';
                }
            });
    }

    searchInput.addEventListener('input', function () {
        clearTimeout(debounceTimer);
        var query = this.value.trim();
        requestNumber += 1;
        if (query.length < 3) {
            setLoading(false);
            resultsBox.style.display = 'none';
            return;
        }
        setLoading(true);
        debounceTimer = setTimeout(function () {
            fetchResults(query);
        }, 250);
    });

    if (searchForm) {
        searchForm.addEventListener('submit', function (event) {
            event.preventDefault();
        });
    }

    document.addEventListener('click', function (event) {
        if (!resultsBox.contains(event.target) && event.target !== searchInput) {
            resultsBox.style.display = 'none';
        }
    });
})();
