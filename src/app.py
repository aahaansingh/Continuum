import sys
import os

# Ensure we can import from src folder (where solver.py resides)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import random
import time
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from solver import solver


app = Flask(__name__, static_folder='../client/dist', static_url_path='/')
frontend_url = os.environ.get("FRONTEND_URL", "*")
CORS(app, origins=[frontend_url])

# --- Helpers ---

def get_spotify_auth_manager(mode='user'):
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.environ.get("SPOTIPY_REDIRECT_URI")
    
    if mode == 'client':
        return SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    else:
        return SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="user-library-modify playlist-modify-public playlist-read-private user-read-private user-read-email",
            cache_path=".spotify_cache",
            open_browser=False
        )

def get_gsbpm_features(artist, title):
    api_key = os.environ.get("GETSONGBPM_API_KEY")
    if not api_key: return None
    
    url = "https://api.getsong.co/search/"
    params = {"api_key": api_key, "type": "both", "lookup": f"song:{title} artist:{artist}"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if isinstance(data, dict) and 'search' in data and data['search']:
            res = data['search'][0]
            if not res.get('key_of') or not res.get('tempo'): return None
            
            dance = res.get('danceability')
            energy = float(dance) if dance is not None else 0.5
            
            return {
                'key': int(res['key_of']), 
                'mode': int(res.get('mode', 1)),
                'tempo': float(res['tempo']),
                'energy': energy,
                'BPM': float(res['tempo'])
            }
        return None
    except:
        return None

# --- Routes ---

@app.route('/')
def serve_index():
    if os.path.exists(app.static_folder):
        return send_from_directory(app.static_folder, 'index.html')
    return "Backend Running. Frontend not built.", 200

@app.route('/api/auth/url', methods=['GET'])
def auth_url():
    """Get Spotify Auth URL for User Mode."""
    auth = get_spotify_auth_manager('user')
    return jsonify({'url': auth.get_authorize_url()})

@app.route('/api/auth/token', methods=['POST'])
def get_token():
    """Exchange manual callback URL/Code for Token."""
    data = request.json
    redirected_url = data.get('url')
    
    auth = get_spotify_auth_manager('user')
    try:
        code = auth.parse_response_code(redirected_url)
        token = auth.get_access_token(code)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """Check if we have a valid cached token."""
    auth = get_spotify_auth_manager('user')
    token = auth.get_cached_token()
    return jsonify({'authenticated': bool(token)})

@app.route('/api/playlist', methods=['POST'])
def fetch_playlist():
    """Fetch tracks from Playlist (supports User or Client mode)."""
    data = request.json
    pl_id = data.get('id')
    mode = data.get('mode', 'user') # 'user' or 'client'
    
    if mode == 'client':
        sp = spotipy.Spotify(auth_manager=get_spotify_auth_manager('client'))
    else:
        auth = get_spotify_auth_manager('user')
        token = auth.get_cached_token()
        if not token: return jsonify({'error': 'Not authenticated'}), 401
        sp = spotipy.Spotify(auth=token['access_token'])
        
    try:
        if "spotify.com" in pl_id:
            pl_id = pl_id.split("/")[-1].split("?")[0]
            
        results = sp.playlist_items(pl_id)
        tracks = results['items']
        while results['next'] and len(tracks) < 500: # Limit 500 for web
            results = sp.next(results)
            tracks.extend(results['items'])
            
        clean = []
        for item in tracks:
            t = item.get('track')
            if t and not t.get('is_local'):
                clean.append({
                    'id': t['id'],
                    'name': t['name'],
                    'artist': t['artists'][0]['name'],
                    'album': t['album']['name'],
                    'uri': t['uri'],
                    'duration_ms': t['duration_ms']
                })
        
        # Sample if too big
        if len(clean) > 100:
            clean = random.sample(clean, 100)
            
        return jsonify({'tracks': clean})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/recommendations', methods=['POST'])
def fetch_recs():
    """Fetch Artist-Based Recommendations."""
    data = request.json
    seed = data.get('seed')
    mode = data.get('mode', 'user')
    
    if mode == 'client':
        sp = spotipy.Spotify(auth_manager=get_spotify_auth_manager('client'))
    else:
        auth = get_spotify_auth_manager('user')
        token = auth.get_cached_token()
        if not token: return jsonify({'error': 'Not authenticated'}), 401
        sp = spotipy.Spotify(auth=token['access_token'])
        
    try:
        results = sp.search(q=seed, type='artist', limit=1)
        if not results['artists']['items']: return jsonify({'error': 'Artist not found'}), 404
        
        artist = results['artists']['items'][0]
        related = sp.artist_related_artists(artist['id'])['artists']
        related.insert(0, artist)
        
        pool = []
        for art in related[:10]: # Top 10 related
            top = sp.artist_top_tracks(art['id'])['tracks']
            for t in top:
                pool.append({
                    'id': t['id'],
                    'name': t['name'],
                    'artist': t['artists'][0]['name'],
                    'album': t['album']['name'],
                    'uri': t['uri'],
                    'duration_ms': t['duration_ms']
                })
                
        if len(pool) > 100: pool = random.sample(pool, 100)
        return jsonify({'tracks': pool})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/features', methods=['POST'])
def fetch_features():
    """Fetch GetSongBPM features for a single track."""
    data = request.json
    track = data.get('track')
    feat = get_gsbpm_features(track['artist'], track['name'])
    
    if feat:
        # Merge features
        track.update(feat)
        return jsonify({'track': track, 'found': True})
    else:
        return jsonify({'track': track, 'found': False})

@app.route('/api/solve', methods=['POST'])
def run_solver():
    """Run Solver on provided songs."""
    data = request.json
    songs = data.get('songs')
    mix_min = float(data.get('length', 45))
    
    # Solver
    s = solver(
        songs_lst=songs,
        key_fn_dict={'key_pen':1,0:6,1:3,2:1,3:0,4:0,5:0,6:0},
        modal_pen=2, tempo_wt=0.1, energy_wt=2.0, target_energy_diff=0.05,
        threshold=int(mix_min*60000)
    )
    res = s.solve()
    
    if res:
        # Sort songs by result order
        ids = res['song_ids']
        ordered = []
        for sid in ids:
            t = next((x for x in songs if x['id'] == sid), None)
            if t: ordered.append(t)
            
        return jsonify({'success': True, 'mix': ordered})
    else:
        return jsonify({'success': False, 'message': 'No solution found'}), 400

@app.route('/api/save', methods=['POST'])
def save_playlist():
    """Save playlist to Spotify."""
    data = request.json
    uris = data.get('uris')
    
    auth = get_spotify_auth_manager('user')
    token = auth.get_cached_token()
    if not token: return jsonify({'error': 'Not authenticated'}), 401
    sp = spotipy.Spotify(auth=token['access_token'])
    
    try:
        uid = sp.current_user()['id']
        pl = sp.user_playlist_create(uid, "Continuum Mix", public=True, description="Generated via Continuum Web")
        for i in range(0, len(uris), 100):
            sp.playlist_add_items(pl['id'], uris[i:i+100])
        return jsonify({'url': pl['external_urls']['spotify']})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
