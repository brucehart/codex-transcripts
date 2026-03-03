(function() {
    var inlineIndex = window.__SEARCH_INDEX__ || null;
    var totalPages = (inlineIndex && inlineIndex.total_pages) || {{ total_pages }};
    var cachedItems = (inlineIndex && Array.isArray(inlineIndex.items)) ? inlineIndex.items : null;

    var searchBox = document.getElementById('search-box');
    var searchInput = document.getElementById('search-input');
    var searchBtn = document.getElementById('search-btn');
    var modal = document.getElementById('search-modal');
    var modalInput = document.getElementById('modal-search-input');
    var modalSearchBtn = document.getElementById('modal-search-btn');
    var modalCloseBtn = document.getElementById('modal-close-btn');
    var searchStatus = document.getElementById('search-status');
    var searchResults = document.getElementById('search-results');

    if (!searchBox || !modal) return;

    searchBox.style.display = 'flex';

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function escapeRegex(text) {
        return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function normalizeWhitespace(text) {
        return (text || '').replace(/\s+/g, ' ').trim();
    }

    function highlightSnippet(text, query) {
        var escaped = escapeHtml(text);
        var regex = new RegExp('(' + escapeRegex(query) + ')', 'gi');
        return escaped.replace(regex, '<mark>$1</mark>');
    }

    function buildSnippet(text, query) {
        var normalized = normalizeWhitespace(text);
        if (!normalized) return '';

        var lower = normalized.toLowerCase();
        var lowerQuery = query.toLowerCase();
        var index = lower.indexOf(lowerQuery);
        if (index === -1) {
            return normalized.length > 220 ? normalized.slice(0, 220) + '...' : normalized;
        }

        var start = Math.max(0, index - 100);
        var end = Math.min(normalized.length, index + query.length + 120);
        var snippet = normalized.slice(start, end);
        if (start > 0) snippet = '...' + snippet;
        if (end < normalized.length) snippet = snippet + '...';
        return snippet;
    }

    function openModal(query) {
        modalInput.value = query || '';
        searchResults.innerHTML = '';
        searchStatus.textContent = '';
        modal.showModal();
        modalInput.focus();
        if (query) {
            performSearch(query);
        }
    }

    function closeModal() {
        modal.close();
        if (window.location.hash.startsWith('#search=')) {
            history.replaceState(null, '', window.location.pathname + window.location.search);
        }
    }

    function updateUrlHash(query) {
        if (query) {
            history.replaceState(null, '', window.location.pathname + window.location.search + '#search=' + encodeURIComponent(query));
        }
    }

    async function loadIndexItems() {
        if (cachedItems) {
            return cachedItems;
        }

        if (window.location.protocol === 'file:') {
            return [];
        }

        try {
            var response = await fetch('search-index.json');
            if (!response.ok) {
                throw new Error('failed to load search-index.json');
            }
            var payload = await response.json();
            cachedItems = Array.isArray(payload.items) ? payload.items : [];
            return cachedItems;
        } catch (_) {
            return [];
        }
    }

    function renderResult(item, query) {
        var link = item.page + '#' + item.anchor;
        var role = item.role || 'Entry';
        var pageLabel = item.page || 'page';
        var timeLabel = item.timestamp || '';
        var snippet = buildSnippet(item.text || '', query);

        var resultDiv = document.createElement('div');
        resultDiv.className = 'search-result';
        resultDiv.innerHTML =
            '<a href="' + escapeHtml(link) + '">' +
                '<div class="search-result-page">' +
                    escapeHtml(pageLabel) + ' • ' + escapeHtml(role) + (timeLabel ? ' • ' + escapeHtml(timeLabel) : '') +
                '</div>' +
                '<div class="search-result-content">' + highlightSnippet(snippet, query) + '</div>' +
            '</a>';
        searchResults.appendChild(resultDiv);
    }

    async function performSearch(query) {
        var trimmed = (query || '').trim();
        if (!trimmed) {
            searchStatus.textContent = 'Enter a search term';
            return;
        }

        updateUrlHash(trimmed);
        searchResults.innerHTML = '';
        searchStatus.textContent = 'Loading search index...';

        var items = await loadIndexItems();
        if (!items.length) {
            if (window.location.protocol === 'file:') {
                searchStatus.textContent = 'Search index unavailable for file URLs. Use `codex-transcripts serve`.';
            } else {
                searchStatus.textContent = 'No search index data available.';
            }
            return;
        }

        var lowerQuery = trimmed.toLowerCase();
        var matches = [];

        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var text = normalizeWhitespace(item.text || '');
            if (!text) continue;
            if (text.toLowerCase().indexOf(lowerQuery) !== -1) {
                matches.push(item);
            }
        }

        for (var j = 0; j < matches.length; j++) {
            renderResult(matches[j], trimmed);
        }

        searchStatus.textContent =
            'Found ' + matches.length + ' result(s) in ' + items.length + ' indexed entries (' + totalPages + ' pages)';
    }

    searchBtn.addEventListener('click', function() {
        openModal(searchInput.value);
    });

    searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            openModal(searchInput.value);
        }
    });

    modalSearchBtn.addEventListener('click', function() {
        performSearch(modalInput.value);
    });

    modalInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            performSearch(modalInput.value);
        }
    });

    modalCloseBtn.addEventListener('click', closeModal);

    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeModal();
        }
    });

    if (window.location.hash.startsWith('#search=')) {
        var query = decodeURIComponent(window.location.hash.substring(8));
        if (query) {
            searchInput.value = query;
            openModal(query);
        }
    }
})();
