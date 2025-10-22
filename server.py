# server.py
"""
Server for Chrome profile management with human-like, anti-ban refresh behavior.
- Pure simulation mode (no GUI automation) suitable for large fleets (500-1000 profiles).
- 3 rotation groups (only one group refreshed per cycle).
- Dynamic minute-based scheduling (center ~32 minutes, jitter ±8 minutes).
- Per-profile backoff and quarantine.
- Endpoints: auth, profiles, launch, launch_all, start_refresh, stop_refresh,
  safe_refresh, logs, quarantine list/reset, add_proxies (stub), change_password, close_all,
  dashboard summary.
- On-disk JSON persistence of rotation/profile state and proxies.
"""

import os
import json
import time
import threading
import secrets
import base64
import hashlib
import hmac
import subprocess
import platform
import random
from functools import wraps
from math import ceil
import atexit
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------- CONFIG ---------------- #
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILENAME = os.path.join(SCRIPT_DIR, "server_state.json")
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
TARGET_URL = "https://m.poppolive.com/live/room/?l=&roomid=26343308"
CONFIG_FILENAME = "zoee_profile_manager_config.json"
PBKDF2_ITERATIONS = 200_000
TOKEN_TTL = 60 * 60 * 24  # tokens valid 24h
DEFAULT_PASSWORD = "1234"

opened_profiles = set()
profile_proxies = {}
_activity_log = []
_valid_tokens = {}

# Rotation and safety tuned for large fleets (500-1000)
HUMAN_BEHAVIOR_LEVEL = "medium"  # "low", "medium" (no GUI), "high" not used here

SAFETY = {
    "base_cycle_minutes": 32,
    "max_profiles_per_cycle": 1000,
    "min_delay_seconds": 60,
    "jitter_seconds": 480,  # ±8 minutes
    "interaction_chance_pct": 30,
    "long_break_chance_pct": 8,
    "failure_quarantine_threshold": 3,
    "failure_backoff_base": 60 * 2,
    "max_concurrent_refreshes": 6,
    "active_hours_start": 8,
    "active_hours_end": 23,
    "rotation_groups": 3,
    "max_log_items": 2000,
    "state_autosave_interval": 60,  # seconds
}

# Lock for shared state
_state_lock = threading.Lock()

# ---------------- Utilities ---------------- #
def config_path():
    return os.path.join(SCRIPT_DIR, CONFIG_FILENAME)

def _log_trim():
    if len(_activity_log) > SAFETY["max_log_items"]:
        del _activity_log[0 : len(_activity_log) - SAFETY["max_log_items"]]

def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with _state_lock:
        _activity_log.append(line)
        _log_trim()
    print(line)

# ---------------- Persistence (JSON) ---------------- #
def _load_state():
    global _rotation_state, _profile_state, profile_proxies
    if not os.path.exists(STATE_FILENAME):
        log("No saved state file found; starting fresh.")
        return
    try:
        with open(STATE_FILENAME, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _state_lock:
            _rotation_state.update(data.get("rotation_state", {}))
            # load profile state values, ensure numeric types where needed
            saved_profiles = data.get("profile_state", {})
            for k, v in saved_profiles.items():
                _profile_state[k] = {
                    "last_refresh": float(v.get("last_refresh", 0)),
                    "failures": int(v.get("failures", 0)),
                    "next_allowed": float(v.get("next_allowed", 0)),
                    "quarantined": bool(v.get("quarantined", False)),
                }
            profile_proxies.update(data.get("profile_proxies", {}))
        log("Loaded persisted state from disk.")
    except Exception as e:
        log(f"Failed to load persisted state: {e}")

def _save_state():
    try:
        with _state_lock:
            data = {
                "rotation_state": _rotation_state,
                "profile_state": _profile_state,
                "profile_proxies": profile_proxies,
                "ts": time.time(),
            }
        with open(STATE_FILENAME, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log("Saved state to disk.")
    except Exception as e:
        log(f"Failed to save state: {e}")

# Autosave background thread
_autosave_stop = threading.Event()
def _autosave_worker():
    while not _autosave_stop.is_set():
        time.sleep(SAFETY.get("state_autosave_interval", 60))
        try:
            _save_state()
        except Exception:
            pass

_autosave_thread = threading.Thread(target=_autosave_worker, daemon=True)

def _start_autosave():
    if not _autosave_thread.is_alive():
        _autosave_thread.start()

def _stop_autosave():
    _autosave_stop.set()
    try:
        _autosave_thread.join(timeout=2)
    except Exception:
        pass

# Ensure save on exit
def _on_exit_save():
    log("Shutdown: saving state to disk...")
    _save_state()
    _stop_autosave()

atexit.register(_on_exit_save)

# ---------------- Password utilities ---------------- #
def save_password_hash(salt: bytes, dk: bytes, iterations=PBKDF2_ITERATIONS):
    entry = {
        "salt": base64.b64encode(salt).decode("utf-8"),
        "dk": base64.b64encode(dk).decode("utf-8"),
        "iterations": iterations,
    }
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(entry, f)

def load_password_hash():
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            entry = json.load(f)
        return (
            base64.b64decode(entry["salt"]),
            base64.b64decode(entry["dk"]),
            int(entry.get("iterations", PBKDF2_ITERATIONS)),
        )
    except Exception:
        return None

def derive_key(password: str, salt: bytes, iterations=PBKDF2_ITERATIONS):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, dklen=32)

def ensure_password_exists():
    if not load_password_hash():
        salt = secrets.token_bytes(16)
        dk = derive_key(DEFAULT_PASSWORD, salt)
        save_password_hash(salt, dk)
        log("Default password created (first run).")

def verify_password(password: str) -> bool:
    loaded = load_password_hash()
    if not loaded:
        return False
    salt, dk_saved, iterations = loaded
    dk_try = derive_key(password, salt, iterations)
    return hmac.compare_digest(dk_try, dk_saved)

def set_new_password(new_password: str):
    salt = secrets.token_bytes(16)
    dk = derive_key(new_password, salt)
    save_password_hash(salt, dk)
    log("Password updated via API.")

# ---------------- Token middleware ---------------- #
def generate_token():
    return secrets.token_hex(24)

def extract_token():
    token = request.headers.get("X-Auth-Token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    return token

def require_token(f):
    @wraps(f)
    def inner(*args, **kwargs):
        token = extract_token()
        if not token:
            log(f"Unauthorized: missing token on {request.path}")
            return jsonify(ok=False, error="auth token required"), 401
        expiry = _valid_tokens.get(token)
        if not expiry or expiry < time.time():
            log(f"Unauthorized: invalid/expired token on {request.path}")
            return jsonify(ok=False, error="invalid or expired token"), 401
        return f(*args, **kwargs)
    return inner

# ---------------- Chrome profile handling ---------------- #
def get_logged_in_profiles():
    profiles = []
    try:
        local_state = os.path.join(USER_DATA_DIR, "Local State")
        with open(local_state, "r", encoding="utf-8") as f:
            state = json.load(f)
        info_cache = state.get("profile", {}).get("info_cache", {})
    except Exception:
        info_cache = {}

    try:
        for folder in os.listdir(USER_DATA_DIR):
            if folder == "Default" or folder.startswith("Profile "):
                p_path = os.path.join(USER_DATA_DIR, folder)
                if os.path.exists(os.path.join(p_path, "Bookmarks")):
                    email = info_cache.get(folder, {}).get("user_name", "Unknown")
                    profiles.append({"profile": folder, "email": email})
    except Exception as e:
        log(f"Error scanning profiles: {e}")
    return sorted(profiles, key=lambda x: x["profile"])

def launch_profile(profile, email=None):
    if profile in opened_profiles:
        log(f"Profile already launched: {profile}")
        return
    options = [f"--profile-directory={profile}", "--autoplay-policy=no-user-gesture-required"]
    proxy = profile_proxies.get(profile)
    if proxy:
        options.append(f"--proxy-server={proxy}")
    try:
        subprocess.Popen([CHROME_PATH] + options + [TARGET_URL])
        opened_profiles.add(profile)
        log(f"Launched {profile} ({email})")
    except Exception as e:
        log(f"Failed to launch {profile}: {e}")
        raise

def close_all_profiles():
    if platform.system() == "Windows":
        try:
            subprocess.call("taskkill /F /IM chrome.exe", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    opened_profiles.clear()
    log("Closed all Chrome profiles")

# ---------------- Per-profile state (safety) ---------------- #
_profile_state = {}

def _ensure_profile_state(profile_name):
    if profile_name not in _profile_state:
        _profile_state[profile_name] = {"last_refresh": 0, "failures": 0, "next_allowed": 0, "quarantined": False}
    return _profile_state[profile_name]

def _mark_success(profile_name):
    st = _ensure_profile_state(profile_name)
    st["last_refresh"] = time.time()
    st["failures"] = 0
    st["next_allowed"] = time.time()
    st["quarantined"] = False

def _mark_failure(profile_name):
    st = _ensure_profile_state(profile_name)
    st["failures"] = st.get("failures", 0) + 1
    backoff = SAFETY["failure_backoff_base"] * (2 ** (st["failures"] - 1))
    backoff = min(backoff, 60 * 60 * 24)
    st["next_allowed"] = time.time() + backoff
    if st["failures"] >= SAFETY["failure_quarantine_threshold"]:
        st["quarantined"] = True
        log(f"[SAFETY] Quarantined profile {profile_name} after {st['failures']} failures (backoff {backoff}s).")

def _is_allowed_to_refresh(profile_name):
    st = _ensure_profile_state(profile_name)
    if st.get("quarantined"):
        return False, "quarantined"
    if st.get("next_allowed", 0) > time.time():
        return False, "backoff"
    return True, None

# ---------------- Human-like scheduling helpers ---------------- #
def _now_hour():
    return time.localtime().tm_hour

def _is_within_active_hours():
    start = SAFETY["active_hours_start"]
    end = SAFETY["active_hours_end"]
    h = _now_hour()
    if start <= end:
        return start <= h < end
    return h >= start or h < end

def _compute_delay_per_profile(total_profiles):
    if total_profiles <= 0:
        return SAFETY["min_delay_seconds"]
    base = max(SAFETY["min_delay_seconds"], (SAFETY["base_cycle_minutes"] * 60) // total_profiles)
    jitter = secrets.randbelow(SAFETY["jitter_seconds"] * 2 + 1) - SAFETY["jitter_seconds"]
    delay = max(SAFETY["min_delay_seconds"], base + jitter)
    if not _is_within_active_hours():
        delay = int(delay * 1.5)
    return delay

def _should_do_interaction():
    return secrets.randbelow(100) < SAFETY["interaction_chance_pct"]

def _should_take_long_break():
    return secrets.randbelow(100) < SAFETY["long_break_chance_pct"]

def _perform_human_like_interaction_simulated(profile_name):
    action = random.choice(["small_scroll", "hover", "pause"])
    log(f"[SIMULATED INTERACTION] {profile_name}: {action}")

# ---------------- Rotation state ---------------- #
_rotation_state = {
    "groups": SAFETY["rotation_groups"],
    "last_group": -1,
    "last_cycle_ts": 0,
}

def _compute_rotation_groups(profiles):
    n = max(1, _rotation_state["groups"])
    total = len(profiles)
    if total == 0:
        return [[] for _ in range(n)]
    chunk = ceil(total / n)
    groups = [profiles[i * chunk:(i + 1) * chunk] for i in range(n)]
    while len(groups) < n:
        groups.append([])
    return groups

def _next_rotation_group_index():
    with _state_lock:
        _rotation_state["last_group"] = (_rotation_state["last_group"] + 1) % _rotation_state["groups"]
        _rotation_state["last_cycle_ts"] = time.time()
        return _rotation_state["last_group"]

# ---------------- Background refresh (rotation + simulation) ---------------- #
_stop_event = threading.Event()
_refresh_thread = None

def _refresh_worker():
    log("Background refresh worker started (rotation mode).")
    while not _stop_event.is_set():
        try:
            profiles = get_logged_in_profiles()
            if not profiles:
                log("No profiles found to refresh.")
                time.sleep(10)
                continue

            groups = _compute_rotation_groups(profiles)
            group_index = _next_rotation_group_index()
            active_group = groups[group_index] if group_index < len(groups) else []
            log(f"[ROTATION] Starting cycle for Group {group_index + 1} of {len(groups)} (profiles in group: {len(active_group)})")

            total_in_group = min(len(active_group), SAFETY["max_profiles_per_cycle"])
            delay_per_profile = _compute_delay_per_profile(total_in_group if total_in_group > 0 else 1)

            refreshed = 0
            for i, p in enumerate(active_group[:SAFETY["max_profiles_per_cycle"]]):
                if _stop_event.is_set():
                    break
                profile_name = p["profile"]
                email = p.get("email", "Unknown")

                allowed, reason = _is_allowed_to_refresh(profile_name)
                if not allowed:
                    log(f"[ROTATION] Skipping {profile_name}: {reason}")
                    continue

                if _should_take_long_break():
                    extra = secrets.randbelow(60 * 30)
                    _ensure_profile_state(profile_name)["next_allowed"] = time.time() + extra
                    log(f"[ROTATION] Taking occasional long break for {profile_name} (+{extra}s)")
                    continue

                try:
                    log(f"[ROTATION] Refreshing (simulated) {profile_name} ({email})")
                    if _should_do_interaction():
                        _perform_human_like_interaction_simulated(profile_name)
                    _mark_success(profile_name)
                    refreshed += 1
                except Exception as e:
                    log(f"[ROTATION] Error refreshing {profile_name}: {e}")
                    _mark_failure(profile_name)

                time.sleep(delay_per_profile)

            log(f"[ROTATION] Completed cycle for Group {group_index + 1}. Refreshed: {refreshed}")
            # small buffer before next rotation
            time.sleep(5)
        except Exception as e:
            log(f"Refresh loop error: {e}")
            time.sleep(10)
    log("Background refresh worker stopped.")

def start_refresh():
    global _refresh_thread
    if _refresh_thread and _refresh_thread.is_alive():
        log("Auto-refresh already running.")
        return
    _stop_event.clear()
    _refresh_thread = threading.Thread(target=_refresh_worker, daemon=True)
    _refresh_thread.start()
    _start_autosave()
    log("Started auto-refresh thread and autosave.")

def stop_refresh():
    global _refresh_thread
    if _refresh_thread:
        _stop_event.set()
        _refresh_thread.join(timeout=5)
        _refresh_thread = None
        log("Stopped auto-refresh thread.")

# ---------------- Safe Refresh (single-cycle over one rotation group) ---------------- #
def _safe_refresh_cycle_once():
    profiles = get_logged_in_profiles()
    if not profiles:
        log("Safe refresh: no profiles found.")
        return 0
    groups = _compute_rotation_groups(profiles)
    with _state_lock:
        next_idx = (_rotation_state["last_group"] + 1) % _rotation_state["groups"]
    active_group = groups[next_idx] if next_idx < len(groups) else []
    log(f"[SAFE_REFRESH] Performing safe refresh for Group {next_idx + 1} of {len(groups)} (size {len(active_group)})")
    total_in_group = min(len(active_group), SAFETY["max_profiles_per_cycle"])
    delay_per_profile = _compute_delay_per_profile(total_in_group if total_in_group > 0 else 1)
    refreshed = 0
    for p in active_group[:SAFETY["max_profiles_per_cycle"]]:
        profile_name = p["profile"]
        email = p.get("email", "Unknown")
        allowed, reason = _is_allowed_to_refresh(profile_name)
        if not allowed:
            log(f"[SAFE_REFRESH] Skipping {profile_name}: {reason}")
            continue
        if _should_take_long_break():
            extra = secrets.randbelow(60 * 30)
            _ensure_profile_state(profile_name)["next_allowed"] = time.time() + extra
            log(f"[SAFE_REFRESH] Taking occasional long break for {profile_name} (+{extra}s)")
            continue
        try:
            log(f"[SAFE_REFRESH] Simulated refresh for {profile_name} ({email})")
            if _should_do_interaction():
                _perform_human_like_interaction_simulated(profile_name)
            _mark_success(profile_name)
            refreshed += 1
        except Exception as e:
            log(f"[SAFE_REFRESH] Error refreshing {profile_name}: {e}")
            _mark_failure(profile_name)
        time.sleep(delay_per_profile)
    log(f"[SAFE_REFRESH] Completed; refreshed {refreshed}")
    return refreshed

# ---------------- Flask endpoints ---------------- #
@app.before_request
def debug_request():
    try:
        print(f"[REQ] {request.method} {request.path}")
    except Exception:
        pass

@app.route("/auth/login", methods=["POST"])
def auth_login():
    ensure_password_exists()
    data = request.get_json() or {}
    pw = data.get("password", "")
    if not pw:
        return jsonify(ok=False, error="password required"), 400
    if verify_password(pw):
        token = generate_token()
        _valid_tokens[token] = time.time() + TOKEN_TTL
        log("User logged in (token issued)")
        return jsonify(ok=True, token=token)
    return jsonify(ok=False, error="invalid password"), 403

@app.route("/profiles", methods=["GET"])
@require_token
def api_profiles():
    profs = get_logged_in_profiles()
    return jsonify(ok=True, profiles=profs)

@app.route("/logs", methods=["GET"])
@require_token
def api_logs():
    with _state_lock:
        return jsonify(ok=True, logs=list(_activity_log))

@app.route("/launch", methods=["POST"])
@require_token
def api_launch():
    data = request.get_json() or {}
    profile = data.get("profile")
    email = data.get("email")
    if not profile:
        return jsonify(ok=False, error="profile required"), 400
    launch_profile(profile, email)
    return jsonify(ok=True)

@app.route("/launch_all", methods=["POST"])
@require_token
def api_launch_all():
    for p in get_logged_in_profiles():
        try:
            launch_profile(p["profile"], p.get("email"))
            time.sleep(0.2)
        except Exception as e:
            log(f"Error launching {p['profile']}: {e}")
    return jsonify(ok=True)

@app.route("/start_refresh", methods=["POST"])
@require_token
def api_start_refresh():
    start_refresh()
    return jsonify(ok=True)

@app.route("/stop_refresh", methods=["POST"])
@require_token
def api_stop_refresh():
    stop_refresh()
    return jsonify(ok=True)

@app.route("/close_all", methods=["POST"])
@require_token
def api_close_all():
    close_all_profiles()
    return jsonify(ok=True)

@app.route("/safe_refresh", methods=["POST"])
@require_token
def api_safe_refresh():
    try:
        refreshed = _safe_refresh_cycle_once()
        return jsonify(ok=True, refreshed=refreshed)
    except Exception as e:
        log(f"Safe refresh endpoint error: {e}")
        return jsonify(ok=False, error=str(e)), 500

@app.route("/quarantine/list", methods=["GET"])
@require_token
def api_quarantine_list():
    items = []
    for profile, st in _profile_state.items():
        if st.get("quarantined"):
            items.append({
                "profile": profile,
                "failures": st.get("failures", 0),
                "next_allowed": st.get("next_allowed", 0),
            })
    return jsonify(ok=True, quarantined=items)

@app.route("/quarantine/reset", methods=["POST"])
@require_token
def api_quarantine_reset():
    data = request.get_json() or {}
    profile = data.get("profile")
    if not profile:
        return jsonify(ok=False, error="profile required"), 400
    st = _profile_state.get(profile)
    if not st:
        return jsonify(ok=False, error="profile not found in state"), 404
    st["failures"] = 0
    st["next_allowed"] = 0
    st["quarantined"] = False
    log(f"Quarantine reset for {profile}")
    return jsonify(ok=True)

@app.route("/add_proxies", methods=["POST"])
@require_token
def api_add_proxies():
    data = request.get_json() or {}
    proxies = data.get("proxies")
    if not proxies or not isinstance(proxies, dict):
        log("/add_proxies called with no proxies; no action taken.")
        return jsonify(ok=True, message="no proxies applied (stub)")
    for profile, proxy in proxies.items():
        profile_proxies[profile] = proxy
        log(f"Proxy set for {profile}: {proxy}")
    return jsonify(ok=True, message="proxies applied")

@app.route("/change_password", methods=["POST"])
@require_token
def api_change_password():
    data = request.get_json() or {}
    new_pw = data.get("new_password")
    if not new_pw or not isinstance(new_pw, str) or new_pw.strip() == "":
        return jsonify(ok=False, error="new_password required"), 400
    set_new_password(new_pw.strip())
    return jsonify(ok=True)

@app.route("/dashboard/summary", methods=["GET"])
@require_token
def api_dashboard_summary():
    profiles = get_logged_in_profiles()
    total = len(profiles)
    groups = _compute_rotation_groups(profiles)
    with _state_lock:
        last_group = _rotation_state.get("last_group", -1)
        last_cycle_ts = _rotation_state.get("last_cycle_ts", 0)
    quarantined = sum(1 for s in _profile_state.values() if s.get("quarantined"))
    backing_off = sum(1 for s in _profile_state.values() if s.get("next_allowed", 0) > time.time())
    return jsonify(ok=True, summary={
        "total_profiles": total,
        "rotation_groups": len(groups),
        "current_group_index": last_group,
        "current_group_size": len(groups[last_group]) if (0 <= last_group < len(groups)) else 0,
        "quarantined_profiles": quarantined,
        "profiles_in_backoff": backing_off,
        "last_cycle_time": last_cycle_ts,
    })

@app.route("/", methods=["GET"])
def root():
    return jsonify(ok=True, message="Server running")

# Print registered routes (debug)
print("\n[DEBUG] Registered Flask routes:")
for rule in app.url_map.iter_rules():
    print(f"  {rule}")
print()

# ---------------- Boot (load state & start autosave) ---------------- #
_load_state()  # load persisted rotation/profile state if available
_start_autosave()

# ---------------- Run (PyInstaller + normal) ---------------- #
import sys

if __name__ == "__main__":
    # Handle working directory correctly in frozen .exe
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    ensure_password_exists()
    log("🚀 Starting Flask server at http://127.0.0.1:5002")

    try:
        app.run(host="127.0.0.1", port=5002, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        log(f"❌ Server crashed: {e}")
        input("\nPress Enter to exit...")
    finally:
        _on_exit_save()
        input("\nPress Enter to close the server...")
