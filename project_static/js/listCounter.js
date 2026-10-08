(function (window) {
    function attachFilter(options) {
        var input = options.input;
        var count = options.count;
        var items = Array.from(document.querySelectorAll(options.itemSelector));
        var getText = options.getText || function (item) {
            return item.textContent;
        };

        function filter(value) {
            var query = (value || '').toLowerCase();
            var visibleCount = 0;
            items.forEach(function (item) {
                var matches = getText(item).toLowerCase().includes(query);
                if (matches) {
                    item.style.removeProperty('display');
                } else {
                    item.style.setProperty('display', 'none', 'important');
                }
                if (matches) visibleCount += 1;
            });
            if (count) count.textContent = visibleCount;
        }

        if (input) {
            input.addEventListener('input', function () {
                filter(this.value);
            });
        }
        filter(input ? input.value : '');

        return { items: items, filter: filter };
    }

    function attachWordCloud(options) {
        var words = Array.from(document.querySelectorAll(options.itemSelector));
        var counts = words.map(function (word) {
            return parseInt(word.dataset.count, 10) || 0;
        });
        var maxCount = Math.max.apply(null, counts) || 1;
        var minCount = Math.min.apply(null, counts) || 0;
        var minSize = options.minSize || 0.85;
        var maxSize = options.maxSize || 3.0;

        words.forEach(function (word) {
            var count = parseInt(word.dataset.count, 10) || 0;
            var ratio = maxCount > minCount
                ? (count - minCount) / (maxCount - minCount)
                : 0.5;
            var size = minSize + ratio * (maxSize - minSize);
            word.style.fontSize = size.toFixed(2) + 'rem';
        });

        return attachFilter({
            input: options.input,
            count: options.count,
            itemSelector: options.itemSelector,
            getText: options.getText || function (word) {
                return word.dataset.label || word.textContent;
            }
        });
    }

    window.MmtList = {
        attachFilter: attachFilter,
        attachWordCloud: attachWordCloud
    };
})(window);