#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           Pocket FM Downloader  •  v3.0                     ║
║   OTP Login  •  Widevine L3  •  MPEG-DASH  •  DRM          ║
╚══════════════════════════════════════════════════════════════╝
"""

import os, sys, re, json, base64, threading, datetime
import subprocess, shutil, urllib.parse, tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import requests
except ImportError:
    print("pip install requests  — required"); sys.exit(1)

# ─────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────

APP_DIR  = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.join(APP_DIR, "pocketfm_config.json")
BASE_URL = "https://pocketfm.com"

SA_SEND_OTP       = "409bc47d2a18952706ecfba61644dd2566c3cb04c7"
SA_STORY_DETAILS  = "409e8bd890bda1a316d6583a7a531c04043ead5832"
SA_LICENSE_URL    = "401e43ce787a78fcc842aa5c09458cd137942d78a6"
SA_SHOW_DETAILS   = "40e485f3f70b4db6ae573aab483d8be6bb925e3cdf"
SA_SHOW_EPISODES  = "40fcf5bff259b98f5b39b1cba3bff405dc326aa82f"
SA_PLAYTIME       = "40d791bfa1506e472f2420ca9e5074b4d71fe379e5"
SA_LAST_PLAYED    = "400fa180efa364ef79c5f808cab230ae052c4bd566"

ROUTER_STATE_LOGIN = "%5B%22%22%2C%7B%22children%22%3A%5B%22login%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2Cnull%2Cnull%2C162%5D%7D%2Cnull%2Cnull%2C98%5D%7D%2Cnull%2Cnull%2C8274%5D"

HEADERS_BASE = {
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept":           "*/*",
    "Accept-Language":  "en-GB,en-IN;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin":           BASE_URL,
    "Referer":          BASE_URL + "/login",
    "Cache-Control":    "no-cache",
    "Pragma":           "no-cache",
}

DEFAULT_CFG = {
    "token_file":       os.path.join(APP_DIR, "pocketfm_session.json"),
    "output_dir":       os.path.join(os.path.expanduser("~"), "Downloads", "PocketFM"),
    "n_m3u8dl_path":    "N_m3u8DL-RE",
    "mp4decrypt_path":  "mp4decrypt",
    "threads":          16,
    "engine":           "n_m3u8dl",
    "cdm_path":         "",
    "decrypt_tool":     "mp4decrypt",
}

# ─────────────────────────────────────────────────────────────
#  CONFIG  I/O
# ─────────────────────────────────────────────────────────────

def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg

def save_cfg(cfg):
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# ─────────────────────────────────────────────────────────────
#  TOKEN  I/O
# ─────────────────────────────────────────────────────────────

def _mask_phone(phone):
    """Mask phone number: +91XXXXXXXX89 → +91•••••••89"""
    s = str(phone)
    if len(s) >= 6:
        return s[:3] + "•" * (len(s) - 5) + s[-2:]
    return "•" * len(s)

def load_token(cfg):
    p = cfg.get("token_file", "")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
            return d.get("access_token", ""), p
    except Exception:
        return "", p

def save_token(access_token, uid, user_data, cfg):
    p = cfg.get("token_file", "")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({
            "access_token": access_token,
            "uid":          uid,
            "user_data":    user_data,
            "saved_at":     datetime.datetime.now().isoformat(),
        }, f, indent=2)
    return p

def tok_str(token):
    """Short summary of JWT for display."""
    try:
        # Try to read as full session JSON first (what we store)
        d = json.loads(base64.urlsafe_b64decode(token + "==="))
        raw   = d.get("user_data", {}).get("phone_number", d.get("uid", "?"))
        name  = _mask_phone(raw)
        saved = d.get("saved_at", "")[:10]
        return f"{name}  •  saved {saved}"
    except Exception:
        pass
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            padded  = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            uid     = payload.get("uid", payload.get("sub", "?"))[:16]
            exp     = payload.get("exp", 0)
            if exp:
                dt  = datetime.datetime.fromtimestamp(exp)
                rem = dt - datetime.datetime.now()
                hrs = int(rem.total_seconds() / 3600)
                return f"Logged in  •  expires in {hrs}h"
    except Exception:
        pass
    return token[:40] + "..."

# ─────────────────────────────────────────────────────────────
#  AUTHENTICATION
# ─────────────────────────────────────────────────────────────

def api_get_csrf(session, log_cb=None):
    """
    GET /api/auth/csrf  →  {"csrfToken":"..."}
    Returns csrfToken string.
    """
    def _log(m):
        if log_cb: log_cb(m)
    r = session.get(f"{BASE_URL}/api/auth/csrf",
                    headers={**HEADERS_BASE, "Content-Type": "application/json"},
                    timeout=15)
    _log(f"[CSRF] status={r.status_code}  body={r.text[:100]}\n")
    r.raise_for_status()
    return r.json()["csrfToken"]


def api_send_otp(phone_10digit, session, log_cb=None):
    """
    POST /login  with Next-Action header
    Body: [{"phone_number":"+91XXXXXXXXXX","country_code":"+91"}]

    This is a Next.js Server Action — the response is text/x-component
    but the OTP is sent server-side regardless of the response body.

    Returns True if request succeeded (HTTP 200), OTP arrives via SMS.
    """
    def _log(m):
        if log_cb: log_cb(m)

    full_phone = f"+91{phone_10digit}"
    body = json.dumps([{"phone_number": full_phone, "country_code": "+91"}])

    headers = {
        **HEADERS_BASE,
        "Content-Type":           "text/plain;charset=UTF-8",
        "Accept":                 "text/x-component",
        "Next-Action":            SA_SEND_OTP,
        "Next-Router-State-Tree": ROUTER_STATE_LOGIN,
        "Referer":                f"{BASE_URL}/login",
    }

    _log(f"[OTP-Send] → POST {BASE_URL}/login\n")
    _log(f"[OTP-Send]   Next-Action: {SA_SEND_OTP}\n")
    _log(f"[OTP-Send]   body: {body}\n")

    r = session.post(f"{BASE_URL}/login", data=body.encode("utf-8"),
                     headers=headers, timeout=25)
    _log(f"[OTP-Send] status={r.status_code}\n")
    _log(f"[OTP-Send] response (first 300): {r.text[:300]}\n")

    if r.status_code == 200:
        _log(f"[OTP-Send] ✓ OTP dispatched to {full_phone}\n")
        return True

    _log(f"[OTP-Send] ✗ Unexpected status {r.status_code}\n")
    return False


def api_verify_otp(phone_10digit, otp, csrf_token, session, log_cb=None):
    """
    POST /api/auth/callback/credentials?
    body (urlencoded):
        country_code=%2B91
        is_whatsapp=1
        phone_number=%2B91XXXXXXXXXX
        otp=XXXXXX
        type=otp
        csrfToken=<csrf>
        callbackUrl=https://pocketfm.com/login
    extra header: x-auth-return-redirect: 1

    Then GET /api/auth/session  →  {"access-token":"<JWT>","uid":"...","user_data":{...}}

    Returns (access_token, uid, user_data) tuple, or (None, None, None) on failure.
    """
    def _log(m):
        if log_cb: log_cb(m)

    full_phone = f"+91{phone_10digit}"

    payload = urllib.parse.urlencode({
        "country_code": "+91",
        "is_whatsapp":  "1",
        "phone_number": full_phone,
        "otp":          otp,
        "type":         "otp",
        "csrfToken":    csrf_token,
        "callbackUrl":  f"{BASE_URL}/login",
    })

    headers = {
        **HEADERS_BASE,
        "Content-Type":           "application/x-www-form-urlencoded",
        "x-auth-return-redirect": "1",
        "Referer":                f"{BASE_URL}/login",
    }

    _log(f"[OTP-Verify] → POST /api/auth/callback/credentials?\n")
    _log(f"[OTP-Verify]   payload: {payload}\n")

    r = session.post(
        f"{BASE_URL}/api/auth/callback/credentials?",
        data=payload.encode("utf-8"),
        headers=headers,
        allow_redirects=True,
        timeout=25,
    )
    _log(f"[OTP-Verify] status={r.status_code}\n")
    _log(f"[OTP-Verify] response: {r.text[:300]}\n")

    # Now fetch session — the JWT is in the response body (not HttpOnly cookie)
    _log(f"[Session]  → GET /api/auth/session\n")
    s = session.get(
        f"{BASE_URL}/api/auth/session",
        headers={**HEADERS_BASE, "Content-Type": "application/json"},
        timeout=15,
    )
    _log(f"[Session]  status={s.status_code}\n")
    _log(f"[Session]  body: {s.text[:500]}\n")

    if s.status_code != 200:
        _log(f"[Session]  ✗ Failed\n")
        return None, None, None

    try:
        data = s.json()
    except Exception as e:
        _log(f"[Session]  ✗ JSON parse error: {e}\n")
        return None, None, None

    # Session response uses "access-token" key
    access_token = data.get("access-token") or data.get("access_token")
    uid          = data.get("uid", "")
    user_data    = data.get("user_data", {})

    if access_token:
        _log(f"[Session]  ✓ logged in\n")
        _log(f"[Session]  ✓ phone: {_mask_phone(user_data.get('phone_number',''))}\n")
        return access_token, uid, user_data

    # If session returned null or {} (not logged in yet)
    _log(f"[Session]  ✗ No access-token in response — OTP may be wrong\n")
    return None, None, None


# ─────────────────────────────────────────────────────────────
#  CONTENT ID  EXTRACTION
# ─────────────────────────────────────────────────────────────

def extract_content_id(url_or_id):
    """
    Extract show/episode hex ID from Pocket FM URL.
    Returns (content_id, content_type) or (None, None)
    """
    s = url_or_id.strip()
    # Match hex IDs in URL path
    m = re.search(r'/(?:show|episode|series)/([a-f0-9]{12,})', s, re.I)
    if m:
        ctype = "show" if "/show/" in s else "episode"
        return m.group(1), ctype
    # Raw hex ID passthrough
    if re.match(r'^[a-f0-9]{12,}$', s, re.I):
        return s, "episode"
    # Numeric ID fallback
    if s.isdigit():
        return s, "episode"
    return None, None

# ─────────────────────────────────────────────────────────────
#  STREAM  FETCHING
# ─────────────────────────────────────────────────────────────

def _sa_post(episode_id, action_id, body_list, session, log_cb=None):
    """
    POST a Next.js Server Action to the episode page URL.
    Returns parsed JSON from the RSC response (line starting with "1:").
    """
    def _log(m):
        if log_cb: log_cb(m)

    ep_url = f"{BASE_URL}/episode/{episode_id}"
    body   = json.dumps(body_list)
    headers = {
        **HEADERS_BASE,
        "Content-Type":           "text/plain;charset=UTF-8",
        "Accept":                 "text/x-component",
        "Next-Action":            action_id,
        "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22episode%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%5D%7D%5D%7D%5D",
        "Referer":                ep_url,
    }
    _log(f"[SA] POST {ep_url}\n    action={action_id}\n    body={body[:120]}\n")
    r = session.post(ep_url, data=body.encode("utf-8"), headers=headers, timeout=25)
    _log(f"[SA] status={r.status_code}\n")
    _log(f"[SA] response[:400]: {r.text[:400]}\n")

    # RSC format: each line is  <idx>:<json>  — data is on line starting with "1:"
    for line in r.text.splitlines():
        if line.startswith("1:"):
            try:
                return json.loads(line[2:])
            except Exception as e:
                _log(f"[SA] JSON parse err: {e}\n")
    return {}


def _sa_post_show(show_id, action_id, body_list, session, log_cb=None):
    """POST a Next.js Server Action to the SHOW page URL (not episode URL)."""
    def _log(m):
        if log_cb: log_cb(m)
    show_url = f"{BASE_URL}/show/{show_id}"
    body = json.dumps(body_list)
    headers = {
        **HEADERS_BASE,
        "Content-Type":           "text/plain;charset=UTF-8",
        "Accept":                 "text/x-component",
        "Next-Action":            action_id,
        "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22show%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%5D%7D%5D%7D%5D",
        "Referer":                show_url,
    }
    _log(f"[SA-Show] POST {show_url}\n    action={action_id}\n    body={body[:120]}\n")
    r = session.post(show_url, data=body.encode("utf-8"), headers=headers, timeout=25)
    _log(f"[SA-Show] status={r.status_code}\n")
    _log(f"[SA-Show] response[:400]: {r.text[:400]}\n")
    for line in r.text.splitlines():
        if line.startswith("1:"):
            try:
                return json.loads(line[2:])
            except Exception as e:
                _log(f"[SA-Show] JSON parse err: {e}\n")
    return {}


def fetch_show_episodes(show_id, session, log_cb=None, page_size=20, max_eps=None):
    """
    Fetch ALL episode stubs for a show using SA_SHOW_EPISODES pagination.
    Returns (show_title, is_drm, episodes_count, stories_list)
    Each story: {story_id, story_title, seq_number, media_url_enc, show_id, ...}
    """
    def _log(m):
        if log_cb: log_cb(m)

    # First get show metadata
    meta = _sa_post_show(show_id, SA_SHOW_DETAILS, [
        {"showId": show_id, "campaignName": "", "referralCode": ""}
    ], session, _log)
    show_title  = meta.get("show_title", show_id)
    is_drm      = meta.get("is_drm_enabled", False)

    _log(f"[Show] Title: {show_title}  DRM: {is_drm}\n")

    all_stories = []
    curr_ptr    = 0
    total_eps   = None

    while True:
        fetch_size = page_size if not max_eps else min(page_size, max_eps - len(all_stories))
        data = _sa_post_show(show_id, SA_SHOW_EPISODES, [
            {"showId": show_id, "campaignName": "", "referralCode": "",
             "currPtr": curr_ptr, "pageSize": fetch_size}
        ], session, _log)

        result   = data.get("result", {})
        stories  = result.get("stories", [])
        total_eps = total_eps or result.get("episodes_count", 0)

        if not stories:
            break
        all_stories.extend(stories)
        _log(f"[Show] Fetched {len(all_stories)}/{total_eps} episodes\n")

        curr_ptr += len(stories)
        if max_eps and len(all_stories) >= max_eps:
            break
        if curr_ptr >= total_eps:
            break

    return show_title, is_drm, total_eps or len(all_stories), all_stories


def fetch_playtime(show_id, episode_id, session, log_cb=None):
    """
    Fetch per-episode listen progress for a show using SA_PLAYTIME.
    Returns dict: {story_id -> listened_perc (0-100)}


    Body: [{"showId":"...","paginationState":null}]
    Response: {"status":1,"data":{"stories":[{"story_id":"...","listened_perc":N,...}]}}

    Note: paginationState can be used to page through large shows, but typically
    the first call returns all played episodes.
    """
    def _log(m):
        if log_cb: log_cb(m)

    _log(f"[Playtime] Fetching listen progress for show {show_id[:12]}…\n")

    headers = {
        **HEADERS_BASE,
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept":        "text/x-component",
        "Next-Action":   SA_PLAYTIME,
        "Next-Router-State-Tree": "%5B%22%22%2C%7B%7D%5D",
        "Referer":       f"{BASE_URL}/episode/{episode_id}",
    }

    result_map = {}
    pagination_state = None

    # Page through all played episodes
    for _page in range(50):  # max 50 pages safety cap
        body = [{"showId": show_id, "paginationState": pagination_state}]
        try:
            r = session.post(
                f"{BASE_URL}/episode/{episode_id}",
                data=json.dumps(body).encode("utf-8"),
                headers=headers, timeout=20
            )
            parsed = {}
            for line in r.text.splitlines():
                if line.startswith("1:"):
                    try: parsed = json.loads(line[2:])
                    except: pass
                    break

            data = parsed.get("data", {})
            stories = data.get("stories", [])
            if not stories:
                break

            for s in stories:
                sid  = s.get("story_id","")
                perc = s.get("listened_perc", 0)
                if sid:
                    result_map[sid] = perc

            # Check if there's another page
            pagination_state = data.get("pagination_state")
            if not pagination_state:
                break

        except Exception as e:
            _log(f"[Playtime] Error: {e}\n")
            break

    _log(f"[Playtime] Got progress for {len(result_map)} episodes\n")
    return result_map


def fetch_last_played(episode_id, session, log_cb=None):
    """
    Fetch last-played story info across all shows for the logged-in user.
    Returns dict: {show_id -> last_played_story dict}


    Body: [{"deviceId":"mobile-web","showId":""}]
    """
    def _log(m):
        if log_cb: log_cb(m)

    headers = {
        **HEADERS_BASE,
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept":        "text/x-component",
        "Next-Action":   SA_LAST_PLAYED,
        "Next-Router-State-Tree": "%5B%22%22%2C%7B%7D%5D",
        "Referer":       f"{BASE_URL}/episode/{episode_id}",
    }

    try:
        body = [{"deviceId": "mobile-web", "showId": ""}]
        r = session.post(
            f"{BASE_URL}/episode/{episode_id}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers, timeout=20
        )
        for line in r.text.splitlines():
            if line.startswith("1:"):
                try:
                    parsed = json.loads(line[2:])
                    result = parsed.get("result", [])
                    return {item["show_id"]: item["last_played_story"]
                            for item in result if "show_id" in item}
                except: pass
    except Exception as e:
        _log(f"[LastPlayed] Error: {e}\n")

    return {}


def fetch_episode_stream(episode_id, access_token, session, log_cb=None):
    """
    Fetch episode stream URLs using the real Server Action flow.
    Action: SA_STORY_DETAILS → returns media_url_enc (MPD), video_url (HLS).

    Returns (mpd_url, hls_url, episode_data_dict)
    """
    def _log(m):
        if log_cb: log_cb(m)


    # Body: [{"episodeId":"...","campaignName":"","entityId":"","entityType":""}]
    data = _sa_post(episode_id, SA_STORY_DETAILS, [
        {"episodeId": episode_id, "campaignName": "", "entityId": "", "entityType": ""}
    ], session, _log)

    if not data or data.get("status") != 1:
        _log(f"[Fetch] ✗ Story details failed: {data}\n")
        return None, None, {}

    result_list = data.get("result", [])
    ep = result_list[0] if result_list else {}

    # Stream URL priority:
    # video_url_enc_fb  → H264 CENC DASH with video (720p/480p/144p) + audio  [primary]
    # media_url_enc     → Audio-only CENC DASH                                 [fallback]
    #
    # media_url_enc_std → alternate audio-only MPD (last resort)
    # video_url         → plain HLS (ddqs490ahjgsl.cloudfront.net) — non-DRM,
    #                     often inaccessible without cookie, skip unless others fail
    # ─────────────────────────────────────────────────────────────────────────
    video_mpd  = ep.get("video_url_enc_fb")   # has real 720p video track
    audio_mpd  = ep.get("media_url_enc") or ep.get("media_url_enc_std")
    hls        = ep.get("video_url")

    # Prefer the full video MPD when available
    mpd = video_mpd or audio_mpd

    # Enrich data dict with top-level fields
    ep["show_id"]         = ep.get("show_id") or data.get("show_id", "")
    ep["is_drm_enabled"]  = data.get("is_drm_enabled", False)
    ep["title"]           = ep.get("story_title", episode_id)
    ep["has_video"]       = bool(video_mpd)   # GUI can show 720p quality when True

    _log(f"[Fetch] ✓ title:     {ep.get('title','?')}\n")
    _log(f"[Fetch] ✓ DRM:       {ep.get('is_drm_enabled')}\n")
    _log(f"[Fetch] ✓ has_video: {ep.get('has_video')} {'(720p H264)' if video_mpd else '(audio-only)'}\n")
    _log(f"[Fetch] ✓ MPD:       {str(mpd)[:120]}\n")
    if hls:
        _log(f"[Fetch]   HLS(alt): {str(hls)[:100]}\n")
    return mpd, hls, ep


def fetch_widevine_license_url(episode_id, show_id, session, log_cb=None):
    """
    Fetch Widevine license URL using Server Action SA_LICENSE_URL.
    Action: SA_LICENSE_URL → returns license_url (widevine.gumlet.com pre-signed)

    Body: [{"isFairplay":false,"showId":"..."}]

    Returns the license URL string or None.
    """
    def _log(m):
        if log_cb: log_cb(m)

    data = _sa_post(episode_id, SA_LICENSE_URL, [
        {"isFairplay": False, "showId": show_id}
    ], session, _log)

    if not data or data.get("status") != 1:
        _log(f"[License] ✗ Failed: {data}\n")
        return None

    lic = data.get("license_url")
    if lic:
        _log(f"[License] ✓ {lic[:120]}\n")
    return lic

# ─────────────────────────────────────────────────────────────
#  PSSH  EXTRACTION
# ─────────────────────────────────────────────────────────────

def extract_pssh_from_mpd(mpd_url, session, log_cb=None):
    """Extract Widevine PSSH from DASH MPD manifest."""
    def _log(m):
        if log_cb: log_cb(m)

    try:
        r = session.get(mpd_url, timeout=20, headers={
            **HEADERS_BASE,
            "Accept": "application/dash+xml,application/xml,*/*"
        })
        mpd_text = r.text
        _log(f"[MPD] Downloaded {len(mpd_text)} bytes\n")
    except Exception as e:
        _log(f"[MPD] ✗ {e}\n")
        return None, None

    # Form 1: Widevine cenc:pssh block
    m = re.search(
        r'<cenc:pssh[^>]*edef8ba9[^>]*>\s*([A-Za-z0-9+/=]+)\s*</cenc:pssh>',
        mpd_text, re.I
    )
    if m:
        pssh = m.group(1).strip()
        _log(f"[MPD] ✓ PSSH (Widevine block): {pssh[:40]}...\n")
        return pssh, mpd_text

    # Form 2: any cenc:pssh
    m = re.search(r'<cenc:pssh[^>]*>\s*([A-Za-z0-9+/=]{20,})\s*</cenc:pssh>', mpd_text, re.I)
    if m:
        pssh = m.group(1).strip()
        _log(f"[MPD] ✓ PSSH (generic): {pssh[:40]}...\n")
        return pssh, mpd_text

    # Form 3: build from KID
    kids = re.findall(r'cenc:default_KID=["\']([0-9a-f-]{32,36})["\']', mpd_text, re.I)
    if kids:
        kid_hex = kids[0].replace("-", "")
        widevine_system_id = bytes.fromhex("edef8ba979d64acea3c827dcd51d21ed")
        pssh_box = (
            b"\x00\x00\x00\x34" + b"pssh"
            + b"\x01\x00\x00\x00"
            + widevine_system_id
            + b"\x00\x00\x00\x01"
            + bytes.fromhex(kid_hex)
            + b"\x00\x00\x00\x00"
        )
        pssh = base64.b64encode(pssh_box).decode()
        _log(f"[MPD] ✓ PSSH (built from KID {kid_hex}): {pssh[:40]}...\n")
        return pssh, mpd_text

    _log("[MPD] ✗ No PSSH found\n")
    return None, mpd_text


# ─────────────────────────────────────────────────────────────
#  WIDEVINE  KEYS
# ─────────────────────────────────────────────────────────────

def get_widevine_keys(pssh_b64, license_url, session, cdm_path="", log_cb=None):
    """Extract Widevine content keys using pywidevine L3."""
    def _log(m):
        if log_cb: log_cb(m)

    if not pssh_b64:
        _log("[WV] ✗ No PSSH\n"); return []
    if not license_url:
        _log("[WV] ✗ No license URL\n"); return []

    wvd_path = cdm_path or ""
    if not wvd_path or not os.path.exists(wvd_path):
        for loc in [APP_DIR, os.path.expanduser("~"), os.getcwd()]:
            if os.path.isdir(loc):
                for f in os.listdir(loc):
                    if f.endswith(".wvd"):
                        wvd_path = os.path.join(loc, f); break

    if not wvd_path or not os.path.exists(wvd_path):
        _log("[WV] ✗ No .wvd device file — set CDM path in Settings\n"); return []

    try:
        from pywidevine.cdm    import Cdm
        from pywidevine.device import Device
        from pywidevine.pssh   import PSSH
    except ImportError:
        _log("[WV] ✗ pip install pywidevine\n"); return []

    try:
        _log(f"[WV] Loading: {os.path.basename(wvd_path)}\n")
        device    = Device.load(wvd_path)
        cdm       = Cdm.from_device(device)
        sess      = cdm.open()
        pssh_obj  = PSSH(pssh_b64)
        challenge = cdm.get_license_challenge(sess, pssh_obj)
        _log(f"[WV] Challenge: {len(challenge)} bytes\n")
        _log(f"[WV] → License: {license_url[:100]}\n")

        lr = session.post(license_url, data=bytes(challenge),
                          headers={**HEADERS_BASE,
                                   "Content-Type": "application/octet-stream"},
                          timeout=30)
        _log(f"[WV] License status={lr.status_code}\n")
        if lr.status_code != 200:
            _log(f"[WV] ✗ License error: {lr.text[:300]}\n"); cdm.close(sess); return []

        cdm.parse_license(sess, lr.content)
        keys = [(k.kid.hex, k.key.hex()) for k in cdm.get_keys(sess) if k.type == "CONTENT"]
        cdm.close(sess)
        _log(f"[WV] ✓ {len(keys)} key(s):\n")
        for kid, key in keys:
            _log(f"[WV]   {kid}:{key}\n")
        return keys
    except Exception as e:
        _log(f"[WV] ✗ {e}\n")
        import traceback; _log(traceback.format_exc())
        return []


# ─────────────────────────────────────────────────────────────
#  QUALITY  PARSING
# ─────────────────────────────────────────────────────────────

def parse_mpd_qualities(mpd_text, log_cb=None):
    """
    Parse all Representation blocks from MPD.
    Returns list of quality dicts — video if present, otherwise audio.
    Each dict has: type, height (or 0), kbps, bw, channels, codec, est_size, label
    """
    def _log(m):
        if log_cb: log_cb(m)
    if not mpd_text: return []

    video_quals = {}
    audio_quals = {}

    # Walk AdaptationSet blocks to know their contentType
    for as_match in re.finditer(
            r'<AdaptationSet([^>]*)>(.*?)</AdaptationSet>', mpd_text, re.S | re.I):
        as_attrs  = as_match.group(1)
        as_body   = as_match.group(2)
        ct = ""
        # contentType attr
        m = re.search(r'contentType=["\'](\w+)["\']', as_attrs, re.I)
        if m: ct = m.group(1).lower()
        # or mimeType
        if not ct:
            m = re.search(r'mimeType=["\'](\w+)', as_attrs, re.I)
            if m: ct = m.group(1).lower()
        channels = 2
        m = re.search(r'AudioChannelConfiguration[^v]*value=["\'](\d+)["\']', as_body, re.I)
        if m: channels = int(m.group(1))

        for rep in re.finditer(r'<Representation([^>]*)/?>',  as_body, re.I):
            ra = rep.group(1)
            bw = int(re.search(r'bandwidth=["\'](\d+)["\']', ra).group(1)) if re.search(r'bandwidth=["\'](\d+)["\']', ra) else 0
            codec = ""
            m = re.search(r'codecs=["\']([^"\']+)["\']', ra, re.I)
            if m: codec = m.group(1)
            height = None
            m = re.search(r'height=["\'](\d+)["\']', ra, re.I)
            if m: height = int(m.group(1))

            if ct == "video" or height:
                h = height or 0
                kbps = round(bw / 1000)
                # estimate size: bw * duration_guess(12min) / 8
                est = f"~{max(1, bw * 720 // 8 // 1_048_576)} MB"
                q = {"type": "video", "height": h, "kbps": kbps, "bw": bw,
                     "codec": codec, "est_size": est,
                     "label": f"{h}p  {kbps} kbps"}
                if h not in video_quals or bw > video_quals[h]["bw"]:
                    video_quals[h] = q
            else:
                # audio
                kbps = round(bw / 1000)
                est  = f"~{max(1, bw * 720 // 8 // 1_048_576)} MB"
                q = {"type": "audio", "height": 0, "kbps": kbps, "bw": bw,
                     "channels": channels, "codec": codec, "est_size": est,
                     "label": f"{kbps} kbps  {channels}ch  ({codec or 'aac'})"}
                if kbps not in audio_quals or bw > audio_quals[kbps]["bw"]:
                    audio_quals[kbps] = q

    if video_quals:
        quals = sorted(video_quals.values(), key=lambda x: x["height"], reverse=True)
        _log(f"[Quals] {len(quals)} video quality tier(s)\n")
        return quals
    if audio_quals:
        quals = sorted(audio_quals.values(), key=lambda x: x["kbps"], reverse=True)
        _log(f"[Quals] {len(quals)} audio quality tier(s)\n")
        return quals
    _log("[Quals] No representations found\n")
    return []


# ─────────────────────────────────────────────────────────────
#  UTILITY
# ─────────────────────────────────────────────────────────────

def find_exe(candidates):
    for c in candidates:
        if not c: continue
        if os.path.isfile(c) and os.access(c, os.X_OK): return c
        found = shutil.which(c)
        if found: return found
    return None

def make_filename(title, quality=None):
    """Return base filename (no extension) for a given title + quality dict."""
    safe = re.sub(r'[\\/:*?"<>|]', '_', title or "episode")
    safe = re.sub(r'\s+', '.', safe.strip())
    if quality:
        q_type = quality.get("type", "audio")
        height = quality.get("height", 0)
        kbps   = quality.get("kbps", 0)
        if q_type == "video" and height:
            return f"{safe}.{height}p"
        elif kbps:
            return f"{safe}.{kbps}kbps"
    return safe


# ─────────────────────────────────────────────────────────────
#  DOWNLOAD  ENGINE
# ─────────────────────────────────────────────────────────────

def run_download(stream_url, out_dir, out_name, quality, cfg,
                 progress_cb, log_cb, cancel_flag, drm_keys=None, has_video=False):
    """
    has_video: True when stream_url is the video MPD (video_url_enc_fb) containing
               real H264 video tracks (720p/480p/144p + audio).
               False when stream_url is the audio-only MPD (media_url_enc).
    """
    def _log(m):
        if log_cb: log_cb(m)
    os.makedirs(out_dir, exist_ok=True)
    engine   = cfg.get("engine", "auto")
    threads  = int(cfg.get("threads", 16))
    nm_path  = cfg.get("n_m3u8dl_path", "N_m3u8DL-RE")
    yt_path  = cfg.get("ytdlp_path", "yt-dlp")
    ff_path  = cfg.get("ffmpeg_path", "ffmpeg")

    q_type  = quality.get("type", "audio") if quality else "audio"
    height  = quality.get("height", 0)     if quality else 0
    kbps    = quality.get("kbps", 0)       if quality else 0
    # has_video overrides quality-derived guess — trust actual MPD content
    is_audio_only = not has_video and (q_type == "audio" or height == 0)

    # Output extensions — audio → .m4a, video → .mkv / .mp4
    out_ext  = "m4a" if is_audio_only else "mkv"
    out_m4a  = os.path.join(out_dir, out_name + ".m4a")
    out_mkv  = os.path.join(out_dir, out_name + ".mkv")
    out_mp4  = os.path.join(out_dir, out_name + ".mp4")
    out_main = out_m4a if is_audio_only else out_mkv

    # Widevine key flags (--key kid:key for N_m3u8DL-RE)
    key_flags = []
    if drm_keys:
        for kid, key in drm_keys:
            key_flags += ["--key", f"{kid.lower()}:{key.lower()}"]

    q_label = f"{kbps} kbps" if is_audio_only else f"{height}p"
    _log(f"[DL] type={q_type}  {'audio-only' if is_audio_only else 'video+audio'}\n")
    _log(f"[DL] quality={q_label}  keys={len(drm_keys or [])}\n\n")

    def run_proc(cmd, parse_cb=None):
        _log(f"[CMD] {' '.join(str(x) for x in cmd)}\n\n")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, errors='replace')
            for line in proc.stdout:
                _log(line)
                if cancel_flag.is_set():
                    proc.terminate()
                    try: proc.wait(timeout=3)
                    except: proc.kill()
                    return -99
                if parse_cb: parse_cb(line)
            proc.wait()
            return proc.returncode
        except FileNotFoundError: return -1
        except Exception as e: _log(f"[!] {e}\n"); return -1

    # ── N_m3u8DL-RE ──
    nm = find_exe([nm_path, "N_m3u8DL-RE", os.path.join(APP_DIR, "N_m3u8DL-RE.exe")])
    if nm and engine in ("auto", "n_m3u8dl"):
        if is_audio_only:
            # Audio-only CENC MPEG-DASH:
            # - skip video with -dv (drop video), select best audio with -sa
            # - --mux-after-done only supports mkv/mp4/ts — NOT m4a
            # - use format=mp4 so ffmpeg muxes cleanly, then rename to .m4a after
            # Audio-only MPD has 0 video streams — no need for -dv (it eats next arg as regex)
            # --auto-select picks the best available audio track automatically
            # Headers must use -H shortform with value as single "Name: Value" string
            cmd = [nm, stream_url,
                   "--save-dir", out_dir, "--save-name", out_name,
                   "--thread-count", str(threads),
                   "--tmp-dir", os.path.join(out_dir, ".tmp"),
                   "--mux-after-done", "format=mp4",   # mp4 valid; renamed .m4a after
                   "--auto-select",                     # picks best audio automatically
                   "-H", f"Origin: {BASE_URL}",
                   "-H", f"Referer: {BASE_URL}/"] + key_flags
        else:
            v_sel = f"res={height}x{height}" if height else "best"
            cmd = [nm, stream_url,
                   "--save-dir", out_dir, "--save-name", out_name,
                   "--thread-count", str(threads),
                   "--tmp-dir", os.path.join(out_dir, ".tmp"),
                   "--mux-after-done", "format=mkv",
                   "-sv", v_sel,
                   "-sa", "best",
                   "-H", f"Origin: https://video-secure.pocketfm.com",
                   "-H", f"Referer: {BASE_URL}/"] + key_flags

        _log(f"[N_m3u8DL-RE] {threads} threads | {q_label}\n\n")
        pct1 = re.compile(r'(\d+\.?\d*)%.*?(\d+\.?\d*\s*\w+/s)')
        pct2 = re.compile(r'(\d+\.?\d*)%')
        def parse_nm(l):
            mm = pct1.search(l)
            if mm: progress_cb(float(mm.group(1)), mm.group(2)); return
            mm = pct2.search(l)
            if mm: progress_cb(float(mm.group(1)), "")
        rc = run_proc(cmd, parse_nm)
        if rc == 0:
            progress_cb(100, "")
            if is_audio_only:
                # N_m3u8DL-RE outputs .mp4 for audio-only (m4a is not a valid mux format)
                # rename .mp4 → .m4a so the file has correct audio extension
                mp4_out = os.path.join(out_dir, out_name + ".mp4")
                m4a_out = os.path.join(out_dir, out_name + ".m4a")
                if os.path.exists(mp4_out) and not os.path.exists(m4a_out):
                    try:
                        os.rename(mp4_out, m4a_out)
                        _log(f"[✓] Renamed {out_name}.mp4 → {out_name}.m4a\n")
                    except Exception as e:
                        _log(f"[!] Rename failed: {e}\n")
                        m4a_out = mp4_out
                if os.path.exists(m4a_out): return True, m4a_out
            # find output file (video: .mkv first, then fallbacks)
            for ext in ("mkv", "mp4", "m4a", "aac"):
                p = os.path.join(out_dir, out_name + "." + ext)
                if os.path.exists(p): return True, p
            return True, out_main
        if rc == -99: return False, None
        if engine == "n_m3u8dl": _log("[✗] N_m3u8DL-RE failed.\n"); return False, None
        _log("[!] Trying yt-dlp\n\n")

    # ── yt-dlp ──
    yt = find_exe([yt_path, "yt-dlp"])
    if yt and engine in ("auto", "ytdlp"):
        if is_audio_only:
            fmt = f"bestaudio[abr<={kbps+10}]/bestaudio/best" if kbps else "bestaudio/best"
            out_tmpl = os.path.join(out_dir, out_name + ".%(ext)s")
            cmd = [yt, stream_url, "-f", fmt,
                   "-o", out_tmpl,
                   "--concurrent-fragments", str(min(threads, 16)),
                   "--add-header", f"Origin: {BASE_URL}",
                   "--add-header", f"Referer: {BASE_URL}/",
                   "--allow-unplayable-formats",
                   "--no-warnings", "--newline"]
        else:
            fmt = f"bestvideo[height<={height}]+bestaudio/best" if height else "bestvideo+bestaudio/best"
            out_tmpl = os.path.join(out_dir, out_name + ".%(ext)s")
            cmd = [yt, stream_url, "-f", fmt,
                   "-o", out_tmpl,
                   "--concurrent-fragments", str(min(threads, 16)),
                   "--add-header", f"Origin: {BASE_URL}",
                   "--add-header", f"Referer: {BASE_URL}/",
                   "--merge-output-format", "mkv",
                   "--allow-unplayable-formats",
                   "--no-warnings", "--newline"]
        _log(f"[yt-dlp] {q_label}\n\n")
        pct1 = re.compile(r'\[download\]\s+(\d+\.?\d*)%.*?(\d+\.?\d*\s*\w+/s)')
        pct2 = re.compile(r'\[download\]\s+(\d+\.?\d*)%')
        def parse_yt(l):
            mm = pct1.search(l)
            if mm: progress_cb(float(mm.group(1)), mm.group(2)); return
            mm = pct2.search(l)
            if mm: progress_cb(float(mm.group(1)), "")
        rc = run_proc(cmd, parse_yt)
        if rc == 0:
            progress_cb(100, "")
            for ext in ("m4a", "mkv", "mp4", "aac", "webm"):
                p = os.path.join(out_dir, out_name + "." + ext)
                if os.path.exists(p): return True, p
            return True, out_main
        if rc == -99: return False, None
        if engine == "ytdlp": _log("[✗] yt-dlp failed.\n"); return False, None
        _log("[!] Trying ffmpeg\n\n")

    # ── ffmpeg fallback ──
    ff = find_exe([ff_path, "ffmpeg"])
    if not ff: _log("[✗] No downloader found (tried N_m3u8DL-RE, yt-dlp, ffmpeg).\n"); return False, None
    out_ff = out_m4a if is_audio_only else out_mp4
    cmd = [ff, "-allowed_extensions", "ALL",
           "-headers", f"Origin: {BASE_URL}\r\nReferer: {BASE_URL}/\r\n",
           "-i", stream_url, "-c", "copy", out_ff, "-y",
           "-progress", "pipe:1", "-nostats", "-loglevel", "error"]
    _log(f"[ffmpeg] fallback | {q_label}\n\n")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, bufsize=1, errors='replace')
        def read_err():
            for l in proc.stderr: _log(l)
        threading.Thread(target=read_err, daemon=True).start()
        dur_total = 0
        for line in proc.stdout:
            if cancel_flag.is_set():
                proc.terminate(); return False, None
            # parse progress: out_time_ms=...
            m = re.search(r'out_time_ms=(\d+)', line)
            if m and dur_total:
                pct = min(99, int(m.group(1)) / 1000 / dur_total * 100)
                progress_cb(pct, "")
            m = re.search(r'total_size=(\d+)', line)
        proc.wait()
        if proc.returncode == 0 and os.path.exists(out_ff):
            progress_cb(100, ""); return True, out_ff
    except Exception as e: _log(f"[!] ffmpeg: {e}\n")
    return False, None


# ─────────────────────────────────────────────────────────────
#  DECRYPTION
# ─────────────────────────────────────────────────────────────

def decrypt_with_mp4decrypt(enc, out, keys, path="mp4decrypt", log_cb=None):
    def _log(m):
        if log_cb: log_cb(m)
    mp4d = find_exe([path, "mp4decrypt", os.path.join(APP_DIR, "mp4decrypt.exe")])
    if not mp4d: _log("[mp4decrypt] ✗ Not found\n"); return False
    cmd = [mp4d]
    for kid, key in keys:
        cmd += ["--key", f"{kid.replace('-','').lower()}:{key.replace('-','').lower()}"]
    cmd += [enc, out]
    _log(f"[mp4decrypt] {len(keys)} key(s)\n")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, errors="replace")
    for l in proc.stdout: _log(f"[mp4decrypt] {l}")
    proc.wait()
    if proc.returncode == 0 and os.path.exists(out):
        _log("[mp4decrypt] ✓\n"); return True
    _log(f"[mp4decrypt] ✗ rc={proc.returncode}\n"); return False


def decrypt_with_shaka(enc, out, keys, path="packager", log_cb=None):
    def _log(m):
        if log_cb: log_cb(m)
    shaka = find_exe([path, "packager", os.path.join(APP_DIR, "packager.exe")])
    if not shaka: _log("[Shaka] ✗ Not found\n"); return False
    ff    = find_exe(["ffmpeg"])
    klbls = [f"label={i},key_id={kid.replace('-','').lower()},key={key.replace('-','').lower()}"
             for i, (kid, key) in enumerate(keys)]
    base, ext = os.path.splitext(enc)
    tv, ta = base+"_v.mp4", base+"_a.mp4"
    def _run(st, tmp):
        cmd = [shaka, f"in={enc},stream={st},output={tmp},drm_label=CENC",
               "--enable_raw_key_decryption", "--keys", ",".join(klbls)]
        _log(f"[Shaka] {st}\n")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, errors="replace")
        for l in proc.stdout: _log(l)
        proc.wait()
        return proc.returncode == 0 and os.path.exists(tmp)
    ok_v, ok_a = _run("video", tv), _run("audio", ta)
    if ok_v and ok_a and ff:
        r = subprocess.run([ff, "-y", "-i", tv, "-i", ta, "-c", "copy", out, "-loglevel", "error"],
                           capture_output=True, timeout=120)
        for t in [tv, ta]:
            try: os.remove(t)
            except: pass
        if r.returncode == 0: _log("[Shaka] ✓\n"); return True
    _log("[Shaka] ✗\n"); return False


def post_decrypt(enc, out, keys, cfg, log_cb=None):
    tool = cfg.get("decrypt_tool", "auto")
    sp   = cfg.get("shaka_path", "packager")
    mp   = cfg.get("mp4decrypt_path", "mp4decrypt")
    if tool == "shaka":      return decrypt_with_shaka(enc, out, keys, sp, log_cb)
    if tool == "mp4decrypt": return decrypt_with_mp4decrypt(enc, out, keys, mp, log_cb)
    if decrypt_with_mp4decrypt(enc, out, keys, mp, log_cb): return True
    return decrypt_with_shaka(enc, out, keys, sp, log_cb)


# ─────────────────────────────────────────────────────────────
#  THEME
# ─────────────────────────────────────────────────────────────

BG   = "#0d0f18"; BG2 = "#13151f"; BG3 = "#1c1e2e"; BG4 = "#22253a"
ACC  = "#e8572a"; ACC2= "#c94420"; ACC3= "#ff7a52"
FG   = "#e4e4f0"; FG2 = "#7a7a9d"; FG3 = "#44445a"
GRN  = "#4ade80"; RED = "#f87171"; YLW = "#fbbf24"; ORG = "#fb923c"
FONT = ("Segoe UI", 10); FONTB = ("Segoe UI", 10, "bold"); MONO = ("Consolas", 10)


class CheckRow(tk.Frame):
    def __init__(self, parent, var, q, is_top=False, **kw):
        """q = quality dict from parse_mpd_qualities()"""
        super().__init__(parent, bg=BG2, cursor="hand2", **kw)
        self.var = var
        self.cv  = tk.Canvas(self, width=18, height=18, bg=BG2, highlightthickness=0, cursor="hand2")
        self.cv.pack(side="left", padx=(6,8), pady=6)
        self._draw()

        q_type   = q.get("type", "audio")
        height   = q.get("height", 0)
        kbps     = q.get("kbps", 0)
        channels = q.get("channels", 2)
        codec    = q.get("codec", "aac")
        est_size = q.get("est_size", "?")
        mbps     = q.get("bw", kbps * 1000) / 1_000_000

        if q_type == "video" and height:
            q_color = {1080: ACC3, 720: GRN, 480: YLW, 360: ORG}.get(height, FG2)
            tk.Label(self, text=f"{height}p",       bg=BG2, fg=q_color, font=("Consolas",10,"bold"), width=7,  anchor="w").pack(side="left")
            tk.Label(self, text=f"{mbps:.2f} Mbps", bg=BG2, fg=FG2,     font=("Consolas",9),          width=11, anchor="w").pack(side="left")
        else:
            # Audio quality row
            kbps_colors = {192: ACC3, 128: GRN, 96: YLW, 64: ORG}
            q_color = kbps_colors.get(kbps, FG2)
            tk.Label(self, text=f"{kbps} kbps",     bg=BG2, fg=q_color, font=("Consolas",10,"bold"), width=9,  anchor="w").pack(side="left")
            tk.Label(self, text=f"{channels}ch",     bg=BG2, fg=FG2,     font=("Consolas",9),          width=5,  anchor="w").pack(side="left")
            tk.Label(self, text=f"({codec})",         bg=BG2, fg=FG3,     font=("Consolas",9),          width=14, anchor="w").pack(side="left")

        tk.Label(self, text=est_size, bg=BG2,
                 fg=GRN if is_top else FG2,
                 font=("Consolas",9,"bold" if is_top else "normal"),
                 width=10, anchor="w").pack(side="left")
        self._bind_all(self)
        self.var.trace_add("write", lambda *a: self._draw())

    def _bind_all(self, w):
        w.bind("<Button-1>", self._toggle)
        w.bind("<Enter>",    lambda e: (self.configure(bg=BG4), self.cv.configure(bg=BG4)))
        w.bind("<Leave>",    lambda e: (self.configure(bg=BG2), self.cv.configure(bg=BG2)))
        for c in w.winfo_children(): self._bind_all(c)

    def _toggle(self, e=None): self.var.set(not self.var.get())

    def _draw(self):
        cv = self.cv; cv.delete("all")
        on = self.var.get()
        cv.create_rectangle(1,1,17,17, fill=ACC if on else BG3, outline=ACC if on else FG3)
        if on:
            cv.create_line(3,9, 7,13,  fill="#fff", width=2, capstyle="round")
            cv.create_line(7,13,15,5,  fill="#fff", width=2, capstyle="round")


# ─────────────────────────────────────────────────────────────
#  MAIN APP
# ─────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pocket FM Downloader  •  v3.0")
        self.configure(bg=BG)
        try: self.iconbitmap(default='')
        except: pass

        # Responsive sizing — adapt to screen
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = min(1100, int(sw * 0.75))
        h  = min(900,  int(sh * 0.82))
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(680, 520)
        self.resizable(True, True)

        self.cfg         = load_cfg()
        self._session    = requests.Session()
        self._session.headers.update(HEADERS_BASE)
        self._csrf       = ""
        self._phone      = ""
        self._mpd_url    = None
        self._hls_url    = None
        self._mpd_text   = None
        self._quals      = []
        self._q_vars     = []
        self._episode_data   = {}
        self._episode_title  = ""
        self._orig_url   = ""
        self._log_open   = False
        self._dl_thread  = None
        self._cancel     = threading.Event()
        self._drm_keys   = []
        self._pssh       = None
        self._license_url = None
        self._drm_status = "unknown"

        self._build_styles()
        self._build_ui()
        self._refresh_status()

    def _build_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, font=FONT)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("TButton", background=ACC, foreground="#fff", font=FONTB,
                    borderwidth=0, padding=(14,7), relief="flat")
        s.map("TButton", background=[("active",ACC2),("disabled",BG3)],
              foreground=[("disabled",FG2)])
        s.configure("Ghost.TButton", background=BG3, foreground=FG2,
                    font=("Segoe UI",9), padding=(10,5), relief="flat", borderwidth=0)
        s.map("Ghost.TButton", background=[("active",ACC),("disabled",BG3)],
              foreground=[("active","#fff"),("disabled",FG3)])
        s.configure("Cancel.TButton", background="#7f1d1d", foreground=RED,
                    font=FONTB, padding=(14,7), relief="flat", borderwidth=0)
        s.map("Cancel.TButton", background=[("active","#991b1b")])
        s.configure("TEntry", fieldbackground=BG3, foreground=FG, insertcolor=ACC3,
                    borderwidth=0, relief="flat", padding=6)
        s.configure("TNotebook", background=BG, tabmargins=[0,0,0,0], borderwidth=0)
        s.configure("TNotebook.Tab", background=BG2, foreground=FG2, padding=[22,9],
                    font=FONT, borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected",ACC),("active",BG3)],
              foreground=[("selected","#fff"),("active",FG)])
        s.configure("Prog.Horizontal.TProgressbar", troughcolor=BG3, background=ACC,
                    borderwidth=0, thickness=8, lightcolor=ACC, darkcolor=ACC2)
        s.configure("TCheckbutton", background=BG2, foreground=FG, font=FONT)
        s.map("TCheckbutton", background=[("active",BG2)])

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG2, height=54)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        lf = tk.Frame(hdr, bg=BG2); lf.pack(side="left", padx=18, pady=12)
        tk.Label(lf, text="🎧", bg=BG2, fg=ACC, font=("Segoe UI",15,"bold")).pack(side="left")
        tk.Label(lf, text="  Pocket FM Downloader", bg=BG2, fg=FG, font=("Segoe UI",13,"bold")).pack(side="left")
        rf = tk.Frame(hdr, bg=BG2); rf.pack(side="right", padx=18, pady=14)
        self._status_txt = tk.Label(rf, text="", bg=BG2, fg=FG2, font=("Segoe UI",9))
        self._status_txt.pack(side="right", padx=(0,6))
        self._status_dot = tk.Label(rf, text="●", bg=BG2, fg=RED, font=("Segoe UI",10))
        self._status_dot.pack(side="right")
        tk.Frame(self, bg=ACC, height=2).pack(fill="x")

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self._t_login = ttk.Frame(nb); nb.add(self._t_login, text="  Login  ")
        self._t_dl    = ttk.Frame(nb); nb.add(self._t_dl,    text="  Download  ")
        self._t_cfg   = ttk.Frame(nb); nb.add(self._t_cfg,   text="  Settings  ")
        self._build_login()
        self._build_download()
        self._build_settings()

    # ─── LOGIN TAB ───

    def _build_login(self):
        f = self._t_login
        col = tk.Frame(f, bg=BG); col.pack(anchor="n", padx=40, pady=24, fill="x")

        card = tk.Frame(col, bg=BG2, padx=30, pady=26); card.pack(fill="x")
        tk.Label(card, text="Phone Login (India)", bg=BG2, fg=ACC,
                 font=("Segoe UI",13,"bold")).grid(row=0,column=0,columnspan=3,sticky="w",pady=(0,20))

        tk.Label(card, text="Phone number  (10 digits, no +91)", bg=BG2, fg=FG2,
                 font=("Segoe UI",9)).grid(row=1,column=0,sticky="w")
        self._phone_e = tk.Entry(card, bg=BG3, fg=FG, insertbackground=ACC3,
                                  font=("Consolas",12), relief="flat", width=18, bd=0)
        self._phone_e.grid(row=2,column=0,pady=(5,0),ipady=7,padx=(0,12),sticky="w")
        self._send_btn = ttk.Button(card, text="Send OTP", command=self._send_otp)
        self._send_btn.grid(row=2,column=1,pady=(5,0),sticky="w")

        tk.Label(card, text="OTP", bg=BG2, fg=FG2,
                 font=("Segoe UI",9)).grid(row=3,column=0,sticky="w",pady=(18,0))
        self._otp_e = tk.Entry(card, bg=BG3, fg=FG, insertbackground=ACC3,
                                font=("Consolas",13), relief="flat", width=12, bd=0, state="disabled")
        self._otp_e.grid(row=4,column=0,pady=(5,0),ipady=7,padx=(0,12),sticky="w")
        self._verify_btn = ttk.Button(card, text="Verify & Login",
                                       command=self._verify_otp, state="disabled")
        self._verify_btn.grid(row=4,column=1,pady=(5,0),sticky="w")

        self._login_msg = tk.Label(card, text="", bg=BG2, fg=FG2,
                                    font=("Segoe UI",9), wraplength=460, justify="left")
        self._login_msg.grid(row=5,column=0,columnspan=3,pady=(18,0),sticky="w")

        # Session info
        tok_card = tk.Frame(col, bg=BG2, padx=22, pady=18); tok_card.pack(fill="x",pady=(16,0))
        tk.Label(tok_card, text="🎧 PocketFM Session", bg=BG2, fg=ACC, font=("Segoe UI",9,"bold")).pack(anchor="w")
        self._tok_detail = tk.Label(tok_card, text="Checking...", bg=BG2, fg=FG2,
                                     font=("Segoe UI",9), wraplength=600, justify="left")
        self._tok_detail.pack(anchor="w",pady=(6,10))
        ttk.Button(tok_card, text="Clear Session", style="Ghost.TButton",
                   command=self._clear_token).pack(anchor="w")

        # Live log for auth debug
        log_card = tk.Frame(col, bg=BG2, padx=22, pady=16); log_card.pack(fill="x",pady=(16,0))
        tk.Label(log_card, text="Auth Log", bg=BG2, fg=ACC, font=("Segoe UI",9,"bold")).pack(anchor="w",pady=(0,6))
        self._auth_log = tk.Text(log_card, height=12, state="disabled",
                                  bg="#080a11", fg="#6a6aaa", font=("Consolas",8),
                                  borderwidth=0, wrap="word",
                                  selectbackground=ACC2, selectforeground="#fff")
        sb = tk.Scrollbar(log_card, command=self._auth_log.yview)
        self._auth_log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._auth_log.pack(fill="both", expand=True)

    def _auth_log_w(self, t):
        self._auth_log.configure(state="normal")
        self._auth_log.insert("end", t)
        self._auth_log.see("end")
        self._auth_log.configure(state="disabled")

    # ─── DOWNLOAD TAB ───

    def _build_download(self):
        f = self._t_dl
        PAD = dict(padx=14, pady=(10,4))

        uc = tk.Frame(f, bg=BG2); uc.pack(fill="x", **PAD)
        ui = tk.Frame(uc, bg=BG2, padx=16, pady=14); ui.pack(fill="x")
        tk.Label(ui, text="Pocket FM Episode/Show URL or Episode ID", bg=BG2, fg=FG2,
                 font=("Segoe UI",9)).pack(anchor="w",pady=(0,6))
        ur = tk.Frame(ui, bg=BG2); ur.pack(fill="x")
        self._url_e = tk.Entry(ur, bg=BG3, fg=FG, insertbackground=ACC3, font=MONO, relief="flat", bd=0)
        self._url_e.pack(side="left",fill="x",expand=True,ipady=7,padx=(0,10))
        self._fetch_btn = ttk.Button(ur, text="🔍  Fetch Qualities", command=self._fetch)
        self._fetch_btn.pack(side="left")
        tk.Label(ui, text="e.g. https://pocketfm.com/episode/abc123...  or hex episode ID",
                 bg=BG2, fg=FG3, font=("Segoe UI",8)).pack(anchor="w",pady=(4,0))
        self._ep_info = tk.Label(ui, text="", bg=BG2, fg=ACC3, font=("Segoe UI",9), wraplength=700)
        self._ep_info.pack(anchor="w", pady=(6,0))

        qc = tk.Frame(f, bg=BG2); qc.pack(fill="x", **PAD)
        qi = tk.Frame(qc, bg=BG2, padx=16, pady=12); qi.pack(fill="x")
        self._drm_bar  = tk.Frame(qi, bg=BG2); self._drm_bar.pack(fill="x", pady=(0,6))
        self._drm_icon = tk.Label(self._drm_bar, text="🔒", bg=BG2, fg=FG3, font=("Segoe UI",10))
        self._drm_icon.pack(side="left")
        self._drm_lbl  = tk.Label(self._drm_bar, text="", bg=BG2, fg=FG3, font=("Segoe UI",8))
        self._drm_lbl.pack(side="left", padx=(4,0))

        qt = tk.Frame(qi, bg=BG2); qt.pack(fill="x",pady=(0,6))
        tk.Label(qt, text="Select Quality", bg=BG2, fg=FG2, font=("Segoe UI",9)).pack(side="left")
        ttk.Button(qt, text="None", style="Ghost.TButton", command=lambda: self._check_all(False)).pack(side="right",padx=(4,0))
        ttk.Button(qt, text="All",  style="Ghost.TButton", command=lambda: self._check_all(True)).pack(side="right")
        self._q_frame = tk.Frame(qi, bg=BG2); self._q_frame.pack(fill="x")
        tk.Label(self._q_frame, text="← paste URL and click Fetch Qualities",
                 bg=BG2, fg=FG3, font=("Segoe UI",9)).pack(anchor="w", pady=6)

        dc = tk.Frame(f, bg=BG2); dc.pack(fill="x", **PAD)
        di = tk.Frame(dc, bg=BG2, padx=16, pady=14); di.pack(fill="x")
        tk.Label(di, text="Output Directory", bg=BG2, fg=FG2, font=("Segoe UI",9)).pack(anchor="w",pady=(0,5))
        or_ = tk.Frame(di, bg=BG2); or_.pack(fill="x",pady=(0,12))
        self._out_var = tk.StringVar(value=self.cfg.get("output_dir",""))
        tk.Entry(or_, textvariable=self._out_var, bg=BG3, fg=FG, insertbackground=ACC3,
                  font=MONO, relief="flat", bd=0).pack(side="left",fill="x",expand=True,ipady=6,padx=(0,10))
        ttk.Button(or_, text="Browse", style="Ghost.TButton", command=self._browse_out).pack(side="left")
        tk.Frame(di, bg=BG3, height=1).pack(fill="x", pady=(0,12))

        br2 = tk.Frame(di, bg=BG2); br2.pack(fill="x")
        self._dl_btn     = ttk.Button(br2, text="⬇  Download", command=self._start_dl)
        self._dl_btn.pack(side="left")
        self._cancel_btn = ttk.Button(br2, text="✕  Cancel", style="Cancel.TButton",
                                       command=self._cancel_dl)
        self._open_btn   = ttk.Button(br2, text="📂 Open Folder", style="Ghost.TButton",
                                       command=self._open_folder, state="disabled")
        self._open_btn.pack(side="left", padx=10)
        self._dl_status  = tk.Label(br2, text="", bg=BG2, fg=FG2, font=("Segoe UI",9))
        self._dl_status.pack(side="left")

        pr = tk.Frame(di, bg=BG2); pr.pack(fill="x", pady=(12,0))
        self._prog = ttk.Progressbar(pr, style="Prog.Horizontal.TProgressbar",
                                      orient="horizontal", mode="determinate", maximum=100)
        self._prog.pack(fill="x",expand=True)
        self._prog_txt = tk.Label(di, text="", bg=BG2, fg=FG2, font=("Segoe UI",8))
        self._prog_txt.pack(anchor="w", pady=(4,0))

        lh = tk.Frame(f, bg=BG, cursor="hand2"); lh.pack(fill="x",padx=14,pady=(4,0))
        self._log_lbl_var = tk.StringVar(value="▸  Show log")
        self._log_lbl     = tk.Label(lh, textvariable=self._log_lbl_var, bg=BG, fg=FG2,
                                      font=("Segoe UI",9), cursor="hand2")
        self._log_lbl.pack(side="left",pady=3,padx=2)
        for w in (lh, self._log_lbl): w.bind("<Button-1>", lambda e: self._toggle_log())

        self._log_frame = tk.Frame(f, bg=BG)
        self._log_box   = tk.Text(self._log_frame, height=10, state="disabled",
                                   bg="#080a11", fg="#6a6aaa", font=("Consolas",8),
                                   borderwidth=0, wrap="word",
                                   selectbackground=ACC2, selectforeground="#fff")
        sb = tk.Scrollbar(self._log_frame, command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_box.pack(fill="both",expand=True,padx=(14,0),pady=(3,10))

    # ─── SETTINGS TAB ───

    def _build_settings(self):
        f = self._t_cfg
        outer = tk.Frame(f, bg=BG); outer.pack(fill="both",expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb2    = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        win   = canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        card = tk.Frame(inner, bg=BG2, padx=26, pady=24); card.pack(fill="x",padx=26,pady=22)
        card.columnconfigure(1, weight=1)
        tk.Label(card, text="Settings", bg=BG2, fg=ACC, font=("Segoe UI",13,"bold")
                 ).grid(row=0,column=0,columnspan=4,sticky="w",pady=(0,10))
        self._cfg_vars = {}

        tk.Label(card, text="╌╌  Download Engine  ╌╌", bg=BG2, fg=FG3,
                 font=("Segoe UI",8)).grid(row=1,column=0,columnspan=4,sticky="w",pady=(0,6))
        eng_frame = tk.Frame(card, bg=BG2); eng_frame.grid(row=2,column=0,columnspan=4,sticky="w",pady=(0,12))
        self._engine_var = tk.StringVar(value=self.cfg.get("engine","auto"))
        engines = [
            ("n_m3u8dl", "⚡  N_m3u8DL-RE",   "Fastest · parallel · DRM keys ✓"),
        ]
        for col,(val,lbl,tip) in enumerate(engines):
            cell = tk.Frame(eng_frame, bg=BG3, padx=10, pady=8, cursor="hand2")
            cell.grid(row=0, column=col, padx=(0,8), sticky="n")
            tk.Radiobutton(cell, text=lbl, variable=self._engine_var, value=val,
                           bg=BG3, fg=FG, selectcolor=BG3, activebackground=BG3,
                           activeforeground=ACC, font=("Segoe UI",9,"bold"),
                           bd=0, highlightthickness=0).pack(anchor="w")
            tk.Label(cell, text=tip, bg=BG3, fg=FG2,
                     font=("Segoe UI",7), wraplength=130).pack(anchor="w",pady=(4,0))
            cell.bind("<Button-1>", lambda e,v=val: self._engine_var.set(v))
        def _ref_eng(*_):
            sel = self._engine_var.get()
            for col,(val,_,__) in enumerate(engines):
                w = eng_frame.grid_slaves(row=0,column=col)
                if w:
                    c = ACC if val==sel else BG3
                    w[0].configure(bg=c)
                    for child in w[0].winfo_children(): child.configure(bg=c)
        self._engine_var.trace_add("write", _ref_eng); _ref_eng()

        tk.Label(card, text="╌╌  Paths  ╌╌", bg=BG2, fg=FG3,
                 font=("Segoe UI",8)).grid(row=3,column=0,columnspan=4,sticky="w",pady=(4,6))
        path_rows = [
            ("token_file",      "PocketFM Session",  "pocketfm_session.json"),
            ("output_dir",      "Output Folder",     "Where files are saved"),
            ("n_m3u8dl_path",   "N_m3u8DL-RE exe",   "⚡ github.com/nilaoda/N_m3u8DL-RE"),
            ("mp4decrypt_path", "mp4decrypt exe",     "🔑 bento4.com — Bento4 SDK"),
            ("cdm_path",        "WVD Device File",    "🔐 Widevine L3 .wvd"),
        ]
        for i,(k,lbl,hint) in enumerate(path_rows):
            r = i+4
            tk.Label(card, text=lbl, bg=BG2, fg=FG, font=FONTB, width=16, anchor="w"
                     ).grid(row=r,column=0,sticky="w",pady=7)
            var = tk.StringVar(value=self.cfg.get(k,""))
            self._cfg_vars[k] = var
            tk.Entry(card, textvariable=var, bg=BG3, fg=FG, insertbackground=ACC3,
                      font=("Consolas",9), relief="flat", bd=0, width=42
                      ).grid(row=r,column=1,padx=8,ipady=6,sticky="ew")
            ttk.Button(card, text="Browse", style="Ghost.TButton",
                       command=lambda k=k,v=var: self._cfg_browse(k,v)
                       ).grid(row=r,column=2,padx=6)
            tk.Label(card, text=hint, bg=BG2, fg=FG2, font=("Segoe UI",8),
                     wraplength=180).grid(row=r,column=3,padx=8,sticky="w")

        r = len(path_rows)+4
        tk.Frame(card, bg=BG3, height=1).grid(row=r,column=0,columnspan=4,sticky="ew",pady=14)
        r += 1
        tk.Label(card, text="DL Threads", bg=BG2, fg=FG, font=FONTB,
                 anchor="w").grid(row=r,column=0,sticky="w",pady=8)
        self._threads_var = tk.IntVar(value=self.cfg.get("threads",16))
        tr = tk.Frame(card, bg=BG2); tr.grid(row=r,column=1,sticky="w",pady=8)
        ttk.Scale(tr, from_=4, to=64, variable=self._threads_var, orient="horizontal", length=200,
                  command=lambda v: self._threads_lbl.configure(text=str(int(float(v))))
                  ).pack(side="left")
        self._threads_lbl = tk.Label(tr, text=str(self.cfg.get("threads",16)),
                                      bg=BG2, fg=ACC3, font=("Consolas",10,"bold"), width=3)
        self._threads_lbl.pack(side="left",padx=8)
        r += 1
        tk.Frame(card, bg=BG3, height=1).grid(row=r,column=0,columnspan=4,sticky="ew",pady=14)
        r += 1
        ttk.Button(card, text="Save Settings", command=self._save_cfg
                   ).grid(row=r,column=0,sticky="w")
        self._cfg_msg = tk.Label(card, text="", bg=BG2, fg=GRN, font=("Segoe UI",9))
        self._cfg_msg.grid(row=r,column=1,sticky="w",padx=10)

    # ─── ACTIONS ───

    def _log_w(self, t):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", t)
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _toggle_log(self):
        if self._log_open:
            self._log_frame.pack_forget()
            self._log_lbl_var.set("▸  Show log")
        else:
            self._log_frame.pack(fill="both", expand=True)
            self._log_lbl_var.set("▾  Hide log")
        self._log_open = not self._log_open

    def _refresh_status(self):
        tok, path = load_token(self.cfg)
        if tok:
            s = tok_str(tok)
            self._status_dot.configure(fg=GRN)
            self._status_txt.configure(text=f"Logged in  •  {s}", fg=FG2)
            self._tok_detail.configure(text=f"✓  Valid session  •  {s}\n{path}", fg=GRN)
        else:
            self._status_dot.configure(fg=RED)
            self._status_txt.configure(text="Not logged in", fg=FG2)
            self._tok_detail.configure(text="✗  No session — use Login tab", fg=RED)

    def _clear_token(self):
        p = self.cfg.get("token_file","")
        if p and os.path.exists(p): os.remove(p)
        self._refresh_status()
        self._tok_detail.configure(text="PocketFM session cleared.", fg=FG2)

    def _update_drm_ui(self):
        s = self._drm_status
        if s == "none":
            self._drm_icon.configure(text="🔓", fg=GRN)
            self._drm_lbl.configure(text="DRM: Plain stream — no decryption needed", fg=GRN)
        elif s == "fetching":
            self._drm_icon.configure(text="🔒", fg=YLW)
            self._drm_lbl.configure(text="DRM: Widevine encrypted  •  Fetching keys...", fg=YLW)
        elif s == "locked":
            self._drm_icon.configure(text="🔒", fg=YLW)
            self._drm_lbl.configure(text="DRM: Widevine encrypted  •  Set CDM (.wvd) in Settings", fg=YLW)
        elif s == "unlocked":
            self._drm_icon.configure(text="🗝", fg=GRN)
            self._drm_lbl.configure(text=f"DRM: Widevine  •  ✓ {len(self._drm_keys)} key(s) ready", fg=GRN)
        elif s == "failed":
            self._drm_icon.configure(text="🔒", fg=RED)
            self._drm_lbl.configure(text="DRM: Widevine  •  ✗ Key fetch failed — check log", fg=RED)
        else:
            self._drm_icon.configure(text="🔒", fg=FG3)
            self._drm_lbl.configure(text="", fg=FG3)

    # LOGIN

    def _send_otp(self):
        phone = self._phone_e.get().strip().replace("+91","").replace(" ","")
        if not phone.isdigit() or len(phone) != 10:
            self._login_msg.configure(text="✗ Enter a valid 10-digit number", fg=RED); return
        self._phone = phone
        self._send_btn.configure(state="disabled", text="Sending...")
        self._login_msg.configure(text="Fetching CSRF token...", fg=FG2)
        # Clear auth log
        self._auth_log.configure(state="normal")
        self._auth_log.delete("1.0", "end")
        self._auth_log.configure(state="disabled")

        def _w():
            def _log(m): self.after(0, lambda m=m: self._auth_log_w(m))
            # Step 1: CSRF
            try:
                csrf = api_get_csrf(self._session, _log)
                self._csrf = csrf
                self.after(0, lambda: self._login_msg.configure(
                    text=f"CSRF obtained, sending OTP...", fg=FG2))
            except Exception as e:
                self.after(0, lambda: self._login_msg.configure(
                    text=f"✗ CSRF failed: {e}", fg=RED))
                self.after(0, lambda: self._send_btn.configure(state="normal", text="Send OTP"))
                return
            # Step 2: Send OTP
            ok = api_send_otp(phone, self._session, _log)
            if ok:
                self.after(0, self._otp_ok)
            else:
                self.after(0, lambda: self._login_msg.configure(
                    text="✗ OTP send failed — check auth log below", fg=RED))
                self.after(0, lambda: self._send_btn.configure(state="normal", text="Send OTP"))
        threading.Thread(target=_w, daemon=True).start()

    def _otp_ok(self):
        self._login_msg.configure(text=f"✓ OTP sent to +91{self._phone}  —  check SMS", fg=GRN)
        self._send_btn.configure(state="normal", text="Resend OTP")
        self._otp_e.configure(state="normal")
        self._verify_btn.configure(state="normal")
        self._otp_e.focus()

    def _verify_otp(self):
        otp = self._otp_e.get().strip()
        if not otp.isdigit():
            self._login_msg.configure(text="✗ Invalid OTP", fg=RED); return
        self._verify_btn.configure(state="disabled", text="Verifying...")

        def _w():
            def _log(m): self.after(0, lambda m=m: self._auth_log_w(m))
            access_token, uid, user_data = api_verify_otp(
                self._phone, otp, self._csrf, self._session, _log)
            if access_token:
                path = save_token(access_token, uid, user_data, self.cfg)
                phone = _mask_phone(user_data.get("phone_number", self._phone))
                self.after(0, lambda: self._login_msg.configure(
                    text=f"✓ Login successful!\n{phone}\nSaved: {path}", fg=GRN))
                self.after(0, self._refresh_status)
                self.after(0, lambda: self._verify_btn.configure(state="normal", text="Verify & Login"))
            else:
                self.after(0, lambda: self._login_msg.configure(
                    text="✗ OTP wrong or expired — check auth log below", fg=RED))
                self.after(0, lambda: self._verify_btn.configure(state="normal", text="Verify & Login"))
        threading.Thread(target=_w, daemon=True).start()

    # DOWNLOAD

    def _browse_out(self):
        d = filedialog.askdirectory(initialdir=self._out_var.get())
        if d: self._out_var.set(d)

    def _check_all(self, val):
        for v in self._q_vars: v.set(val)

    def _open_show_picker(self, show_id, show_title, ep_count, stories):
        """
        Pop a Toplevel window listing all fetched episodes with listen-progress badges.
        Fetches playtime data in background (SA_PLAYTIME) and updates rows live.
        User can select any subset → Download Selected queues sequential download.
        """
        # Need a sample episode_id to post SA_PLAYTIME against
        sample_ep_id = next(
            (s.get("story_id","") for s in stories if s.get("story_id")),
            show_id
        )

        win = tk.Toplevel(self, bg=BG)
        win.title(f"Episodes — {show_title}")
        _sw = win.winfo_screenwidth(); _sh = win.winfo_screenheight()
        _ww = min(960, int(_sw * 0.72)); _wh = min(640, int(_sh * 0.75))
        win.geometry(f"{_ww}x{_wh}+{(_sw-_ww)//2}+{(_sh-_wh)//2}")
        win.minsize(560, 380)
        win.resizable(True, True)

        # Header
        tk.Label(win, text=f"🎙  {show_title}", bg=BG, fg=FG, font=FONTB,
                 anchor="w").pack(fill="x", padx=16, pady=(12,2))
        hdr_lbl = tk.Label(win,
            text=f"{ep_count} episodes total  •  {len(stories)} fetched  •  fetching progress…",
            bg=BG, fg=FG3, font=FONT)
        hdr_lbl.pack(anchor="w", padx=16)

        # Toolbar
        tb = tk.Frame(win, bg=BG); tb.pack(fill="x", padx=12, pady=6)
        ttk.Button(tb, text="✓ All",   command=lambda: _tog(True)).pack(side="left", padx=4)
        ttk.Button(tb, text="✗ None",  command=lambda: _tog(False)).pack(side="left", padx=4)
        ttk.Button(tb, text="✓ Unfinished", command=lambda: _tog_unfinished()).pack(side="left", padx=4)
        ep_range_lbl = tk.Label(tb, text="Ep range:", bg=BG, fg=FG2, font=FONT)
        ep_range_lbl.pack(side="left", padx=(12,4))
        from_v = tk.StringVar(value="1")
        to_v   = tk.StringVar(value=str(len(stories)))
        tk.Entry(tb, textvariable=from_v, width=5, bg=BG3, fg=FG, insertbackground=FG).pack(side="left", padx=2)
        tk.Label(tb, text="–", bg=BG, fg=FG2).pack(side="left")
        tk.Entry(tb, textvariable=to_v,   width=5, bg=BG3, fg=FG, insertbackground=FG).pack(side="left", padx=2)
        ttk.Button(tb, text="Select range", command=lambda: _sel_range()).pack(side="left", padx=6)

        # Legend
        leg = tk.Frame(win, bg=BG); leg.pack(anchor="w", padx=16, pady=(0,4))
        for txt, col in [("██ Done(≥90%)", GRN), ("██ Partial", YLW), ("██ New", FG3), ("🔒 Paid", ORG)]:
            tk.Label(leg, text=txt, bg=BG, fg=col, font=FONT).pack(side="left", padx=6)

        # Episode list (scrollable)
        frame = tk.Frame(win, bg=BG2); frame.pack(fill="both", expand=True, padx=12, pady=4)
        canvas = tk.Canvas(frame, bg=BG2, highlightthickness=0)
        sb     = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner  = tk.Frame(canvas, bg=BG2)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        win_id = canvas.create_window((0,0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)),"units"))

        # Build episode rows — progress_lbl per row will be updated when playtime arrives
        ep_vars      = []
        prog_labels  = {}   # story_id → Label widget

        for s in stories:
            sid   = s.get("story_id", "")
            var   = tk.BooleanVar(value=False)
            ep_vars.append((var, s))
            seq   = s.get("seq_number", "?")
            ttl   = s.get("story_title", s.get("story_id","?"))
            dur   = s.get("duration", 0)
            dur_s = f"{dur//60}:{dur%60:02d}" if dur else "?:??"
            coins = s.get("coins_required", 0)
            lock_ico = "🔒 " if coins else ""
            fg_row = ORG if coins else FG

            row = tk.Frame(inner, bg=BG2, cursor="hand2"); row.pack(fill="x", pady=1)
            tk.Checkbutton(row, variable=var, bg=BG2, activebackground=BG2,
                           fg=FG, selectcolor=BG3, relief="flat").pack(side="left")
            # Progress badge placeholder (will be updated by background thread)
            prog_lbl = tk.Label(row, text="   ", bg=BG2, fg=FG3, font=MONO, width=6, anchor="center")
            prog_lbl.pack(side="left", padx=(0,4))
            if sid:
                prog_labels[sid] = prog_lbl

            tk.Label(row, text=f"Ep {seq:>4}  {lock_ico}{ttl[:58]:<60}  {dur_s}",
                     bg=BG2, fg=fg_row, font=MONO, anchor="w").pack(side="left", fill="x")
            row.bind("<Button-1>", lambda e, v=var: v.set(not v.get()))

        # Playtime data dict (populated by background thread)
        playtime_data = {}   # story_id → listened_perc

        def _apply_playtime(pt_map):
            """Update progress badges on episode rows from pt_map."""
            playtime_data.update(pt_map)
            listened_count = sum(1 for p in pt_map.values() if p >= 90)
            partial_count  = sum(1 for p in pt_map.values() if 0 < p < 90)
            for sid, perc in pt_map.items():
                lbl = prog_labels.get(sid)
                if not lbl: continue
                if perc >= 90:
                    lbl.configure(text=f"{perc:3d}%", fg=GRN, bg=BG2)
                elif perc > 0:
                    lbl.configure(text=f"{perc:3d}%", fg=YLW, bg=BG2)
                else:
                    lbl.configure(text="  0%",  fg=FG3, bg=BG2)
            hdr_lbl.configure(
                text=(f"{ep_count} episodes total  •  {len(stories)} fetched  •  "
                      f"✅ {listened_count} done  •  ⏳ {partial_count} partial")
            )

        def _fetch_playtime_bg():
            """Background thread: fetch playtime then update GUI via after()."""
            tok, _ = load_token(self.cfg)
            if not tok: return
            sess = requests.Session()
            sess.cookies.update({"access-token": tok})
            try:
                pt_map = fetch_playtime(show_id, sample_ep_id, sess)
                if pt_map and win.winfo_exists():
                    win.after(0, lambda: _apply_playtime(pt_map))
            except Exception:
                pass

        # Launch playtime fetch in background — doesn't block picker from opening
        pt_thread = threading.Thread(target=_fetch_playtime_bg, daemon=True)
        pt_thread.start()

        def _tog(val):
            for v, _ in ep_vars: v.set(val)

        def _tog_unfinished():
            """Select only episodes that haven't been fully listened to (< 90%)."""
            for v, s in ep_vars:
                sid  = s.get("story_id","")
                perc = playtime_data.get(sid, 0)
                # If playtime not loaded yet, treat as unfinished
                v.set(perc < 90)

        def _sel_range():
            try:
                lo = max(1, int(from_v.get())) - 1
                hi = min(len(ep_vars), int(to_v.get()))
                for i, (v, _) in enumerate(ep_vars):
                    v.set(lo <= i < hi)
            except: pass

        def _dl_selected():
            chosen = [(v, s) for v, s in ep_vars if v.get()]
            if not chosen:
                messagebox.showwarning("Nothing selected", "Pick at least one episode.", parent=win)
                return
            win.destroy()
            self._queue_show_dl(show_id, show_title, chosen)

        # Footer
        ft = tk.Frame(win, bg=BG); ft.pack(fill="x", padx=12, pady=10)
        ttk.Button(ft, text=f"⬇  Download Selected", command=_dl_selected).pack(side="left", padx=4)
        ttk.Button(ft, text="Cancel", command=win.destroy).pack(side="left", padx=4)
        # Quick action: select all unfinished then download
        ttk.Button(ft, text="⬇  Unfinished Only",
                   command=lambda: [_tog_unfinished(), _dl_selected()]).pack(side="left", padx=12)

    def _queue_show_dl(self, show_id, show_title, chosen_eps):
        """
        Download each chosen episode sequentially — reuses the existing
        single-episode pipeline by injecting stream URL from the stub.
        """
        if self._dl_thread and self._dl_thread.is_alive():
            messagebox.showinfo("Busy","Download already running."); return
        tok, _ = load_token(self.cfg)
        if not tok: messagebox.showerror("Not logged in","Login first."); return

        out_dir  = self._out_var.get().strip() or self.cfg.get("output_dir", APP_DIR)
        cfg_snap = dict(self.cfg)
        cfg_snap["threads"] = int(self._threads_var.get())
        cfg_snap["engine"]  = self._engine_var.get()
        self._cancel.clear()
        self._dl_btn.configure(state="disabled", text="Downloading series...")
        self._cancel_btn.pack(side="left", padx=(0,10))
        self._open_btn.configure(state="disabled")
        self._prog.configure(value=0)
        if not self._log_open: self._toggle_log()

        def _log(m): self.after(0, lambda m=m: self._log_w(m))

        def _work():
            total  = len(chosen_eps)
            last_ok= None
            all_ok = True
            for idx, (_, story) in enumerate(chosen_eps):
                if self._cancel.is_set(): break
                ep_id  = story.get("story_id","")
                ep_ttl = story.get("story_title", ep_id)
                seq    = story.get("seq_number", idx+1)
                self.after(0, lambda n=idx+1,t=total,s=ep_ttl:
                    self._dl_status.configure(text=f"[{n}/{t}] {s[:40]}…", fg=FG2))
                _log(f"\n{'='*60}\n[Series] Ep {seq}/{total}: {ep_ttl}\n{'='*60}\n")

                # Get stream URL — either from stub or by fetching fresh
                mpd = story.get("media_url_enc") or story.get("media_url_enc_std")
                hls = story.get("video_url")

                if not mpd and not hls:
                    # Fallback: individual SA fetch
                    mpd, hls, ep_data = fetch_episode_stream(ep_id, tok, self._session, _log)
                    story.update(ep_data)

                stream = mpd or hls
                if not stream:
                    _log(f"[!] No stream for ep {seq} — skipping\n")
                    all_ok = False; continue

                # Get keys if DRM
                drm_keys = []
                if mpd:
                    pssh, mpd_text = extract_pssh_from_mpd(mpd, self._session, _log)
                    if pssh:
                        cdm = self.cfg.get("cdm_path","").strip()
                        if cdm and os.path.exists(cdm):
                            lic = fetch_widevine_license_url(ep_id, show_id, self._session, _log)
                            if lic:
                                drm_keys = get_widevine_keys(pssh, lic, self._session, cdm_path=cdm, log_cb=_log)

                has_video = ep_data.get("has_video", False)
                if has_video:
                    qual = {"type":"video","height":720,"kbps":0}  # 720p video
                else:
                    qual = {"type":"audio","kbps":192,"height":0}  # best audio
                fname = make_filename(ep_ttl, qual)
                ok, out_path = run_download(
                    stream, out_dir, fname, qual, cfg_snap,
                    lambda pct,spd: self.after(0, lambda p=pct,s=spd: (
                        self._prog.configure(value=p),
                        self._prog_txt.configure(text=f"{p:.1f}%{'   '+s if s else ''}"))),
                    _log, self._cancel, drm_keys=drm_keys, has_video=has_video)
                if ok: last_ok = out_path
                else:  all_ok = False

            def _done():
                self._dl_btn.configure(state="normal", text="⬇  Download")
                self._cancel_btn.pack_forget()
                if self._cancel.is_set():
                    self._dl_status.configure(text="Cancelled", fg=YLW)
                elif all_ok:
                    self._prog.configure(value=100)
                    self._dl_status.configure(text=f"✓ Done! {total} episodes", fg=GRN)
                    self._open_btn.configure(state="normal")
                else:
                    self._dl_status.configure(text="✗ Some failed — check log", fg=RED)
                self._refresh_status()
            self.after(0, _done)

        self._dl_thread = threading.Thread(target=_work, daemon=True)
        self._dl_thread.start()

    def _fetch(self):
        url = self._url_e.get().strip()
        if not url: messagebox.showwarning("No URL", "Paste a URL or ID first."); return
        cid, ctype = extract_content_id(url)
        if not cid: messagebox.showerror("Bad URL", "Can't extract ID."); return
        tok, _ = load_token(self.cfg)
        if not tok: messagebox.showerror("Not logged in", "Login first."); return

        self._orig_url = url
        for w in self._q_frame.winfo_children(): w.destroy()
        tk.Label(self._q_frame, text="Fetching...", bg=BG2, fg=FG2, font=("Segoe UI",9)).pack(anchor="w",pady=6)
        self._q_vars     = []
        self._fetch_btn.configure(state="disabled")
        self._drm_keys   = []
        self._pssh       = None
        self._drm_status = "unknown"
        self._update_drm_ui()
        self._ep_info.configure(text=f"Episode ID: {cid}  ({ctype})")
        if not self._log_open: self._toggle_log()

        def _w():
            def _log(m): self.after(0, lambda m=m: self._log_w(m))

            # ── SHOW URL → open episode picker ──
            if ctype == "show":
                _log(f"[Show] Detected show URL, fetching episode list...\n")
                show_title, is_drm, ep_count, stories = fetch_show_episodes(
                    cid, self._session, _log, page_size=20, max_eps=None)
                self.after(0, lambda: self._fetch_btn.configure(state="normal"))
                if not stories:
                    self.after(0, lambda: self._show_err("No episodes found for this show"))
                    return
                self.after(0, lambda st=show_title, ec=ep_count, s=stories:
                    self._open_show_picker(cid, st, ec, s))
                return

            # ── EPISODE URL → fetch stream directly ──
            mpd_url, hls_url, ep_data = fetch_episode_stream(cid, tok, self._session, _log)
            self.after(0, lambda: self._fetch_btn.configure(state="normal"))
            self._mpd_url = mpd_url; self._hls_url = hls_url; self._episode_data = ep_data
            title = (ep_data.get("title") or ep_data.get("story_title") or
                     ep_data.get("name") or ep_data.get("episode_title") or cid)
            self._episode_title = title
            self.after(0, lambda: self._ep_info.configure(text=f"🎧 {title}  •  ID: {cid}"))

            stream = mpd_url or hls_url
            if not stream:
                self.after(0, lambda: self._show_err("No stream — episode may need premium/coins"))
                return

            quals = []
            if mpd_url:
                _log(f"[MPD] Downloading manifest\n")
                pssh, mpd_text = extract_pssh_from_mpd(mpd_url, self._session, _log)
                self._pssh     = pssh
                self._mpd_text = mpd_text
                quals          = parse_mpd_qualities(mpd_text, _log) if mpd_text else []
            self._quals = quals

            if mpd_url and self._pssh:
                show_id = self._episode_data.get("show_id", "")
                _log(f"[License] Fetching Widevine license URL (show_id={show_id[:20]})\n")
                lic = fetch_widevine_license_url(cid, show_id, self._session, _log)
                self._license_url = lic
                cdm_path = self.cfg.get("cdm_path","").strip()
                if cdm_path and os.path.exists(cdm_path):
                    self._drm_status = "fetching"
                    self.after(0, self._update_drm_ui)
                    def _auto_keys(pssh=self._pssh, lic_url=lic):
                        def _l(m): self.after(0, lambda m=m: self._log_w(m))
                        keys = get_widevine_keys(pssh, lic_url, self._session, cdm_path=cdm_path, log_cb=_l)
                        self._drm_keys   = keys
                        self._drm_status = "unlocked" if keys else "failed"
                        self.after(0, self._update_drm_ui)
                    threading.Thread(target=_auto_keys, daemon=True).start()
                else:
                    self._drm_status = "locked"
                    self.after(0, self._update_drm_ui)
            else:
                self._drm_status = "none"
                self.after(0, self._update_drm_ui)

            self.after(0, lambda: self._show_quals(quals))
        threading.Thread(target=_w, daemon=True).start()

    def _show_err(self, msg):
        for w in self._q_frame.winfo_children(): w.destroy()
        tk.Label(self._q_frame, text=f"✗ {msg}", bg=BG2, fg=RED, font=("Segoe UI",9)).pack(anchor="w")

    def _show_quals(self, quals):
        for w in self._q_frame.winfo_children(): w.destroy()
        self._q_vars = []
        if quals:
            hdr = tk.Frame(self._q_frame, bg=BG2); hdr.pack(fill="x")
            q_type = quals[0].get("type", "audio") if quals else "audio"
            if q_type == "video":
                cols = [("   ",3),("Quality",8),("Bitrate",12),("Est. Size",10)]
            else:
                cols = [("   ",3),("Bitrate",10),("Ch",6),("Codec",15),("Est. Size",10)]
            for txt, w in cols:
                tk.Label(hdr, text=txt, bg=BG2, fg=FG3, font=("Segoe UI",8),
                         width=w, anchor="w").pack(side="left")
            tk.Frame(self._q_frame, bg=BG3, height=1).pack(fill="x", pady=(3,3))
            for i, q in enumerate(quals):
                var = tk.BooleanVar(value=(i==0))
                self._q_vars.append(var)
                CheckRow(self._q_frame, var, q=q,
                         is_top=(i==0)).pack(fill="x", pady=1)
        else:
            var = tk.BooleanVar(value=True)
            self._q_vars.append(var)
            tk.Label(self._q_frame, text="✓  Best available (auto)", bg=BG2, fg=FG,
                     font=MONO, anchor="w").pack(side="left",padx=6,pady=4)

    def _cancel_dl(self):
        self._cancel.set()
        self._dl_status.configure(text="Cancelling...", fg=YLW)

    def _start_dl(self):
        if self._dl_thread and self._dl_thread.is_alive():
            messagebox.showinfo("Busy","Download already running."); return
        tok, _ = load_token(self.cfg)
        if not tok: messagebox.showerror("Not logged in","Login first."); return
        stream = self._mpd_url or self._hls_url
        if not stream: messagebox.showwarning("No stream","Fetch qualities first."); return

        if self._drm_status == "locked" and not self._drm_keys:
            cdm_path = self.cfg.get("cdm_path","").strip()
            pssh = self._pssh
            if cdm_path and os.path.exists(cdm_path) and pssh:
                if not self._log_open: self._toggle_log()
                self._dl_btn.configure(state="disabled", text="Fetching keys...")
                ep_id   = extract_content_id(self._orig_url)[0] or ""
                show_id = self._episode_data.get("show_id","")
                lic = self._license_url
                def _fetch_then_dl(ep_id=ep_id, show_id=show_id):
                    def _log(m): self.after(0, lambda m=m: self._log_w(m))
                    if not lic:
                        new_lic = fetch_widevine_license_url(ep_id, show_id, self._session, _log)
                        actual_lic = new_lic
                    else:
                        actual_lic = lic
                    keys = get_widevine_keys(pssh, actual_lic, self._session, cdm_path=cdm_path, log_cb=_log)
                    def _resume():
                        self._dl_btn.configure(state="normal", text="⬇  Download")
                        if keys:
                            self._drm_keys = keys; self._drm_status = "unlocked"
                            self._update_drm_ui(); self._start_dl()
                        else:
                            messagebox.showerror("Key Fetch Failed", "Check log.")
                    self.after(0, _resume)
                threading.Thread(target=_fetch_then_dl, daemon=True).start()
                return
            else:
                if not messagebox.askyesno("DRM Warning",
                    "Stream is Widevine-encrypted, no keys fetched.\n\nDownload anyway?"): return

        selected = [(i,q) for i,(q,v) in enumerate(
            zip(self._quals if self._quals else [None]*len(self._q_vars), self._q_vars)) if v.get()]
        if not selected: messagebox.showwarning("Nothing selected","Select at least one quality."); return

        out_dir  = self._out_var.get().strip() or self.cfg.get("output_dir", APP_DIR)
        self.cfg["output_dir"] = out_dir
        cfg_snap = dict(self.cfg)
        cfg_snap["threads"] = int(self._threads_var.get())
        cfg_snap["engine"]  = self._engine_var.get()

        drm_keys  = list(self._drm_keys)
        ep_title  = self._episode_title or "episode"
        self._cancel.clear()
        self._dl_btn.configure(state="disabled", text="Downloading...")
        self._cancel_btn.pack(side="left", padx=(0,10))
        self._open_btn.configure(state="disabled")
        self._prog.configure(value=0)
        self._dl_status.configure(text="Starting...", fg=FG2)
        self._log_box.configure(state="normal"); self._log_box.delete("1.0","end"); self._log_box.configure(state="disabled")
        if not self._log_open: self._toggle_log()
        last_out = [None]

        def _work():
            all_ok = True
            for idx,(i,q) in enumerate(selected):
                if self._cancel.is_set(): break
                q_height = q["height"] if q else 0
                q_kbps   = q.get("kbps", 0) if q else 0
                if q_height:
                    q_tag = f"{q_height}p"
                elif q_kbps:
                    q_tag = f"{q_kbps} kbps"
                else:
                    q_tag = "best"
                fname    = make_filename(ep_title, q)
                self.after(0, lambda t=q_tag,n=idx+1,tot=len(selected):
                    self._dl_status.configure(text=f"[{n}/{tot}] {t}  ⬇ Downloading…", fg=FG2))
                ep_has_video = self._episode_data.get("has_video", False)
                ok, out_path = run_download(
                    stream, out_dir, fname, q, cfg_snap,
                    lambda pct,spd: self.after(0, lambda p=pct,s=spd: (
                        self._prog.configure(value=p),
                        self._prog_txt.configure(text=f"{p:.1f}%{'   '+s if s else ''}"))),
                    lambda t: self.after(0, lambda t=t: self._log_w(t)),
                    self._cancel, drm_keys=drm_keys, has_video=ep_has_video)
                if ok: last_out[0] = out_path
                else:  all_ok = False

            def _done():
                self._dl_btn.configure(state="normal", text="⬇  Download")
                self._cancel_btn.pack_forget()
                if self._cancel.is_set():
                    self._dl_status.configure(text="Cancelled", fg=YLW)
                elif all_ok:
                    self._prog.configure(value=100)
                    self._dl_status.configure(text="✓ Done!", fg=GRN)
                    self._open_btn.configure(state="normal")
                else:
                    self._dl_status.configure(text="✗ Failed — check log", fg=RED)
                self._refresh_status()
            self.after(0, _done)

        self._dl_thread = threading.Thread(target=_work, daemon=True)
        self._dl_thread.start()

    def _open_folder(self):
        d = self._out_var.get() or self.cfg.get("output_dir","")
        if d and os.path.isdir(d):
            if sys.platform == "win32":    os.startfile(d)
            elif sys.platform == "darwin": subprocess.Popen(["open", d])
            else:                          subprocess.Popen(["xdg-open", d])

    def _cfg_browse(self, key, var):
        if any(x in key for x in ("dir","folder","output")):
            d = filedialog.askdirectory()
            if d: var.set(d)
        else:
            f = filedialog.askopenfilename(filetypes=[("All","*.*"),("Exe","*.exe"),("WVD","*.wvd")])
            if f: var.set(f)

    def _save_cfg(self):
        for k,v in self._cfg_vars.items(): self.cfg[k] = v.get()
        self.cfg["threads"] = int(self._threads_var.get())
        self.cfg["engine"]  = self._engine_var.get()
        self._out_var.set(self.cfg.get("output_dir",""))
        save_cfg(self.cfg)
        self._cfg_msg.configure(text="✓ Saved")
        self.after(2000, lambda: self._cfg_msg.configure(text=""))
        self._refresh_status()


if __name__ == "__main__":
    app = App()
    app.mainloop()