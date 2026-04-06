import os
import requests
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# Use '0' to auto-resolve your athlete ID from the API Key
ATHLETE_ID = os.environ.get('INTERVALS_ID', '0')
API_KEY = os.environ.get('INTERVALS_API_KEY')
NS_URL = os.environ.get('NS_URL').rstrip('/')
NS_TOKEN = os.environ.get('NS_TOKEN')
AUTH = ('API_KEY', API_KEY)

def get_recent_activities():
    """Fetch activities from the last 24 hours."""
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    
    url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
    params = {'oldest': yesterday}
    r = requests.get(url, auth=AUTH, params=params)
    r.raise_for_status()
    
    # Filter for exact 24h window based on start_date_local
    cutoff = now - timedelta(hours=24)
    return [a for a in r.json() if datetime.fromisoformat(a['start_date_local'].replace('Z', '')) > cutoff]

def stream_exists(activity_id):
    """Check if the blood_glucose stream is already present."""
    url = f"https://intervals.icu/api/v1/activity/{activity_id}/streams.json"
    r = requests.get(url, auth=AUTH, params={'types': 'blood_glucose'})
    # If the list is not empty, the stream exists
    return any(s['type'] == 'blood_glucose' for s in r.json())

def fetch_nightscout_glucose(start_iso, duration_secs):
    """Fetch SGV entries from Nightscout for the activity duration."""
    start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
    end_dt = start_dt + timedelta(seconds=duration_secs)
    
    endpoint = f"{NS_URL}/api/v1/entries/sgv.json"
    params = {
        "find[date][$gte]": int(start_dt.timestamp() * 1000),
        "find[date][$lte]": int(end_dt.timestamp() * 1000),
        "count": 1000,
        "token": NS_TOKEN
    }
    r = requests.get(endpoint, params=params)
    r.raise_for_status()
    
    # Convert to offsets in seconds from activity start
    data, seconds = [], []
    for entry in reversed(r.json()): # NS returns newest first
        ts = entry['date'] / 1000.0
        offset = int(ts - start_dt.timestamp())
        if 0 <= offset <= duration_secs:
            data.append(entry['sgv'])
            seconds.append(offset)
    return data, seconds

def upload_glucose_stream(activity_id, data, seconds):
    """Push the custom stream to Intervals.icu."""
    url = f"https://intervals.icu/api/v1/activity/{activity_id}/streams"
    payload = [{
        "type": "blood_glucose",
        "data": data,
        "seconds": seconds
    }]
    r = requests.put(url, json=payload, auth=AUTH)
    r.raise_for_status()

if __name__ == "__main__":
    activities = get_recent_activities()
    print(f"Checking {len(activities)} recent activities...")

    for activity in activities:
        a_id = activity['id']
        if stream_exists(a_id):
            print(f" - Activity {a_id}: Glucose already exists. Skipping.")
            continue
        
        print(f" - Activity {a_id}: Missing glucose. Syncing...")
        vals, secs = fetch_nightscout_glucose(activity['start_date'], activity['elapsed_time'])
        
        if vals:
            upload_glucose_stream(a_id, vals, secs)
            print(f"   Done! Injected {len(vals)} data points.")
        else:
            print("   No data found in Nightscout for this window.")
