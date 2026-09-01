import React from 'react'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'

const Map = () => {
  return (
    <div style={{ height: '100%', width: '100%' }}>
      <MapContainer center={[39.8283, -98.5795]} zoom={4} style={{ height: '100%', width: '100%' }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Marker position={[39.8283, -98.5795]}>
          <Popup>
            NavigIQ AI Core. <br /> Awaiting spatial operations.
          </Popup>
        </Marker>
      </MapContainer>
    </div>
  )
}

export default Map
