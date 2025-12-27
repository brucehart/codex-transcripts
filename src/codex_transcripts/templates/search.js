(function() {
    var totalPages = {{ total_pages }};
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

    // Hide search on file:// protocol (doesn't work due to CORS restrictions)
    if (window.location.protocol === 'file:') return;

    // Show search box (progressive enhancement)
    searchBox.style.display = 'flex';

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
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

    function highlightTextNodes(element, searchTerm) {
        var walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, null, false);
        var nodesToReplace = [];

        while (walker.nextNode()) {
            var node = walker.currentNode;
            if (node.nodeValue.toLowerCase().indexOf(searchTerm.toLowerCase()) !== -1) {
                nodesToReplace.push(node);
            }
        }

        nodesToReplace.forEach(function(node) {
            var text = node.nodeValue;
            var regex = new RegExp('(' + escapeRegex(searchTerm) + ')', 'gi');
            var parts = text.split(regex);
            if (parts.length > 1) {
                var span = document.createElement('span');
                parts.forEach(function(part) {
                    if (part.toLowerCase() === searchTerm.toLowerCase()) {
                        var mark = document.createElement('mark');
                        mark.textContent = part;
                        span.appendChild(mark);
                    } else {
                        span.appendChild(document.createTextNode(part));
                    }
                });
                node.parentNode.replaceChild(span, node);
            }
        });
    }

    function fixInternalLinks(element, pageFile) {
        var links = element.querySelectorAll('a[href^="#"]');
        links.forEach(function(link) {
            var href = link.getAttribute('href');
            link.setAttribute('href', pageFile + href);
        });
    }

    function processPage(pageFile, html, query) {
        var parser = new DOMParser();
        var doc = parser.parseFromString(html, 'text/html');
        var resultsFromPage = 0;

        var messages = doc.querySelectorAll('.message');
        messages.forEach(function(msg) {
            var text = msg.textContent || '';
            if (text.toLowerCase().indexOf(query.toLowerCase()) !== -1) {
                resultsFromPage++;

                var msgId = msg.id || '';
                var link = pageFile + (msgId ? '#' + msgId : '');

                var clone = msg.cloneNode(true);
                fixInternalLinks(clone, pageFile);
                highlightTextNodes(clone, query);

                var resultDiv = document.createElement('div');
                resultDiv.className = 'search-result';
                resultDiv.innerHTML = '<a href="' + link + '">' +
                    '<div class="search-result-page">' + escapeHtml(pageFile) + '</div>' +
                    '<div class="search-result-content">' + clone.innerHTML + '</div>' +
                    '</a>';
                searchResults.appendChild(resultDiv);
            }
        });

        return resultsFromPage;
    }

    async function performSearch(query) {
        if (!query.trim()) {
            searchStatus.textContent = 'Enter a search term';
            return;
        }

        updateUrlHash(query);
        searchResults.innerHTML = '';
        searchStatus.textContent = 'Searching...';

        var resultsFound = 0;
        var pagesSearched = 0;

        var pagesToFetch = [];
        for (var i = 1; i <= totalPages; i++) {
            pagesToFetch.push('page-' + String(i).padStart(3, '0') + '.html');
        }

        searchStatus.textContent = 'Searching...';

        var batchSize = 3;
        for (var i = 0; i < pagesToFetch.length; i += batchSize) {
            var batch = pagesToFetch.slice(i, i + batchSize);

            var promises = batch.map(function(pageFile) {
                return fetch(pageFile)
                    .then(function(response) {
                        if (!response.ok) throw new Error('Failed to fetch');
                        return response.text();
                    })
                    .then(function(html) {
                        var count = processPage(pageFile, html, query);
                        resultsFound += count;
                        pagesSearched++;
                        searchStatus.textContent = 'Found ' + resultsFound + ' result(s) in ' + pagesSearched + '/' + totalPages + ' pages...';
                    })
                    .catch(function() {
                        pagesSearched++;
                        searchStatus.textContent = 'Found ' + resultsFound + ' result(s) in ' + pagesSearched + '/' + totalPages + ' pages...';
                    });
            });

            await Promise.all(promises);
        }

        searchStatus.textContent = 'Found ' + resultsFound + ' result(s) in ' + totalPages + ' pages';
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
