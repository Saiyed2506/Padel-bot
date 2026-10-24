"""
Padel court watcher for padel amigos Hamburg-Halstenbek (Playtomic).
Checks free slots for your wanted days/times and sends a Telegram alert.

Setup:
  pip install requests
  Set environment variables TG_TOKEN and TG_CHAT_ID (see instructions).
  Run once:      python padel_watcher.py
  Run forever:   python padel_watcher.py --loop
"""
import os, sys, json, time, datetime as dt
from zoneinfo import ZoneInfo
import requests

# ================== YOUR SETTINGS ==================
CLUB_NAME   = "padel amigos Hamburg-Halstenbek"
CLUB_LAT, CLUB_LON = 53.633, 9.842        # Am Bahndamm 88, Halstenbek
TENANT_ID   = ""        # leave empty -> found automatically

# Wanted slots: weekday (0=Mon ... 6=Sun) -> list of (earliest, latest) start times
WANTED = {
    1: [("18:00", "21:00")],   # Tuesday 18:00-21:00
    3: [("18:00", "21:00")],   # Thursday
    5: [("09:00", "13:00")],   # Saturday
}
DURATIONS   = [90, 60]          # acceptable lengths in minutes
COURT_WORDS = ["Indoor"]        # only courts whose name contains one of these ([] = all)
DAYS_AHEAD  = 7                 # how far ahead to check
CHECK_EVERY = 300               # seconds between checks in --loop mode
SLOT_TIMES_ARE_UTC = True       # Playtomic usually returns UTC; set False if alerts look shifted
# ===================================================

API = "https://api.playtomic.io/v1"
TZ = ZoneInfo("Europe/Berlin")
SEEN_FILE = "seen_slots.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal court alert)"}


def find_tenant():
    r = requests.get(f"{API}/tenants", headers=HEADERS, params={
        "sport_id": "PADEL",
        "coordinate": f"{CLUB_LAT},{CLUB_LON}",
        "radius": 3000, "size": 50}, timeout=20)
    r.raise_for_status()
    for t in r.json():
        if "halstenbek" in t.get("tenant_name", "").lower():
            print(f"Found club: {t['tenant_name']}  tenant_id={t['tenant_id']}")
            return t["tenant_id"]
    sys.exit("Club not found - paste TENANT_ID manually (see instructions).")


def court_names(tenant_id):
    r = requests.get(f"{API}/tenants/{tenant_id}", headers=HEADERS, timeout=20)
    r.raise_for_status()
    return {c["resource_id"]: c.get("name", "Court") for c in r.json().get("resources", [])}


def availability(tenant_id, day):
    r = requests.get(f"{API}/availability", headers=HEADERS, params={
        "sport_id": "PADEL", "tenant_id": tenant_id,
        "start_min": f"{day}T00:00:00", "start_max": f"{day}T23:59:59"}, timeout=20)
    r.raise_for_status()
    return r.json()


def to_local(date_str, time_str):
    t = dt.datetime.fromisoformat(f"{date_str}T{time_str}")
    if SLOT_TIMES_ARE_UTC:
        t = t.replace(tzinfo=dt.timezone.utc).astimezone(TZ)
    else:
        t = t.replace(tzinfo=TZ)
    return t


def wanted(t, duration):
    if duration not in DURATIONS:
        return False
    hhmm = t.strftime("%H:%M")
    return any(a <= hhmm <= b for a, b in WANTED.get(t.weekday(), []))


def telegram(text):
    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        print("[no Telegram set]\n" + text)
        return
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  data={"chat_id": chat, "text": text}, timeout=20)


def load_seen():
    try:
        return set(json.load(open(SEEN_FILE)))
    except Exception:
        return set()


def check_once(tenant_id, names):
    seen, hits = load_seen(), []
    today = dt.date.today()
    for i in range(DAYS_AHEAD):
        day = today + dt.timedelta(days=i)
        if day.weekday() not in WANTED:
            continue
        for court in availability(tenant_id, day.isoformat()):
            name = names.get(court["resource_id"], "Court")
            if COURT_WORDS and not any(w.lower() in name.lower() for w in COURT_WORDS):
                continue
            for s in court.get("slots", []):
                t = to_local(court["start_date"], s["start_time"])
                if wanted(t, s["duration"]):
                    key = f"{court['resource_id']}|{t.isoformat()}|{s['duration']}"
                    if key not in seen:
                        seen.add(key)
                        hits.append(f"🎾 {t:%a %d.%m %H:%M} · {s['duration']} min · "
                                    f"{name} · {s.get('price', '')}")
    if hits:
        telegram("Free court at Padel Amigos!\n\n" + "\n".join(hits) +
                 "\n\nBook fast: https://playtomic.com/de/clubs/padel-amigos-hamburg-halstenbek")
    json.dump(sorted(seen)[-500:], open(SEEN_FILE, "w"))
    print(f"{dt.datetime.now(TZ):%H:%M} checked - {len(hits)} new slot(s)")


if __name__ == "__main__":
    tid = TENANT_ID or find_tenant()
    names = court_names(tid)
    if "--loop" in sys.argv:
        while True:
            try:
                check_once(tid, names)
            except Exception as e:
                print("Error:", e)
            time.sleep(CHECK_EVERY)
    else:
        check_once(tid, names)
