// Main JavaScript for search functionality

document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('searchInput');
    const searchBtn = document.getElementById('searchBtn');
    const beerResults = document.getElementById('beerResults');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const errorMessage = document.getElementById('errorMessage');

        // Search on button click
        searchBtn.addEventListener('click', searchBeers);

        // Search on Enter key
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchBeers();
            }
        });

    async function searchBeers() {
        const query = searchInput.value.trim();
        
        if (!query) {
            showError('Please enter a search query');
            return;
        }

        loadingSpinner.style.display = 'block';
        errorMessage.style.display = 'none';
        beerResults.innerHTML = '';
        searchBtn.disabled = true;
        
        // Hide instruction during search
        const instructionElement = document.getElementById('selectionInstruction');
        if (instructionElement) {
            instructionElement.style.display = 'none';
        }

        try {
            // ... rest of the function
            const response = await fetch('/api/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ query: query })
            });

            const data = await response.json();

            // Handle validation errors (400 status - non-beer queries)
            if (response.status === 400 && data.error_type === 'validation') {
                showValidationError(data.error);
                return;
            }

            if (!response.ok) {
                throw new Error(data.error || 'Search failed');
            }

            displayBeers(data.beers);

        } catch (error) {
            console.error('Search error:', error);
            showError('Failed to search for beers. Please try again.');
        } finally {
            loadingSpinner.style.display = 'none';
            searchBtn.disabled = false;
        }
    }

    function displayBeers(beers) {
        const instructionElement = document.getElementById('selectionInstruction');
        
        if (!beers || beers.length === 0) {
            beerResults.innerHTML = '<p style="text-align: center; grid-column: 1 / -1; color: #7f8c8d;">No beers found. Try a different search.</p>';
            if (instructionElement) {
                instructionElement.style.display = 'none';
            }
            return;
        }

        beerResults.innerHTML = beers.map(beer => createBeerCard(beer)).join('');
        
        // Show instruction message
        if (instructionElement) {
            instructionElement.style.display = 'block';
        }
        
        // Add event listeners to checkboxes
        document.querySelectorAll('.beer-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', handleCheckboxChange);
        });
    }

    function createBeerCard(beer) {
        // Create a simple placeholder image using CSS and beer initial
        const beerInitial = beer.name.charAt(0);
        const imageStyle = beer.image 
            ? `background-image: url('${beer.image}');`
            : `background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); display: flex; align-items: center; justify-content: center; font-size: 4rem; color: white;`;

        return `
            <div class="beer-card">
                <div class="beer-image" style="${imageStyle}">
                    ${!beer.image ? beerInitial : ''}
                </div>
                ${beer.image_source ? `
                    <div class="image-source" style="font-size: 0.75rem; color: #7f8c8d; margin-top: 0.25rem; text-align: center;">
                        <a href="${beer.image_source}" target="_blank" rel="noopener noreferrer" style="color: #3498db; text-decoration: none;">
                            Image Source
                        </a>
                    </div>
                ` : ''}
                <div class="beer-checkbox-container">
                    <input type="checkbox" class="beer-checkbox" data-beer='${JSON.stringify(beer).replace(/'/g, "&#39;")}'>
                </div>
                <div class="beer-name">${beer.name}</div>
                <div class="beer-brand">${beer.brand || 'Craft Beer'}</div>
                <div class="beer-stats">
                    ${beer.calories ? `
                        <div class="stat-item">
                            <div class="stat-label">Calories</div>
                            <div class="stat-value">${beer.calories}</div>
                        </div>
                    ` : ''}
                    ${beer.carbs ? `
                        <div class="stat-item">
                            <div class="stat-label">Carbs</div>
                            <div class="stat-value">${beer.carbs}</div>
                        </div>
                    ` : ''}
                    ${beer.abv ? `
                        <div class="stat-item">
                            <div class="stat-label">ABV</div>
                            <div class="stat-value">${beer.abv}</div>
                        </div>
                    ` : ''}
                </div>
                ${beer.description ? `<div class="beer-description">${beer.description}</div>` : ''}
                <div class="beer-info">
                    ${beer.price_range ? `<div class="info-item"><span class="info-label">Price:</span> ${beer.price_range}</div>` : ''}
                    ${beer.where_to_buy ? `<div class="info-item"><span class="info-label">Where to Buy:</span> ${beer.where_to_buy}</div>` : ''}
                </div>
                ${beer.stores && beer.stores.length > 0 ? `
                    <div class="beer-stores">
                        <div class="stores-header">Available at:</div>
                        ${beer.stores.map(store => `
                            <div class="store-item">
                                <div class="store-name">${store.name || 'N/A'}</div>
                                ${store.address ? `<div class="store-address">📍 ${store.address}</div>` : ''}
                                ${store.hours ? `<div class="store-hours">🕐 ${store.hours}</div>` : ''}
                                ${store.distance ? `<div class="store-distance">📏 ${store.distance}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    }

    async function handleCheckboxChange(e) {
        const checkbox = e.target;
        const beerData = JSON.parse(checkbox.getAttribute('data-beer').replace(/&#39;/g, "'"));

        if (checkbox.checked) {
            try {
                const response = await fetch('/api/selected', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(beerData)
                });

                if (!response.ok) {
                    throw new Error('Failed to save beer');
                }

                console.log('Beer saved successfully');

            } catch (error) {
                console.error('Error saving beer:', error);
                checkbox.checked = false;
                alert('Failed to save beer. Please try again.');
            }
        }
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        errorMessage.style.color = '#e74c3c';
        errorMessage.style.backgroundColor = '#fadbd8';
        errorMessage.style.padding = '15px';
        errorMessage.style.borderRadius = '5px';
        errorMessage.style.marginBottom = '20px';
        errorMessage.style.border = '1px solid #e74c3c';
        errorMessage.style.fontWeight = 'normal';
    }

    function showValidationError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        errorMessage.style.color = '#c0392b';
        errorMessage.style.backgroundColor = '#ffebee';
        errorMessage.style.padding = '15px';
        errorMessage.style.borderRadius = '5px';
        errorMessage.style.marginBottom = '20px';
        errorMessage.style.border = '2px solid #ef5350';
        errorMessage.style.fontWeight = 'bold';
        errorMessage.style.fontSize = '1.1rem';
        errorMessage.style.textAlign = 'center';
        
        // Clear any existing results
        beerResults.innerHTML = '';
    }

    // Logout functionality
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async function() {
            if (confirm('Are you sure you want to logout?')) {
                try {
                    const response = await fetch('/api/logout', {
                        method: 'POST'
                    });
                    const data = await response.json();
                    if (data.redirect) {
                        window.location.href = data.redirect;
                    } else {
                        window.location.href = '/login';
                    }
                } catch (error) {
                    console.error('Logout error:', error);
                    window.location.href = '/login';
                }
            }
        });
    }
    // Visitor Counter
    async function updateVisitorCount() {
        try {
            // Increment count on page load
            const response = await fetch('/api/visitor-count/increment', {
                method: 'POST'
            });
            const data = await response.json();
            
            // Display count
            const counterElement = document.getElementById('visitorCount');
            if (counterElement) {
                counterElement.textContent = data.count.toLocaleString();
            }
        } catch (error) {
            console.error('Error updating visitor count:', error);
            const counterElement = document.getElementById('visitorCount');
            if (counterElement) {
                counterElement.textContent = '---';
            }
        }
    }

    // Call on page load
    updateVisitorCount();
});