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
    """Fetch activities from the last 3 days."""
    now = datetime.now()
    three_days_ago = (now - timedelta(days=3)).strftime('%Y-%m-%d')
    
    url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
    params = {'oldest': three_days_ago}
    r = requests.get(url, auth=AUTH, params=params)
    r.raise_for_status()
    
    # Filter for exact 3-day window based on start_date_local
    cutoff = now - timedelta(days=3)
    return [a for a in r.json() if datetime.fromisoformat(a['start_date_local'].replace('Z', '')) > cutoff]

def stream_exists(activity):
    """Check if the bloodglucose stream is already present."""
    return 'bloodglucose' in activity.get('stream_types', [])

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
    
    if seconds and seconds[0] > 0:
        seconds.insert(0, 0)
        data.insert(0, data[0])
        
    return data, seconds

def linear_interpolate(time_stream, seconds, data):
    """Simple linear interpolation for matching data to the time stream."""
    import bisect
    res = []
    for t in time_stream:
        # Find the index of the first element in seconds >= t
        idx = bisect.bisect_left(seconds, t)
        if idx == 0:
            res.append(data[0])
        elif idx == len(seconds):
            res.append(data[-1])
        else:
            # Interpolate between seconds[idx-1] and seconds[idx]
            t0, t1 = seconds[idx-1], seconds[idx]
            v0, v1 = data[idx-1], data[idx]
            weight = (t - t0) / (t1 - t0)
            res.append(v0 + weight * (v1 - v0))
    return res

def upload_glucose_stream(activity_id, data, seconds):
    """Push the custom stream to Intervals.icu."""
    # Fetch existing time stream to get the correct length and sampling
    url_get = f"https://intervals.icu/api/v1/activity/{activity_id}/streams.json"
    r_get = requests.get(url_get, auth=AUTH)
    r_get.raise_for_status()
    streams = r_get.json()
    
    # If the response is not a list (e.g. error dict), something is wrong
    if not isinstance(streams, list):
        print(f"   Could not retrieve streams for activity {activity_id}: {streams}")
        return None

    time_stream = next((s['data'] for s in streams if s['type'] == 'time'), None)
    if not time_stream:
        print(f"   Could not find time stream for activity {activity_id}")
        return None

    # Interpolate data to match the activity's time stream
    interpolated_glucose = linear_interpolate(time_stream, seconds, data)
    
    url_put = f"https://intervals.icu/api/v1/activity/{activity_id}/streams"
    payload = [{
        "type": "bloodglucose",
        "data": interpolated_glucose
    }]
    r = requests.put(url_put, json=payload, auth=AUTH)
    r.raise_for_status()
    return len(interpolated_glucose)

if __name__ == "__main__":
    activities = get_recent_activities()
    print(f"Checking {len(activities)} recent activities...")

    for activity in activities:
        a_id = activity['id']
        if stream_exists(activity):
            print(f" - Activity {a_id}: Glucose already exists. Skipping.")
            continue
        
        print(f" - Activity {a_id}: Missing glucose. Syncing...")
        vals, secs = fetch_nightscout_glucose(activity['start_date'], activity['elapsed_time'])
        
        if vals:
            count = upload_glucose_stream(a_id, vals, secs)
            if count:
                print(f"   Done! Injected {count} data points.")
        else:
            print("   No data found in Nightscout for this window.")
