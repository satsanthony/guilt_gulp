// JavaScript for selected beers page

document.addEventListener('DOMContentLoaded', function() {
    const loadingSpinner = document.getElementById('loadingSpinner');
    const emptyState = document.getElementById('emptyState');
    const tableContainer = document.getElementById('beerTableContainer');

    loadSelectedBeers();

    // Re-render on window resize to switch between table/card view
    let resizeTimer;
    window.addEventListener('resize', function() {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function() {
            if (tableContainer && tableContainer.innerHTML) {
                // Re-trigger display if we have beers loaded
                const removeButtons = document.querySelectorAll('.remove-btn');
                if (removeButtons.length > 0) {
                    loadSelectedBeers();
                }
            }
        }, 250);
    });

    async function loadSelectedBeers() {
        loadingSpinner.style.display = 'block';

        try {
            const response = await fetch('/api/selected');
            const data = await response.json();

            if (!response.ok) {
                throw new Error('Failed to load beers');
            }

            if (data.beers.length === 0) {
                emptyState.style.display = 'block';
                tableContainer.innerHTML = '';
            } else {
                emptyState.style.display = 'none';
                displayBeerTable(data.beers);
            }

        } catch (error) {
            console.error('Error loading beers:', error);
            tableContainer.innerHTML = '<p style="text-align: center; color: #e74c3c;">Failed to load beers. Please try again.</p>';
        } finally {
            loadingSpinner.style.display = 'none';
        }
    }

    function isMobile() {
        return window.innerWidth <= 428;
    }

    function displayBeerTable(beers) {
        if (isMobile()) {
            // Mobile: card view
            const cardsHTML = beers.map(beer => createMobileCard(beer)).join('');
            tableContainer.innerHTML = `<div class="beer-table-mobile">${cardsHTML}</div>`;
        } else {
            // Desktop: table view
            const tableHTML = `
                <table class="beer-table">
                    <thead>
                        <tr>
                            <th>Image</th>
                            <th>Name</th>
                            <th>Brand</th>
                            <th>Calories</th>
                            <th>Carbs</th>
                            <th>ABV</th>
                            <th>Price</th>
                            <th>Where to Buy</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${beers.map(beer => createTableRow(beer)).join('')}
                    </tbody>
                </table>
            `;
            tableContainer.innerHTML = tableHTML;
        }

        // Add event listeners to remove buttons
        document.querySelectorAll('.remove-btn').forEach(btn => {
            btn.addEventListener('click', handleRemoveBeer);
        });
    }
    function createMobileCard(beer) {
        const beerInitial = beer.name.charAt(0);
        const imageStyle = beer.image 
            ? `background-image: url('${beer.image}'); background-size: cover; background-position: center;`
            : `background: linear-gradient(135deg, #d4a574 0%, #b87333 100%); display: flex; align-items: center; justify-content: center; font-size: 3rem; color: white;`;
    
        // Format stores information for mobile
        let storesHTML = '';
        if (beer.stores && beer.stores.length > 0) {
            storesHTML = `
                <div style="background-color: rgba(42, 42, 42, 0.6); padding: 12px; border-radius: 8px; margin-bottom: 12px; border-left: 3px solid var(--accent-amber);">
                    <div style="font-weight: 600; color: var(--accent-gold); margin-bottom: 10px; font-size: 0.9rem;">Available at:</div>
                    ${beer.stores.map(store => `
                        <div style="padding: 8px 0; border-bottom: 1px solid rgba(212, 165, 116, 0.2);">
                            <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">${store.name || 'N/A'}</div>
                            ${store.address ? `<div style="font-size: 0.85rem; color: var(--text-secondary); margin: 2px 0;">📍 ${store.address}</div>` : ''}
                            ${store.hours ? `<div style="font-size: 0.85rem; color: var(--text-secondary); margin: 2px 0;">🕐 ${store.hours}</div>` : ''}
                            ${store.distance ? `<div style="font-size: 0.85rem; color: var(--text-secondary); margin: 2px 0;">📏 ${store.distance}</div>` : ''}
                        </div>
                    `).join('')}
                </div>
            `;
        } else if (beer.where_to_buy) {
            storesHTML = `
                <div style="background-color: rgba(42, 42, 42, 0.6); padding: 12px; border-radius: 8px; margin-bottom: 12px;">
                    <div style="font-weight: 600; color: var(--accent-gold); margin-bottom: 5px;">Where to Buy:</div>
                    <div style="color: var(--text-secondary);">${beer.where_to_buy}</div>
                </div>
            `;
        }
    
        return `
            <div class="beer-card-mobile">
                <div class="beer-image-mobile" style="${imageStyle}">
                    ${!beer.image ? beerInitial : ''}
                </div>
                ${beer.image_source ? `
                    <div style="font-size: 0.75rem; margin-bottom: 12px; text-align: center;">
                        <a href="${beer.image_source}" target="_blank" rel="noopener noreferrer" style="color: var(--accent-gold); text-decoration: none;">
                            Image Source
                        </a>
                    </div>
                ` : ''}
                <div style="margin-bottom: 12px;">
                    <div style="font-size: 1.4rem; font-weight: 700; color: var(--text-primary); margin-bottom: 4px;">${beer.name}</div>
                    <div style="font-size: 1rem; color: var(--accent-gold);">${beer.brand || 'N/A'}</div>
                </div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px;">
                    <div style="background: linear-gradient(135deg, rgba(42, 42, 42, 0.6), rgba(26, 26, 26, 0.6)); padding: 10px; border-radius: 8px; text-align: center; border: 1px solid rgba(212, 165, 116, 0.2);">
                        <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; margin-bottom: 4px;">Calories</div>
                        <div style="font-size: 1rem; font-weight: 700; color: var(--accent-gold);">${beer.calories || 'N/A'}</div>
                    </div>
                    <div style="background: linear-gradient(135deg, rgba(42, 42, 42, 0.6), rgba(26, 26, 26, 0.6)); padding: 10px; border-radius: 8px; text-align: center; border: 1px solid rgba(212, 165, 116, 0.2);">
                        <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; margin-bottom: 4px;">Carbs</div>
                        <div style="font-size: 1rem; font-weight: 700; color: var(--accent-gold);">${beer.carbs || 'N/A'}</div>
                    </div>
                    <div style="background: linear-gradient(135deg, rgba(42, 42, 42, 0.6), rgba(26, 26, 26, 0.6)); padding: 10px; border-radius: 8px; text-align: center; border: 1px solid rgba(212, 165, 116, 0.2);">
                        <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; margin-bottom: 4px;">ABV</div>
                        <div style="font-size: 1rem; font-weight: 700; color: var(--accent-gold);">${beer.abv || 'N/A'}</div>
                    </div>
                </div>
                ${beer.description ? `<div style="font-size: 0.9rem; color: var(--text-secondary); line-height: 1.6; margin-bottom: 12px;">${beer.description}</div>` : ''}
                ${beer.price_range ? `
                    <div style="background: linear-gradient(135deg, rgba(42, 42, 42, 0.6), rgba(26, 26, 26, 0.6)); padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid rgba(212, 165, 116, 0.2);">
                        <div style="font-weight: 600; color: var(--accent-amber);">Price:</div>
                        <div style="color: var(--text-secondary);">${beer.price_range}</div>
                    </div>
                ` : ''}
                ${storesHTML}
                <button class="remove-btn" data-beer-name="${beer.name.replace(/"/g, '&quot;')}" style="width: 100%; padding: 12px; font-size: 1rem; min-height: 44px;">
                    Remove
                </button>
            </div>
        `;
    }
    function createTableRow(beer) {
        const beerInitial = beer.name.charAt(0);
        const imageStyle = beer.image 
            ? `background-image: url('${beer.image}');`
            : `background: linear-gradient(135deg, #d4a574 0%, #b87333 100%); display: flex; align-items: center; justify-content: center; font-size: 2rem; color: white;`;
    
        // Format stores information
        let storesInfo = 'N/A';
        if (beer.stores && beer.stores.length > 0) {
            storesInfo = beer.stores.map(store => {
                let parts = [];
                if (store.name) parts.push(`<strong>${store.name}</strong>`);
                if (store.address) parts.push(`📍 ${store.address}`);
                if (store.distance) parts.push(`📏 ${store.distance}`);
                return parts.join('<br>');
            }).join('<br><br>');
        } else if (beer.where_to_buy) {
            storesInfo = beer.where_to_buy;
        }
    
        return `
            <tr>
                <td>
                    <div class="table-image" style="${imageStyle}">
                        ${!beer.image ? beerInitial : ''}
                    </div>
                    ${beer.image_source ? `
                        <div style="font-size: 0.7rem; margin-top: 0.25rem;">
                            <a href="${beer.image_source}" target="_blank" rel="noopener noreferrer" style="color: #d4a574; text-decoration: none;">
                                Source
                            </a>
                        </div>
                    ` : ''}
                </td>
                <td><strong>${beer.name}</strong></td>
                <td>${beer.brand || 'N/A'}</td>
                <td>${beer.calories || 'N/A'}</td>
                <td>${beer.carbs || 'N/A'}</td>
                <td>${beer.abv || 'N/A'}</td>
                <td>${beer.price_range || 'N/A'}</td>
                <td style="font-size: 0.85rem; line-height: 1.6;">${storesInfo}</td>
                <td>
                    <button class="remove-btn" data-beer-name="${beer.name.replace(/"/g, '&quot;')}">
                        Remove
                    </button>
                </td>
            </tr>
        `;
    }


    async function handleRemoveBeer(e) {
        const beerName = e.target.getAttribute('data-beer-name');
        
        if (!confirm(`Remove "${beerName}" from your list?`)) {
            return;
        }

        try {
            const response = await fetch(`/api/selected/${encodeURIComponent(beerName)}`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                throw new Error('Failed to remove beer');
            }

            // Reload the beers
            loadSelectedBeers();

        } catch (error) {
            console.error('Error removing beer:', error);
            alert('Failed to remove beer. Please try again.');
        }
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
});




