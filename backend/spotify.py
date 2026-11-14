"""Calm playlists for each dashboard mood color, from the Spotify Web API.

Uses the Client Credentials flow: an app key only, no user Spotify login, so it can only
search public playlists (which is all we need). Results are cached for an hour per mood.

Setup: create an app at https://developer.spotify.com/dashboard and put
SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in backend/.env. Without them the music card
still works, with links that open a Spotify search instead of embedded playlists.
"""
import base64
import json
import logging
import os
import time
import urllib.parse
import urllib.request

log = logging.getLogger('attunemind.spotify')

# What to search for, per mood color. Aimed at calming or gently matching the feeling.
MOOD_QUERIES = {
    'Yellow': 'happy acoustic morning',
    'Green': 'calm acoustic chill',
    'Blue': 'comforting gentle piano',
    'Red': 'calming meditation breathing',
    'Purple': 'dreamy ambient focus',
}

_token = {'value': None, 'expires': 0.0}
_cache = {}            # mood -> (time fetched, playlists)
CACHE_SECONDS = 3600


def configured():
    return bool(os.getenv('SPOTIFY_CLIENT_ID') and os.getenv('SPOTIFY_CLIENT_SECRET'))


def search_url(mood):
    """A Spotify search link that works without any API key."""
    return 'https://open.spotify.com/search/' + urllib.parse.quote(MOOD_QUERIES[mood])


def _get_token():
    if _token['value'] and time.time() < _token['expires'] - 60:
        return _token['value']
    creds = f"{os.getenv('SPOTIFY_CLIENT_ID')}:{os.getenv('SPOTIFY_CLIENT_SECRET')}".encode()
    req = urllib.request.Request(
        'https://accounts.spotify.com/api/token',
        data=urllib.parse.urlencode({'grant_type': 'client_credentials'}).encode(),
        headers={'Authorization': 'Basic ' + base64.b64encode(creds).decode(),
                 'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.load(res)
    _token.update(value=data['access_token'], expires=time.time() + data.get('expires_in', 3600))
    return _token['value']


def _search(query, limit=6):
    url = 'https://api.spotify.com/v1/search?' + urllib.parse.urlencode(
        {'q': query, 'type': 'playlist', 'limit': limit, 'market': 'US'})
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + _get_token()})
    with urllib.request.urlopen(req, timeout=10) as res:
        items = json.load(res).get('playlists', {}).get('items') or []
    playlists = []
    for p in items:
        if not p or not p.get('id'):          # Spotify sometimes returns null entries
            continue
        images = p.get('images') or []
        playlists.append({
            'id': p['id'],
            'name': p.get('name') or 'Playlist',
            'owner': (p.get('owner') or {}).get('display_name') or '',
            'image': images[0]['url'] if images else None,
            'url': (p.get('external_urls') or {}).get('spotify') or f"https://open.spotify.com/playlist/{p['id']}",
            'embed_url': f"https://open.spotify.com/embed/playlist/{p['id']}",
        })
    return playlists


def playlists_for(mood):
    """Playlists for a mood color. Raises RuntimeError if Spotify isn't set up or fails."""
    if not configured():
        raise RuntimeError('Spotify is not set up.')
    cached = _cache.get(mood)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        playlists = _search(MOOD_QUERIES[mood])
    except Exception as e:                    # network error, bad key, rate limit...
        log.warning('Spotify search failed: %s', e)
        raise RuntimeError('Spotify is not responding right now.') from e
    _cache[mood] = (time.time(), playlists)
    return playlists
