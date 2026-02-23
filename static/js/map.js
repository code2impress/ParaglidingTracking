/**
 * map.js — Leaflet map interaction for the Paragliding Tracker dashboard.
 *
 * Features:
 *  - OpenStreetMap tile layer (free, no API key)
 *  - Leaflet.draw rectangle tool for creating watch zones
 *  - Zone rectangles drawn from stored DB data on load
 *  - Click a zone rectangle or sidebar card → load live flights
 *  - Pilot markers with popups (alt, speed)
 *  - Auto-refresh every 60 s for the currently selected zone
 */

'use strict';

// ── Map initialisation ────────────────────────────────────────────────────────

const map = L.map('map', {
  center: [47.5, 12.5],   // Default: Austrian/Bavarian Alps
  zoom: 9,
  zoomControl: true,
});

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

// ── State ─────────────────────────────────────────────────────────────────────

let drawnRectangle  = null;   // temporary rectangle while naming the zone
let pendingBounds   = null;   // bbox waiting for user to enter a name
let zoneRectangles  = {};     // { zoneId: L.rectangle }
let pilotMarkers    = {};     // { zoneId: [L.marker, ...] }
let selectedZoneId  = null;
let refreshTimer    = null;

const saveModal  = new bootstrap.Modal(document.getElementById('saveZoneModal'));
const statusText = document.getElementById('status-text');
const lastRefresh = document.getElementById('last-refresh');

// ── Leaflet.draw setup ────────────────────────────────────────────────────────

const drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

const drawControl = new L.Control.Draw({
  draw: {
    rectangle: { shapeOptions: { color: '#0d6efd', weight: 2, fillOpacity: 0.1 } },
    polyline: false, polygon: false, circle: false,
    circlemarker: false, marker: false,
  },
  edit: false,
});

// Draw button toggle
document.getElementById('btn-draw').addEventListener('click', () => {
  map.addControl(drawControl);
  document.getElementById('btn-draw').classList.add('d-none');
  document.getElementById('btn-cancel-draw').classList.remove('d-none');
  // Programmatically start the rectangle draw handler
  new L.Draw.Rectangle(map, drawControl.options.draw.rectangle).enable();
  setStatus('Draw a rectangle on the map to define a watch zone.');
});

document.getElementById('btn-cancel-draw').addEventListener('click', cancelDraw);

map.on(L.Draw.Event.CREATED, (e) => {
  cancelDraw();
  const layer = e.layer;
  const b = layer.getBounds();
  pendingBounds = {
    min_lat: b.getSouth(),
    max_lat: b.getNorth(),
    min_lon: b.getWest(),
    max_lon: b.getEast(),
  };
  // Show temporary rectangle
  drawnRectangle = L.rectangle(b, { color: '#fd7e14', weight: 2,
                                     fillOpacity: 0.08, dashArray: '6' })
                    .addTo(map);
  document.getElementById('zone-name-input').value = '';
  saveModal.show();
});

function cancelDraw() {
  try { map.removeControl(drawControl); } catch (_) {}
  document.getElementById('btn-draw').classList.remove('d-none');
  document.getElementById('btn-cancel-draw').classList.add('d-none');
  setStatus('Ready.');
}

// ── Save zone ─────────────────────────────────────────────────────────────────

document.getElementById('btn-save-zone').addEventListener('click', saveZone);
document.getElementById('zone-name-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') saveZone();
});

async function saveZone() {
  const name = document.getElementById('zone-name-input').value.trim();
  if (!name) {
    document.getElementById('zone-name-input').focus();
    return;
  }
  saveModal.hide();

  try {
    const resp = await fetch('/api/zones', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ...pendingBounds }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      alert(err.error || 'Failed to save zone.');
      return;
    }
    const zone = await resp.json();
    addZoneToSidebar(zone);
    addZoneRectangle(zone);
    if (drawnRectangle) { map.removeLayer(drawnRectangle); drawnRectangle = null; }
    document.getElementById('empty-hint')?.remove();
    setStatus(`Zone "${zone.name}" saved.`);
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

// ── Render zones from server on page load ────────────────────────────────────

(function loadInitialZones() {
  document.querySelectorAll('.zone-card[data-zone-id]').forEach(card => {
    const zone = {
      id: parseInt(card.dataset.zoneId),
      name: card.querySelector('.fw-semibold').textContent.trim(),
      is_active: card.querySelector('.badge').textContent.trim() === 'Active',
      ...JSON.parse(card.dataset.bounds),
    };
    addZoneRectangle(zone);
  });
})();

// ── Zone rectangle drawing ────────────────────────────────────────────────────

function addZoneRectangle(zone) {
  const color = zone.is_active ? '#0d6efd' : '#6c757d';
  const rect = L.rectangle(
    [[zone.min_lat, zone.min_lon], [zone.max_lat, zone.max_lon]],
    { color, weight: 2, fillOpacity: 0.07 }
  ).addTo(map);

  rect.bindTooltip(zone.name, { permanent: false, sticky: true });
  rect.on('click', () => selectZone(zone.id));
  zoneRectangles[zone.id] = rect;
}

// ── Sidebar zone cards ────────────────────────────────────────────────────────

function addZoneToSidebar(zone) {
  const list = document.getElementById('zone-list');
  const div = document.createElement('div');
  div.className = 'zone-card p-3 border-bottom';
  div.dataset.zoneId = zone.id;
  div.dataset.bounds = JSON.stringify({
    min_lat: zone.min_lat, max_lat: zone.max_lat,
    min_lon: zone.min_lon, max_lon: zone.max_lon,
  });
  div.innerHTML = `
    <div class="d-flex justify-content-between align-items-start">
      <span class="fw-semibold small">${escHtml(zone.name)}</span>
      <div class="dropdown">
        <button class="btn btn-link btn-sm p-0 text-muted" data-bs-toggle="dropdown">
          <i class="bi bi-three-dots-vertical"></i>
        </button>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><button class="dropdown-item small btn-toggle-zone" data-zone-id="${zone.id}">
            <i class="bi bi-pause-fill"></i> Disable</button></li>
          <li><button class="dropdown-item small text-danger btn-delete-zone" data-zone-id="${zone.id}">
            <i class="bi bi-trash"></i> Delete</button></li>
        </ul>
      </div>
    </div>
    <span class="badge bg-success mt-1">Active</span>
    <div class="pilot-list mt-2" id="pilots-${zone.id}">
      <span class="text-muted small">Click to load flights</span>
    </div>`;
  list.appendChild(div);
  attachZoneCardListeners(div);
}

// Attach listeners to existing cards on page load
document.querySelectorAll('.zone-card').forEach(attachZoneCardListeners);

function attachZoneCardListeners(card) {
  card.addEventListener('click', (e) => {
    if (e.target.closest('.dropdown')) return;
    selectZone(parseInt(card.dataset.zoneId));
  });

  card.querySelector('.btn-delete-zone')?.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!confirm('Delete this zone?')) return;
    const zoneId = parseInt(e.currentTarget.dataset.zoneId);
    await deleteZone(zoneId);
  });

  card.querySelector('.btn-toggle-zone')?.addEventListener('click', async (e) => {
    e.stopPropagation();
    const zoneId = parseInt(e.currentTarget.dataset.zoneId);
    await toggleZone(zoneId);
  });
}

// ── Zone selection + flight loading ──────────────────────────────────────────

function selectZone(zoneId) {
  // Deselect previous
  document.querySelectorAll('.zone-card.selected')
    .forEach(c => c.classList.remove('selected'));

  const card = document.querySelector(`.zone-card[data-zone-id="${zoneId}"]`);
  if (card) {
    card.classList.add('selected');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Fit map to zone bounds
  const rect = zoneRectangles[zoneId];
  if (rect) map.fitBounds(rect.getBounds(), { padding: [40, 40] });

  selectedZoneId = zoneId;
  clearRefreshTimer();
  loadFlights(zoneId);
  refreshTimer = setInterval(() => loadFlights(zoneId), 60_000);
}

async function loadFlights(zoneId) {
  setStatus(`Loading flights for zone ${zoneId}…`);
  clearPilotMarkers(zoneId);

  try {
    const resp = await fetch(`/api/flights/${zoneId}`);
    if (!resp.ok) { setStatus('Error loading flights.'); return; }
    const pilots = await resp.json();

    const pilotList = document.getElementById(`pilots-${zoneId}`);
    if (!pilotList) return;

    if (pilots.length === 0) {
      pilotList.innerHTML = '<span class="text-muted small">No paragliders detected.</span>';
      setStatus('No paragliders in zone right now.');
    } else {
      pilotList.innerHTML = pilots.map(p => `
        <div class="pilot-item">
          <span>🪂 ${escHtml(p.name)}</span>
          <span class="text-muted">${p.alt != null ? p.alt + ' m' : '—'}</span>
        </div>`).join('');
      setStatus(`${pilots.length} paraglider(s) in zone.`);
      addPilotMarkers(zoneId, pilots);
    }

    lastRefresh.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (err) {
    setStatus('Network error: ' + err.message);
  }
}

function addPilotMarkers(zoneId, pilots) {
  pilotMarkers[zoneId] = [];
  pilots.forEach(p => {
    if (p.lat == null || p.lon == null) return;
    const icon = L.divIcon({
      className: '',
      html: '<span style="font-size:1.4rem">🪂</span>',
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
    const marker = L.marker([p.lat, p.lon], { icon })
      .addTo(map)
      .bindPopup(`
        <div class="pilot-popup">
          <h6 class="mb-1">${escHtml(p.name)}</h6>
          <div><strong>Alt:</strong> ${p.alt != null ? p.alt + ' m' : 'n/a'}</div>
          <div><strong>Speed:</strong> ${p.speed != null ? (p.speed * 3.6).toFixed(0) + ' km/h' : 'n/a'}</div>
        </div>`);
    pilotMarkers[zoneId].push(marker);
  });
}

function clearPilotMarkers(zoneId) {
  (pilotMarkers[zoneId] || []).forEach(m => map.removeLayer(m));
  pilotMarkers[zoneId] = [];
}

// ── Zone actions ──────────────────────────────────────────────────────────────

async function deleteZone(zoneId) {
  try {
    const resp = await fetch(`/api/zones/${zoneId}`, { method: 'DELETE' });
    if (!resp.ok) { alert('Failed to delete zone.'); return; }
    // Remove from map
    if (zoneRectangles[zoneId]) {
      map.removeLayer(zoneRectangles[zoneId]);
      delete zoneRectangles[zoneId];
    }
    clearPilotMarkers(zoneId);
    // Remove from sidebar
    document.querySelector(`.zone-card[data-zone-id="${zoneId}"]`)?.remove();
    if (selectedZoneId === zoneId) {
      selectedZoneId = null;
      clearRefreshTimer();
    }
    setStatus('Zone deleted.');
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

async function toggleZone(zoneId) {
  try {
    const resp = await fetch(`/api/zones/${zoneId}/toggle`, { method: 'PATCH' });
    if (!resp.ok) { alert('Failed to toggle zone.'); return; }
    const zone = await resp.json();

    // Update badge
    const card = document.querySelector(`.zone-card[data-zone-id="${zoneId}"]`);
    if (card) {
      const badge = card.querySelector('.badge');
      badge.textContent = zone.is_active ? 'Active' : 'Paused';
      badge.className = `badge mt-1 ${zone.is_active ? 'bg-success' : 'bg-secondary'}`;
      const btn = card.querySelector('.btn-toggle-zone');
      btn.innerHTML = zone.is_active
        ? '<i class="bi bi-pause-fill"></i> Disable'
        : '<i class="bi bi-play-fill"></i> Enable';
    }
    // Update rectangle colour
    if (zoneRectangles[zoneId]) {
      zoneRectangles[zoneId].setStyle({ color: zone.is_active ? '#0d6efd' : '#6c757d' });
    }
  } catch (err) {
    alert('Network error: ' + err.message);
  }
}

// ── Refresh button ────────────────────────────────────────────────────────────

document.getElementById('btn-refresh').addEventListener('click', () => {
  if (viewAllActive) loadAllGliders();
  else if (selectedZoneId) loadFlights(selectedZoneId);
  else setStatus('Select a zone or click "View all gliders".');
});

// ── View All Gliders ──────────────────────────────────────────────────────────

let viewAllActive   = false;
let viewAllMarkers  = [];
let viewAllTimer    = null;

document.getElementById('btn-view-all').addEventListener('click', () => {
  viewAllActive = true;
  document.getElementById('btn-view-all').classList.add('d-none');
  document.getElementById('btn-clear-all').classList.remove('d-none');
  // Deselect any zone
  document.querySelectorAll('.zone-card.selected').forEach(c => c.classList.remove('selected'));
  clearRefreshTimer();
  loadAllGliders();
  viewAllTimer = setInterval(loadAllGliders, 60_000);
});

document.getElementById('btn-clear-all').addEventListener('click', () => {
  clearViewAll();
  setStatus('Ready.');
});

function clearViewAll() {
  viewAllActive = false;
  viewAllMarkers.forEach(m => map.removeLayer(m));
  viewAllMarkers = [];
  if (viewAllTimer) { clearInterval(viewAllTimer); viewAllTimer = null; }
  document.getElementById('btn-view-all').classList.remove('d-none');
  document.getElementById('btn-clear-all').classList.add('d-none');
}

async function loadAllGliders() {
  const b = map.getBounds();
  const params = new URLSearchParams({
    min_lat: b.getSouth().toFixed(6),
    max_lat: b.getNorth().toFixed(6),
    min_lon: b.getWest().toFixed(6),
    max_lon: b.getEast().toFixed(6),
  });

  setStatus('Loading all gliders in view…');
  viewAllMarkers.forEach(m => map.removeLayer(m));
  viewAllMarkers = [];

  try {
    const resp = await fetch(`/api/flights/all?${params}`);
    if (!resp.ok) { setStatus('Error loading gliders.'); return; }
    const data = await resp.json();
    const pilots = data.pilots || [];

    if (pilots.length === 0) {
      setStatus('No active paragliders / hang-gliders in view right now.');
    } else {
      pilots.forEach(p => {
        if (p.lat == null || p.lon == null) return;
        const typeLabel = p.type === 6 ? '🏄' : '🪂';
        const icon = L.divIcon({
          className: '',
          html: `<span style="font-size:1.4rem">${typeLabel}</span>`,
          iconSize: [24, 24], iconAnchor: [12, 12],
        });
        const ageMins = p.age != null ? Math.round(p.age / 60) : null;
        const marker = L.marker([p.lat, p.lon], { icon })
          .addTo(map)
          .bindPopup(`
            <div class="pilot-popup">
              <h6 class="mb-1">${escHtml(p.name)}</h6>
              <div><strong>Alt:</strong> ${p.alt != null ? p.alt + ' m' : 'n/a'}</div>
              <div><strong>Speed:</strong> ${p.speed != null ? (p.speed * 3.6).toFixed(0) + ' km/h' : 'n/a'}</div>
              <div><strong>Vario:</strong> ${p.vspeed != null ? p.vspeed + ' m/s' : 'n/a'}</div>
              <div><strong>Last fix:</strong> ${ageMins != null ? ageMins + ' min ago' : 'n/a'}</div>
              <div><strong>Type:</strong> ${p.type === 7 ? 'Paraglider' : p.type === 6 ? 'Hang-glider' : 'Unknown'}</div>
            </div>`);
        viewAllMarkers.push(marker);
      });
      setStatus(`${pilots.length} active paraglider${pilots.length !== 1 ? 's' : ''} / hang-glider${pilots.length !== 1 ? 's' : ''} in view.`);
    }
    lastRefresh.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (err) {
    setStatus('Network error: ' + err.message);
  }
}

// Clear view-all markers when user pans/zooms and re-fetch for new area
map.on('moveend', () => {
  if (viewAllActive) loadAllGliders();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function setStatus(msg) { statusText.textContent = msg; }

function clearRefreshTimer() {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
}

function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
