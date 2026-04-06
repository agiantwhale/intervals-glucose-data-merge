import os
import requests
from datetime import datetime, timedelta

# Config (Use your GitHub Secrets or environment variables)
ATHLETE_ID = os.environ.get('INTERVALS_ID', '0') # '0' auto-resolves your ID
API_KEY = os.environ.get('INTERVALS_API_KEY')
AUTH = ('API_KEY', API_KEY)

def get_recent_activities():
    # 1. Handle the 24-hour window (API uses YYYY-MM-DD)
    now = datetime.now()
    yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    today_str = now.strftime('%Y-%m-%d')
    
    url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
    params = {'oldest': yesterday_str, 'newest': today_str}
    
    response = requests.get(url, auth=AUTH, params=params)
    response.raise_for_status()
    activities = response.json()
    
    # 2. Filter for actual last 24 hours (precise timestamp)
    cutoff = now - timedelta(hours=24)
    recent = [a for a in activities if datetime.fromisoformat(a['start_date_local'].replace('Z', '')) > cutoff]
    return recent

def has_glucose_data(activity_id):
    # 3. Check for the specific 'blood_glucose' stream
    # Requesting ONLY the blood_glucose type keeps the response tiny
    url = f"https://intervals.icu/api/v1/activity/{activity_id}/streams.json"
    params = {'types': 'blood_glucose'}
    
    response = requests.get(url, auth=AUTH, params=params)
    streams = response.json()
    
    # Returns True if the stream exists and has data points
    return any(s['type'] == 'blood_glucose' and len(s['data']) > 0 for s in streams)

# --- Execution ---
if __name__ == "__main__":
    runs = get_recent_activities()
    print(f"Found {len(runs)} activities in the last 24 hours.")
    
    for activity in runs:
        activity_id = activity['id']
        name = activity['name']
        
        if has_glucose_data(activity_id):
            print(f"✅ {name} ({activity_id}) already has glucose data.")
        else:
            print(f"❌ {name} ({activity_id}) is missing glucose data. Ready for sync!")
