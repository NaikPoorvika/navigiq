import React, { useState, useEffect } from 'react'
import Map from './components/Map'

function App() {
  const [health, setHealth] = useState<any>(null)

  useEffect(() => {
    // Test backend connection via proxy
    fetch('/api/v1/health')
      .then(res => res.json())
      .then(data => setHealth(data))
      .catch(err => console.error("Health check failed", err))
  }, [])

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>NavigIQ - AI Planning</h1>
        <div className="health-status">
          Backend Status: {health ? health.status : 'Loading...'}
        </div>
      </header>
      <main className="app-main">
        <Map />
      </main>
    </div>
  )
}

export default App
