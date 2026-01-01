import { useState, useEffect } from 'react'

function App() {
  const [step, setStep] = useState('auth') // auth, source, processing, results
  const [authMode, setAuthMode] = useState('client') // client, user
  const [sourceMode, setSourceMode] = useState('playlist') // playlist, recs
  const [inputValue, setInputValue] = useState('')
  const [mixLength, setMixLength] = useState(45)
  const [tracks, setTracks] = useState([])
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('')
  const [resultMix, setResultMix] = useState([])
  const [savedUrl, setSavedUrl] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    // Check if auth token exists? Not really needed for web flow start
  }, [])

  const handleAuth = async () => {
    if (authMode === 'client') {
      setStep('source')
    } else {
      // User auth flow
      try {
        const res = await fetch('/api/auth/url')
        const data = await res.json()
        window.open(data.url, '_blank')

        const pasted = prompt("Please paste the full redirected URL here:")
        if (pasted) {
          const tokenRes = await fetch('/api/auth/token', {
            method: 'POST', body: JSON.stringify({ url: pasted }), headers: { 'Content-Type': 'application/json' }
          })
          const tokenData = await tokenRes.json()
          if (tokenData.success) {
            setStep('source')
          } else {
            setError(tokenData.error || "Auth Failed")
          }
        }
      } catch (e) {
        setError(e.message)
      }
    }
  }

  const handleFetch = async () => {
    setStep('processing')
    setError('')
    setStatus('Fetching tracks...')

    try {
      let endpoint = sourceMode === 'playlist' ? '/api/playlist' : '/api/recommendations'
      let payload = sourceMode === 'playlist'
        ? { id: inputValue, mode: authMode }
        : { seed: inputValue, mode: authMode }

      const res = await fetch(endpoint, {
        method: 'POST', body: JSON.stringify(payload), headers: { 'Content-Type': 'application/json' }
      })
      const data = await res.json()

      if (data.error) throw new Error(data.error)

      // Process GSBPM features
      let rawTracks = data.tracks
      let processed = []

      for (let i = 0; i < rawTracks.length; i++) {
        let t = rawTracks[i]
        setProgress(((i) / rawTracks.length) * 100)
        setStatus(`Processing [${i + 1}/${rawTracks.length}]: ${t.name}`)

        const featRes = await fetch('/api/features', {
          method: 'POST', body: JSON.stringify({ track: t }), headers: { 'Content-Type': 'application/json' }
        })
        const featData = await featRes.json()
        if (featData.found) {
          processed.push(featData.track)
        }
      }

      setTracks(processed)
      setStatus('Running Solver...')
      setProgress(100)

      const solveRes = await fetch('/api/solve', {
        method: 'POST',
        body: JSON.stringify({ songs: processed, length: mixLength }),
        headers: { 'Content-Type': 'application/json' }
      })
      const solveData = await solveRes.json()

      if (solveData.success) {
        setResultMix(solveData.mix)
        setStep('results')
      } else {
        setError(solveData.message || "Solver failed")
        setStep('source')
      }

    } catch (e) {
      setError(e.message)
      setStep('source')
    }
  }

  const handleSave = async () => {
    try {
      const uris = resultMix.map(t => t.uri)
      const res = await fetch('/api/save', {
        method: 'POST', body: JSON.stringify({ uris }), headers: { 'Content-Type': 'application/json' }
      })
      const data = await res.json()
      if (data.url) {
        setSavedUrl(data.url)
      } else {
        alert("Error: " + data.error)
      }
    } catch (e) {
      alert(e.message)
    }
  }

  const handleExport = () => {
    const text = resultMix.map(t => `${t.artist} - ${t.name}`).join('\n')
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'mix.txt'
    a.click()
  }

  return (
    <div className="bg min-h-screen text-text p-8 flex flex-col items-center">
      <h1 className="mb-8 font-bold text-center">Continuum</h1>

      {error && <div className="card mb-4 border border-red-500 text-red-400">{error}</div>}

      {step === 'auth' && (
        <div className="card">
          <h2 className="text-xl mb-4 font-bold text-secondary">Authentication</h2>
          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-2">
              <input type="radio" name="auth" checked={authMode === 'client'} onChange={() => setAuthMode('client')} />
              Client Credentials (Read-Only, No Limits)
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="auth" checked={authMode === 'user'} onChange={() => setAuthMode('user')} />
              User Authentication (Can Create Playlists)
            </label>
          </div>
          <button className="mt-6 w-full" onClick={handleAuth}>Continue</button>
        </div>
      )}

      {step === 'source' && (
        <div className="card">
          <h2 className="text-xl mb-4 font-bold text-secondary">Configuration</h2>

          <div className="mb-4">
            <label className="block text-sm text-gray-400">Source</label>
            <select value={sourceMode} onChange={e => setSourceMode(e.target.value)}>
              <option value="playlist">Existing Playlist</option>
              <option value="recs">Recommendations (Artist Seed)</option>
            </select>
          </div>

          <div className="mb-4">
            <label className="block text-sm text-gray-400">
              {sourceMode === 'playlist' ? 'Playlist ID or URL' : 'Seed Artist Name'}
            </label>
            <input
              type="text"
              value={inputValue}
              onChange={e => setInputValue(e.target.value)}
              placeholder={sourceMode === 'playlist' ? 'https://open.spotify.com/playlist/...' : 'e.g. Daft Punk'}
            />
          </div>

          <div className="mb-6">
            <label className="block text-sm text-gray-400">Target Mix Length (min)</label>
            <input
              type="number"
              value={mixLength}
              onChange={e => setMixLength(e.target.value)}
            />
          </div>

          <button className="w-full" onClick={handleFetch}>Generate Mix</button>
        </div>
      )}

      {step === 'processing' && (
        <div className="card text-center">
          <h2 className="text-xl mb-4 text-hl">Processing...</h2>
          <p className="text-sm mb-2">{status}</p>
          <div className="prog-bar">
            <div className="prog-fill" style={{ width: `${progress}%` }}></div>
          </div>
          <div className="text-xs text-gray-500">
            Please wait while we fetch features from GetSongBPM.
          </div>
        </div>
      )}

      {step === 'results' && (
        <div className="card max-w-4xl">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl font-bold text-primary">Optimal Mix Generated</h2>
            <div className="flex gap-2">
              <button onClick={() => setStep('source')}>Start Over</button>
              <button onClick={handleExport}>Export mix.txt</button>
              {authMode === 'user' && (
                <button onClick={handleSave} className="bg-primary text-bg font-bold">
                  Save to Spotify
                </button>
              )}
            </div>
          </div>

          {savedUrl && (
            <div className="p-4 bg-green-900 text-green-200 rounded mb-4 text-center">
              Saved! <a href={savedUrl} target="_blank" className="underline">Open Playlist</a>
            </div>
          )}

          <div className="bg-bg p-4 rounded max-h-96 overflow-y-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="pb-2">#</th>
                  <th className="pb-2">Artist</th>
                  <th className="pb-2">Track</th>
                  <th className="pb-2">Key</th>
                  <th className="pb-2">BPM</th>
                </tr>
              </thead>
              <tbody>
                {resultMix.map((t, i) => (
                  <tr key={t.id} className="border-b border-gray-800 hover:bg-gray-800">
                    <td className="py-2 text-gray-500">{i + 1}</td>
                    <td className="py-2 text-secondary">{t.artist}</td>
                    <td className="py-2">{t.name}</td>
                    <td className="py-2 text-hl">{t.key} {t.mode === 1 ? 'Maj' : 'Min'}</td>
                    <td className="py-2 text-gray-400">{t.BPM}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <footer className="mt-12 mb-4 text-xs text-gray-500">
        Powered by <a href="https://getsongbpm.com/" target="_blank" rel="noopener noreferrer" className="underline hover:text-primary transition-colors">GetSongBPM</a>
      </footer>
    </div>
  )
}

export default App
