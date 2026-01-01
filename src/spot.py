import os
import sys
import time
import random
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from solver import solver

def get_spotify_client():
    """Authenticates and returns a Spotify client + Auth Mode."""
    print("\n--- Authentication Mode ---")
    print("[1] User Authentication (Standard)")
    print("    - Can create playlists directly.")
    print("    - Subject to 25-user development cap.")
    print("[2] Client Credentials (Read-Only)")
    print("    - Bypasses user cap.")
    print("    - CANNOT create playlists (exports to 'mix.txt').")
    
    mode = input("Select mode (1/2): ").strip()
    user_auth = (mode != '2')
    
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
    redirect_uri = os.environ.get("SPOTIPY_REDIRECT_URI")

    if not client_id or not client_secret:
        print("\nCredentials not found in environment variables.")
        if not client_id: client_id = input("Enter Client ID: ").strip()
        if not client_secret: client_secret = input("Enter Client Secret: ").strip()
        os.environ["SPOTIPY_CLIENT_ID"] = client_id
        os.environ["SPOTIPY_CLIENT_SECRET"] = client_secret

    if user_auth:
        print("\nInitializing User Authentication...")
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="user-library-modify playlist-modify-public playlist-read-private user-read-private user-read-email",
            cache_path=".spotify_cache",
            open_browser=False
        )
        
        # Check token interaction (manual flow support)
        token_info = auth_manager.get_cached_token()
        if not token_info:
            print("\n--- Authentication Required ---")
            auth_url = auth_manager.get_authorize_url()
            print(f"pVisit: {auth_url}")
            resp = input("Paste redirected URL: ").strip()
            try:
                code = auth_manager.parse_response_code(resp)
                auth_manager.get_access_token(code)
            except Exception as e:
                print(f"Auth failed: {e}")
                return None, False
        
        return spotipy.Spotify(auth_manager=auth_manager), True
    else:
        print("\nInitializing Client Credentials (Read-Only)...")
        auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
        return spotipy.Spotify(auth_manager=auth_manager), False

def get_playlist_tracks(sp, limit=100):
    """Fetches tracks from a playlist."""
    print("\n--- Source: Playlist ---")
    playlist_id = input("Enter Playlist ID/URL: ").strip()
    if "spotify.com" in playlist_id:
        playlist_id = playlist_id.split("/")[-1].split("?")[0]

    try:
        results = sp.playlist_items(playlist_id)
        tracks = results['items']
        while results['next'] and len(tracks) < 1000:
            results = sp.next(results)
            tracks.extend(results['items'])
        
        clean = [item['track'] for item in tracks if item.get('track') and not item['track'].get('is_local')]
        
        if len(clean) > limit:
            print(f"Sampling {limit} from {len(clean)} tracks...")
            clean = random.sample(clean, limit)
        return clean
    except Exception as e:
        print(f"Error: {e}")
        return []

def get_recommendations_artist_based(sp, limit=100):
    """Generates recommendations by finding related artists -> top tracks."""
    print("\n--- Source: Recommendations (Artist-Based) ---")
    seed_name = input("Enter Seed Artist Name: ").strip()
    
    try:
        # 1. Search for Artist
        results = sp.search(q=seed_name, type='artist', limit=1)
        if not results['artists']['items']:
            print("Artist not found.")
            return []
            
        artist = results['artists']['items'][0]
        artist_id = artist['id']
        print(f"Found Artist: {artist['name']}")
        
        # 2. Get Related Artists
        print("Fetching related artists...")
        related = sp.artist_related_artists(artist_id)['artists']
        # Add seed artist to pool
        related.insert(0, artist)
        
        # 3. Get Top Tracks
        print(f"Fetching top tracks from {len(related)} artists...")
        pool = []
        for art in related[:20]: # Limit to top 20 related to save time
            top = sp.artist_top_tracks(art['id'])['tracks']
            pool.extend(top)
            
        # 4. Sample
        if len(pool) > limit:
            print(f"Pool size {len(pool)}. Sampling {limit} tracks...")
            pool = random.sample(pool, limit)
            
        return pool
        
    except Exception as e:
        print(f"Error fetching recommendations: {e}")
        return []

def get_gsbpm_features(artist, title, api_key):
    """Fetches features from GetSongBPM API."""
    url = "https://api.getsong.co/search/"
    params = {"api_key": api_key, "type": "both", "lookup": f"song:{title} artist:{artist}"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if isinstance(data, dict) and 'search' in data and data['search']:
            res = data['search'][0]
            if not res.get('key_of') or not res.get('tempo'): return None
            
            # Proxy Energy from Danceability
            dance = res.get('danceability')
            energy = float(dance) if dance is not None else 0.5
            
            return {
                'key': int(res['key_of']), # Assuming safe int string
                'mode': int(res.get('mode', 1)),
                'tempo': float(res['tempo']),
                'energy': energy,
                'BPM': float(res['tempo'])
            }
        return None
    except:
        return None

def process_songs_gsbpm(tracks, api_key):
    """Annotate tracks with GetSongBPM features."""
    if not tracks: return []
    print(f"\nProcessing {len(tracks)} tracks with GetSongBPM (approx {len(tracks)*1.1:.0f}s)...")
    
    out = []
    for i, t in enumerate(tracks):
        artist = t['artists'][0]['name']
        title = t['name']
        print(f"[{i+1}/{len(tracks)}] {title} - {artist}")
        
        feat = get_gsbpm_features(artist, title, api_key)
        if feat:
            out.append({
                'id': t['id'], 'name': title, 'artist': artist, 
                'album': t['album']['name'], 'uri': t['uri'], 
                'duration_ms': t['duration_ms'], **feat
            })
        time.sleep(1.0) # Rate limit
    return out

def main():
    sp, user_auth = get_spotify_client()
    if not sp: return

    gsbpm_key = os.environ.get("GETSONGBPM_API_KEY")
    if not gsbpm_key:
        gsbpm_key = input("Enter GetSongBPM API Key: ").strip()
        os.environ["GETSONGBPM_API_KEY"] = gsbpm_key

    print("\nSelect Source:")
    print("[1] Existing Playlist")
    print("[2] Recommendations (Artist-Based)")
    src = input("Choice: ").strip()
    
    if src == '2':
        tracks = get_recommendations_artist_based(sp)
    else:
        tracks = get_playlist_tracks(sp)
        
    songs = process_songs_gsbpm(tracks, gsbpm_key)
    if not songs: return

    # Solver
    try:
        mix_min = float(input("\nTarget mix length (mins) [default 45]: ").strip() or 45)
    except: mix_min = 45
    
    print(f"\nSolving mix for {len(songs)} songs...")
    # Default weights
    sol = solver(
        songs_lst=songs,
        key_fn_dict={'key_pen':1,0:6,1:3,2:1,3:0,4:0,5:0,6:0},
        modal_pen=2, tempo_wt=0.1, energy_wt=2.0, target_energy_diff=0.05,
        threshold=int(mix_min*60000)
    )
    res = sol.solve()
    
    if res:
        ids = res['song_ids']
        print(f"\nOptimal Mix Found: {len(ids)} songs.")
        
        if user_auth:
            try:
                uid = sp.current_user()['id']
                pl = sp.user_playlist_create(uid, "Continuum Mix", public=True, description="Generated via Continuum")
                for i in range(0, len(ids), 100):
                    sp.playlist_add_items(pl['id'], ids[i:i+100])
                print(f"Playlist Created: {pl['external_urls']['spotify']}")
            except Exception as e:
                print(f"Error creating playlist: {e}")
        else:
            print("\n--- Read-Only Mode: Exporting Mix ---")
            fname = "mix.txt"
            with open(fname, "w") as f:
                for sid in ids:
                    s = next(s for s in songs if s['id'] == sid)
                    f.write(f"{s['artist']} - {s['name']}\n")
            print(f"Saved to '{fname}'.")
            print("Upload this file to TuneMyMusic.com or Soundiiz to create your playlist.")
            
    else:
        print("No solution found.")

if __name__ == "__main__":
    main()
