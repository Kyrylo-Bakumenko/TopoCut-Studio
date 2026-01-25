import React, { useEffect, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, Circle, useMapEvents, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import 'leaflet-edgebuffer';

// Fix leaflet default icon issue
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

let DefaultIcon = L.icon({
  iconUrl: icon,
  shadowUrl: iconShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

interface MapSelectorProps {
  lat: number;
  lon: number;
  radius: number;
  setCoords: (lat: number, lon: number) => void;
}

// Handle map click events
const LocationMarker: React.FC<{
  setCoords: (lat: number, lon: number) => void;
  onInteractionStart: () => void;
}> = ({ setCoords, onInteractionStart }) => {
  useMapEvents({
    click(e) {
      setCoords(e.latlng.lat, e.latlng.lng);
    },
    dragstart() {
      onInteractionStart();
    },
    zoomstart() {
      onInteractionStart();
    },
  });
  return null;
};

// Manage recentering with debounce to avoid fighting user interaction
const MapController: React.FC<{
  lat: number;
  lon: number;
  skipRecenterRef: React.MutableRefObject<boolean>;
}> = ({ lat, lon, skipRecenterRef }) => {
  const map = useMap();
  const prevLatLon = useRef({ lat, lon });

  useEffect(() => {
    // skip recenter if user just interacted (click, drag, zoom)
    if (skipRecenterRef.current) {
      skipRecenterRef.current = false;
      prevLatLon.current = { lat, lon };
      return;
    }

    // only recenter if coordinates actually changed significantly
    // this prevents micro-jitters from floating point
    const threshold = 0.00001;
    const latDiff = Math.abs(prevLatLon.current.lat - lat);
    const lonDiff = Math.abs(prevLatLon.current.lon - lon);

    if (latDiff > threshold || lonDiff > threshold) {
      // use panTo for smoother animation, flyTo is jerky
      map.panTo([lat, lon], { animate: true, duration: 0.25 });
      prevLatLon.current = { lat, lon };
    }
  }, [lat, lon, map, skipRecenterRef]);

  return null;
};

const MapSelector: React.FC<MapSelectorProps> = ({ lat, lon, radius, setCoords }) => {
  // ref to skip recentering when user clicks/drags/zooms
  const skipRecenterRef = useRef(false);

  const handleInteractionStart = useCallback(() => {
    skipRecenterRef.current = true;
  }, []);

  return (
    <MapContainer
      center={[lat, lon]}
      zoom={13}
      style={{ height: '100%', width: '100%' }}
      // allow smooth scrolling and interactions
      scrollWheelZoom={true}
      doubleClickZoom={true}
      dragging={true}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        // @ts-ignore - leaflet-edgebuffer extension
        edgeBufferTiles={3}
        keepBuffer={4}
      />
      <LocationMarker setCoords={setCoords} onInteractionStart={handleInteractionStart} />
      <MapController lat={lat} lon={lon} skipRecenterRef={skipRecenterRef} />
      <Circle
        center={[lat, lon]}
        radius={radius}
        pathOptions={{ color: 'red', fillColor: 'red', fillOpacity: 0.2 }}
      />
    </MapContainer>
  );
};

export default MapSelector;
