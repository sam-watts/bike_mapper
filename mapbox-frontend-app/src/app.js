const mapboxAccessToken = 'pk.eyJ1Ijoic3dhdHRzdGd0ZyIsImEiOiJja3lvNmc5a28zMXA2MnVxcHlheGl2NWF3In0.nFWaW9_LluRnEjdPaMlAjw';
const generateRouteUrl = 'http://127.0.0.1:8000/generate_route'; // Replace with your actual API endpoint
mapboxgl.accessToken = mapboxAccessToken;

const map = new mapboxgl.Map({
    container: 'map', // ID of the container in index.html
    style: 'mapbox://styles/mapbox/streets-v11',
    center: [-3.1883, 55.9533], // Initial map center [lng, lat] for Edinburgh
    zoom: 12
});

map.on('style.load', () => {
    map.addSource('route', {
        type: 'geojson',
        data: {
            type: 'FeatureCollection',
            features: []
        }
    });

    map.addLayer({
        id: 'route-layer',
        type: 'line',
        source: 'route',
        layout: {
            'line-join': 'round',
            'line-cap': 'round'
        },
        paint: {
            'line-color': 'orange',
            'line-width': 6
        }
    });
});

const features = []; // Array to store features
let startPoint = null;
let endPoint = null;
let groupedPaths = {}; // Store the grouped paths data

const geojsonLayer = {
    type: 'FeatureCollection',
    features: []
};


function loadCycleways() {
    // Add the combined GeoJSON as a single source
    map.addSource('cycleways', {
        type: 'geojson',
        data: {
            type: 'FeatureCollection',
            features: [] // Start with an empty feature collection
        }
    });

    fetch('data/cycleways.geojson')
        .then(response => response.json())
        .then(data => {
            data.features.forEach((feature, index) => {
                feature.id = feature.properties.id; // get the osmid from properties
            });
            console.log(data)
            map.getSource('cycleways').setData(data);
        });

    // Add a single layer for all the lines
    map.addLayer({
        source: 'cycleways',
        id: 'cycleways-layer',
        type: 'line',
        layout: {
            'line-join': 'round',
            'line-cap': 'round'
        },
        paint: {
            'line-color': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                'orange', // Highlight color
                ['boolean', ['feature-state', 'selected'], false],
                'red', // Selected color
                'blue'    // Default color
            ],
            'line-width': 2.5
        }
    });
}

function loadGroupedPaths() {
    fetch('data/grouped_paths.json')
        .then(response => response.json())
        .then(data => {
            groupedPaths = data;
            populatePathGroupsDropdown(groupedPaths);
        })
        .catch(error => {
            console.error('Error loading grouped paths:', error);
        });
}

function populatePathGroupsDropdown(groupedPaths) {
    const dropdown = document.getElementById('pathGroups');

    // Clear existing options except the first one
    while (dropdown.children.length > 1) {
        dropdown.removeChild(dropdown.lastChild);
    }

    // Add options for each path group
    Object.keys(groupedPaths).forEach(groupKey => {
        const option = document.createElement('option');
        option.value = groupKey;
        // Convert underscore-separated keys to readable labels
        option.textContent = groupKey.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        dropdown.appendChild(option);
    });
}

map.on('load', () => {
    loadCycleways();
    loadGroupedPaths();
});

let hoveredFeatureId = null;
let previous_cursor = ''; // Variable to store previous cursor state

map.on('mousemove', 'cycleways-layer', (e) => {
    if (e.features.length > 0) {
        if (hoveredFeatureId !== null) {
            map.setFeatureState(
                { source: 'cycleways', id: hoveredFeatureId },
                { hover: false }
            );
        }

        // Set the hover state for the currently hovered feature
        hoveredFeatureId = e.features[0].id;
        map.setFeatureState(
            { source: 'cycleways', id: hoveredFeatureId },
            { hover: true }
        );

        if (map.getCanvas().style.cursor !== 'pointer') {
            previous_cursor = map.getCanvas().style.cursor; // Store previous cursor state
        }
        map.getCanvas().style.cursor = 'pointer'; // Change cursor to pointer
    }
});

map.on('mouseleave', 'cycleways-layer', () => {
    if (hoveredFeatureId !== null) {
        map.setFeatureState(
            { source: 'cycleways', id: hoveredFeatureId },
            { hover: false }
        );
    }
    hoveredFeatureId = null;
    map.getCanvas().style.cursor = previous_cursor; // Reset cursor to previous state
});



map.on('click', (e) => {
    const coordinates = e.lngLat.toArray();
    if (hoveredFeatureId !== null) {
        // Check if the feature is already selected
        const existingFeatureIndex = features.findIndex(feature => feature.id === hoveredFeatureId);

        if (existingFeatureIndex !== -1) {
            // Feature is already selected, so deselect it
            features.splice(existingFeatureIndex, 1);
            map.setFeatureState(
                { source: 'cycleways', id: hoveredFeatureId },
                { selected: false }
            );
        } else {
            // Feature is not selected, so select it
            features.push({
                id: hoveredFeatureId,
                coordinates: coordinates
            });
            map.setFeatureState(
                { source: 'cycleways', id: hoveredFeatureId },
                { selected: true }
            );
        }

        console.log(features);
    }
});

function generateRoute(start, end, preferredRoutes, followingWeight) {
    console.log("Generating route!")
    fetch(generateRouteUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ start: start, end: end, following_weight: followingWeight, preferred_routes: preferredRoutes })
    }).then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    }).then(data => {
        console.log("Route data:", data);
        map.getSource('route').setData(data);
    }).catch(error => {
        console.error('Error generating route:', error);
        alert('Error generating route. Please check if the backend server is running.');
    });

}


function setStart() {
    map.getCanvas().style.cursor = 'crosshair'; // Change cursor to crosshair
    map.once('click', (e) => {
        if (startPoint !== null) {
            startPoint.remove()
        }
        startPoint = new mapboxgl.Marker({ color: 'green' })
            .setLngLat(e.lngLat.toArray())
            .addTo(map);
        map.getCanvas().style.cursor = ''; // Reset cursor
    });
}

function setEnd() {
    map.getCanvas().style.cursor = 'crosshair'; // Change cursor to crosshair
    map.once('click', (e) => {
        if (endPoint !== null) {
            endPoint.remove()
        }
        endPoint = new mapboxgl.Marker({ color: 'red' })
            .setLngLat(e.lngLat.toArray())
            .addTo(map);
        map.getCanvas().style.cursor = ''; // Reset cursor
    });
}

function deselectAllRoutes() {
    // Deselect all features and clear the features array
    features.forEach(feature => {
        map.setFeatureState(
            { source: 'cycleways', id: feature.id },
            { selected: false }
        );
    });
    features.length = 0; // Clear the array
    console.log('All routes deselected');
}

function selectPathGroup(groupKey) {
    if (!groupKey || !groupedPaths[groupKey]) {
        return;
    }

    const pathGroup = groupedPaths[groupKey];

    // Extract all IDs from the group (handling both flat arrays and nested arrays)
    const idsToSelect = [];

    if (Array.isArray(pathGroup)) {
        pathGroup.forEach(item => {
            if (Array.isArray(item)) {
                // Nested array case (like st_andrews_square_to_picardy_place)
                item.forEach(subItem => {
                    if (subItem.id) {
                        idsToSelect.push(subItem.id);
                    }
                });
            } else if (item.id) {
                // Flat array case (like leith_walk)
                idsToSelect.push(item.id);
            }
        });
    }

    // Add these IDs to the features array and select them on the map
    idsToSelect.forEach(id => {
        // Check if this ID is not already selected
        const existingFeature = features.find(feature => feature.id === id);
        if (!existingFeature) {
            features.push({
                id: id,
                coordinates: null // We don't have coordinates from grouped_paths, but that's okay
            });

            map.setFeatureState(
                { source: 'cycleways', id: id },
                { selected: true }
            );
        }
    });

    console.log(`Selected path group: ${groupKey}`, features);
}

document.getElementById("setStart").onclick = setStart;
document.getElementById("setEnd").onclick = setEnd;
document.getElementById("deselectAll").onclick = deselectAllRoutes;
document.getElementById("pathGroups").onchange = function () {
    const selectedGroup = this.value;
    if (selectedGroup) {
        selectPathGroup(selectedGroup);
    }
};
document.getElementById("generateRoute").onclick = () => {
    if (startPoint && endPoint) {
        const generateButton = document.getElementById("generateRoute");
        try {
            // Start pulsing animation
            generateButton.classList.add("button-pulsing");
            generateButton.disabled = true;
            generateButton.textContent = "Generating Route...";

            const startCoords = startPoint.getLngLat().toArray();
            const endCoords = endPoint.getLngLat().toArray();
            const followingWeight = document.getElementById("slider").value;
            console.log("Following Weight:", followingWeight);
            console.log("Start:", startCoords);
            console.log("End:", endCoords);
            generateRoute(startCoords, endCoords, features.map(x => x.id), followingWeight);

        } catch (error) {
            console.error('Error generating route:', error);
            alert('Error generating route. Please check if the backend server is running.');
        } finally {
            // Stop pulsing animation
            generateButton.classList.remove("button-pulsing");
            generateButton.disabled = false;
            generateButton.textContent = "Generate Route";
        }
    } else {
        alert("Please set both start and end points.");
    }
};