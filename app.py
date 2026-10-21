import base64
import json
import re
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    GMAIL_LIBRARIES_AVAILABLE = True
except ImportError:
    Credentials = None
    Flow = None
    build = None
    GMAIL_LIBRARIES_AVAILABLE = False

import pandas as pd
import streamlit as st

BASE = Path(__file__).parent
OUTPUTS = BASE / "approved_artifacts"
GMAIL_TOKEN_PATH = BASE / ".streamlit" / "gmail_token.json"
GMAIL_STATE_PATH = BASE / ".streamlit" / "gmail_oauth_state.json"
ANALYSIS_PATH = BASE / "groww_review_analysis.csv"
SOURCE_PATH = BASE / "Groww_Reviews_source.csv"

st.set_page_config(page_title="Groww | Review Intelligence", page_icon="◈", layout="wide", initial_sidebar_state="expanded")


# --- Gmail draft integration (OAuth; drafts only, never sends) ---
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/userinfo.email", "openid"]

def gmail_oauth_settings():
    """Read OAuth settings from Streamlit secrets; never hardcode credentials."""
    if not GMAIL_LIBRARIES_AVAILABLE:
        return None
    try:
        cfg = st.secrets["gmail"]
        return {
            "client_id": str(cfg["client_id"]),
            "client_secret": str(cfg["client_secret"]),
            "redirect_uri": str(cfg["redirect_uri"]),
        }
    except Exception:
        return None

def gmail_oauth_flow(state=None):
    cfg = gmail_oauth_settings()
    if not cfg:
        return None
    client_config = {
        "web": {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [cfg["redirect_uri"]],
        }
    }
    flow = Flow.from_client_config(
        client_config, scopes=GMAIL_SCOPES, state=state
    )
    flow.redirect_uri = cfg["redirect_uri"]
    return flow

def gmail_credentials():
    """Load OAuth credentials from this local app's private token file/session."""
    if not GMAIL_LIBRARIES_AVAILABLE:
        return None
    token_json = st.session_state.get("gmail_credentials_json")
    if not token_json and GMAIL_TOKEN_PATH.exists():
        try:
            token_json = GMAIL_TOKEN_PATH.read_text(encoding="utf-8")
            st.session_state["gmail_credentials_json"] = token_json
        except OSError:
            token_json = None
    if not token_json:
        return None
    try:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), scopes=GMAIL_SCOPES)
        # Refresh an expired access token when a refresh token is available.
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            token_json = creds.to_json()
            st.session_state["gmail_credentials_json"] = token_json
            GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GMAIL_TOKEN_PATH.write_text(token_json, encoding="utf-8")
        return creds
    except Exception:
        return None

def gmail_connected_email():
    """Return the email for the Google account linked to the saved OAuth token.

    Use Google's authenticated session so expired access tokens can be refreshed,
    and try both supported user-info endpoints. This endpoint only reads the
    signed-in account profile; it does not send or read email content.
    """
    creds = gmail_credentials()
    if not creds:
        return None
    try:
        from google.auth.transport.requests import AuthorizedSession
        session = AuthorizedSession(creds)
        for endpoint in (
            "https://openidconnect.googleapis.com/v1/userinfo",
            "https://www.googleapis.com/oauth2/v2/userinfo",
        ):
            try:
                response = session.get(endpoint, timeout=15)
                if response.ok:
                    profile = response.json()
                    email = profile.get("email")
                    if email:
                        # Persist refreshed access-token data, if the session refreshed it.
                        token_json = creds.to_json()
                        st.session_state["gmail_credentials_json"] = token_json
                        GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
                        GMAIL_TOKEN_PATH.write_text(token_json, encoding="utf-8")
                        try:
                            GMAIL_TOKEN_PATH.chmod(0o600)
                        except OSError:
                            pass
                        return email
            except Exception:
                continue
    except Exception:
        pass
    return None

def gmail_create_draft(subject, body, recipient):
    """Create a Gmail Draft only. This function does not send email."""
    if not GMAIL_LIBRARIES_AVAILABLE:
        raise RuntimeError("Gmail libraries are missing. Install requirements.txt and restart Streamlit.")
    creds = gmail_credentials()
    if not creds:
        raise RuntimeError("Gmail is not connected in this session.")
    msg = EmailMessage()
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    result = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return result.get("id", "")

# Handle the OAuth redirect back from Google. Persist state/token locally because
# some browser/Streamlit OAuth round-trips create a fresh session.
if "error" in st.query_params:
    oauth_error = st.query_params.get("error", "Google authorization was denied.")
    st.session_state["gmail_oauth_error"] = str(oauth_error)
    st.query_params.clear()
elif "code" in st.query_params:
    returned_state = st.query_params.get("state", "")
    expected_state = st.session_state.get("gmail_oauth_state", "")
    saved_oauth = {}
    if GMAIL_STATE_PATH.exists():
        try:
            saved_oauth = json.loads(GMAIL_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            saved_oauth = {}
    if not expected_state:
        expected_state = saved_oauth.get("state", "")
    try:
        if not expected_state or returned_state != expected_state:
            raise RuntimeError("Google sign-in state did not match. Please click Connect Gmail again.")
        flow = gmail_oauth_flow(state=expected_state)
        if flow is None:
            raise RuntimeError("Gmail OAuth secrets are not configured.")
        # Google OAuth uses PKCE; the verifier created before redirect must be
        # restored on the callback before exchanging the authorization code.
        saved_verifier = saved_oauth.get("code_verifier")
        if not saved_verifier:
            raise RuntimeError("OAuth code verifier is missing. Click Connect Gmail again after updating the app.")
        flow.code_verifier = saved_verifier
        flow.fetch_token(code=st.query_params.get("code"))
        creds = flow.credentials
        token_json = creds.to_json()
        st.session_state["gmail_credentials_json"] = token_json
        GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GMAIL_TOKEN_PATH.write_text(token_json, encoding="utf-8")
        try:
            GMAIL_TOKEN_PATH.chmod(0o600)
        except OSError:
            pass
        st.session_state.pop("gmail_oauth_state", None)
        try:
            GMAIL_STATE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        st.query_params.clear()
        st.session_state["gmail_connected_notice"] = True
        st.rerun()
    except Exception as exc:
        st.query_params.clear()
        st.session_state["gmail_oauth_error"] = str(exc)


# --- Visual system ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root { --ink:#202321; --muted:#747a75; --paper:#f7f6f2; --card:#ffffff; --line:#e9e7e0; --coral:#e7654f; --mint:#dff1e6; color-scheme:light; }
html, body, [class*="css"] { font-family:'DM Sans', sans-serif; color:var(--ink); }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
  background:var(--paper) !important; color:var(--ink) !important;
}
.block-container { padding-top:1.4rem; padding-bottom:3rem; max-width:1440px; }
h1,h2,h3,h4 { font-family:'Space Grotesk',sans-serif !important; letter-spacing:-.035em; color:var(--ink) !important; }
p, li, label, [data-testid="stCaptionContainer"], [data-testid="stMarkdownContainer"] { color:var(--ink); }
[data-testid="stSidebar"], [data-testid="stSidebar"] > div,
[data-testid="stSidebar"] [data-testid="stSidebarContent"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
  background:var(--paper) !important; background-color:var(--paper) !important;
}
[data-testid="stSidebar"] {
  display:block !important; visibility:visible !important; opacity:1 !important;
  transform:none !important; width:18rem !important; min-width:18rem !important;
  border-right:1px solid var(--line) !important; box-shadow:none !important;
}
[data-testid="stSidebar"] > div { width:18rem !important; }
[data-testid="stSidebarCollapsedControl"] { display:none !important; }
[data-testid="stSidebar"] [data-testid="stSidebarContent"] { border-right:0 !important; box-shadow:none !important; }
[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] { border:0 !important; box-shadow:none !important; }
header[data-testid="stHeader"], [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
  background:var(--paper) !important; background-color:var(--paper) !important; border:0 !important; box-shadow:none !important;
}
header[data-testid="stHeader"] { height:0 !important; min-height:0 !important; }
[data-testid="stToolbar"] { visibility:hidden !important; height:0 !important; }
[data-testid="stDecoration"] { display:none !important; }
.brand { color:var(--ink) !important; font-family:'Space Grotesk',sans-serif; font-size:1.45rem; font-weight:700; letter-spacing:-.05em; padding:.35rem 0 1rem; }
.brand span { color:var(--coral) !important; }
.eyebrow { text-transform:uppercase; font-size:.72rem; letter-spacing:.16em; color:var(--coral) !important; font-weight:700; }
.hero { background:linear-gradient(120deg,#fff0e8 0%,#f8dfd1 100%); border:1px solid #f2d4c7; border-radius:24px; padding:2rem 2.2rem; margin:.25rem 0 1.2rem; }
.hero h1 { font-size:clamp(2rem,4vw,3.6rem); line-height:1.02; margin:.55rem 0 .8rem; max-width:750px; }
.hero p { color:#5c625e !important; max-width:650px; font-size:1rem; line-height:1.65; }
.metric { background:white; border:1px solid var(--line); border-radius:17px; padding:1.05rem 1.15rem; height:132px; box-sizing:border-box; display:flex; flex-direction:column; }
.metric-label { color:var(--muted) !important; font-size:.78rem; font-weight:600; }
.metric-value { color:var(--ink) !important; font-family:'Space Grotesk',sans-serif; font-size:1.9rem; font-weight:700; letter-spacing:-.05em; margin:.25rem 0; }
.metric-note { color:var(--muted) !important; font-size:.75rem; line-height:1.35; margin-top:auto; padding-top:.25rem; }
.panel { background:white; color:var(--ink); border:1px solid var(--line); border-radius:18px; padding:1.2rem 1.3rem; margin-bottom:1rem; }
.explore-card { height:246px; box-sizing:border-box; overflow:hidden; }
.review-card { background:white; border:1px solid var(--line); border-radius:15px; padding:1rem 1.15rem; margin:.55rem 0; color:var(--ink); }
.review-meta { color:var(--muted) !important; font-size:.78rem; }
.pill { display:inline-block; background:#fce7e1; color:#a83c2b !important; border-radius:999px; padding:.2rem .55rem; font-size:.72rem; font-weight:700; }
.small-muted { color:var(--muted) !important; font-size:.82rem; }

/* Fix clipped long labels in Streamlit/BaseWeb select dropdown menus. */
div[data-baseweb="popover"],
div[data-baseweb="popover"] > div,
div[data-baseweb="menu"],
ul[role="listbox"] {
  width: max-content !important;
  min-width: 300px !important;
  max-width: min(420px, 90vw) !important;
}
div[data-baseweb="popover"] ul[role="listbox"],
ul[role="listbox"] {
  box-sizing: border-box !important;
}
ul[role="listbox"] li,
ul[role="listbox"] [role="option"],
div[role="listbox"] [role="option"],
div[data-baseweb="menu"] [role="option"],
div[data-baseweb="popover"] [role="option"] {
  box-sizing: border-box !important;
  width: 100% !important;
  height: auto !important;
  min-height: 36px !important;
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
  overflow-wrap: anywhere !important;
  word-break: normal !important;
  line-height: 1.35 !important;
  padding-top: 8px !important;
  padding-bottom: 8px !important;
}
ul[role="listbox"] li > div,
ul[role="listbox"] [role="option"] > div,
div[data-baseweb="popover"] [role="option"] > div,
div[data-baseweb="menu"] [role="option"] > div {
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
  overflow-wrap: anywhere !important;
  max-width: 100% !important;
}
/* Button surface owns the border. Never put a border/background on its text node:
   that creates the unwanted little grey rectangle around labels in Streamlit. */
.stApp div.stButton > button, .stApp div.stDownloadButton > button {
  color:#30332f !important; background:#ffffff !important; border:1px solid #dedbd2 !important;
  box-shadow:none !important; outline:0 !important; opacity:1 !important;
}
.stApp div.stButton > button p, .stApp div.stButton > button span,
.stApp div.stDownloadButton > button p, .stApp div.stDownloadButton > button span {
  color:inherit !important; background:transparent !important; border:0 !important;
  outline:0 !important; box-shadow:none !important; text-decoration:none !important;
}
.stApp div.stButton > button[kind="primary"], .stApp div.stDownloadButton > button[kind="primary"] {
  color:#ffffff !important; background:#202321 !important; border-color:#202321 !important;
}
.stApp div.stButton > button[kind="primary"] p, .stApp div.stButton > button[kind="primary"] span,
.stApp div.stDownloadButton > button[kind="primary"] p, .stApp div.stDownloadButton > button[kind="primary"] span {
  color:#ffffff !important; background:transparent !important; border:0 !important;
}
.stApp div.stButton > button:disabled {
  color:#777c78 !important; background:#efeee9 !important; border-color:#e3e0d8 !important; opacity:1 !important;
}
.stApp div.stButton > button:disabled p, .stApp div.stButton > button:disabled span {
  color:#777c78 !important; background:transparent !important; border:0 !important;
}

.stApp div.stButton > button p:focus, .stApp div.stButton > button span:focus,
.stApp div.stDownloadButton > button p:focus, .stApp div.stDownloadButton > button span:focus {
  outline:0 !important; border:0 !important; box-shadow:none !important;
}
.stApp div.stButton > button:focus-visible, .stApp div.stDownloadButton > button:focus-visible {
  outline:2px solid #e7654f !important; outline-offset:2px !important;
}

/* Sidebar tab borders removed; keep the subtle outer divider only. */
[data-testid="stSidebar"] div.stButton > button, [data-testid="stSidebar"] div.stButton > button p,
[data-testid="stSidebar"] div.stButton > button span {
  color:#30332f !important; background:transparent !important; border:0 !important; outline:0 !important; box-shadow:none !important; opacity:1 !important;
}
[data-testid="stSidebar"] div.stButton > button:hover, [data-testid="stSidebar"] div.stButton > button:hover p,
[data-testid="stSidebar"] div.stButton > button:hover span {
  color:#a83c2b !important; background:#fce7e1 !important;
}
[data-testid="stSidebar"] div.stButton > button[kind="primary"],
[data-testid="stSidebar"] div.stButton > button[kind="primary"] p,
[data-testid="stSidebar"] div.stButton > button[kind="primary"] span {
  color:#a83c2b !important; background:#fce7e1 !important; border:0 !important;
}
/* Streamlit-native metrics, JSON, expanders, text previews and code blocks stay legible. */
[data-testid="stMetric"], [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
[data-testid="stMetricDelta"], [data-testid="stMetric"] label,
[data-testid="stMetric"] div, [data-testid="stMetric"] p {
  color:var(--ink) !important;
}
[data-testid="stMetricValue"] {
  white-space:nowrap !important;
  overflow:visible !important;
  text-overflow:clip !important;
  font-size:clamp(1.6rem, 2.3vw, 2.25rem) !important;
}
[data-testid="stJson"], [data-testid="stJson"] * {
  color:var(--ink) !important; background:#ffffff !important;
}
[data-testid="stCode"], [data-testid="stCode"] * {
  color:#202321 !important; background:#ffffff !important;
}
[data-testid="stText"], [data-testid="stText"] *, [data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input {
  color:#202321 !important; background:#ffffff !important; -webkit-text-fill-color:#202321 !important;
}
[data-testid="stExpander"], [data-testid="stExpander"] summary,
[data-testid="stExpander"] details, [data-testid="stExpander"] p {
  color:#202321 !important; background:#ffffff !important;
}
[data-testid="stAlert"], [data-testid="stAlert"] * { color:#202321 !important; }
hr { border-color:var(--line) !important; }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_reviews():
    path = ANALYSIS_PATH if ANALYSIS_PATH.exists() else SOURCE_PATH
    data = pd.read_csv(path)
    rename = {}
    for c in data.columns:
        low = c.lower().replace("_", " ").strip()
        if low in ("review date", "date", "at", "created at"): rename[c] = "Review Date"
        elif low in ("rating", "score", "stars"): rename[c] = "Rating"
        elif low in ("review", "content", "text", "content text"): rename[c] = "Review"
        elif low in ("theme", "cluster"): rename[c] = "theme"
        elif low in ("reviewid", "review id", "id"): rename[c] = "reviewId"
    data = data.rename(columns=rename)
    for c, default in [("Review Date", ""), ("Rating", 0), ("Review", ""), ("theme", "Unclassified"), ("reviewId", "")]:
        if c not in data.columns: data[c] = default
    data["Review"] = data["Review"].fillna("").astype(str)
    data["Rating"] = pd.to_numeric(data["Rating"], errors="coerce").fillna(0).astype(int)
    data["Review Date"] = pd.to_datetime(data["Review Date"], errors="coerce")
    data["theme"] = data["theme"].fillna("Unclassified").astype(str)
    data = data.drop_duplicates(subset=["reviewId"] if data["reviewId"].astype(str).str.len().gt(0).any() else ["Review", "Review Date", "Rating"])
    return data

df = load_reviews()
if "page" not in st.session_state: st.session_state.page = "Overview"
if "review_page" not in st.session_state: st.session_state.review_page = 1
if "approved" not in st.session_state: st.session_state.approved = False

pulse_path = BASE / "weekly_product_pulse.md"
fee_path = BASE / "fee_explainer.md"
entry_path = BASE / "notes_entry_preview.json"
pulse_text = pulse_path.read_text(encoding="utf-8") if pulse_path.exists() else "Weekly pulse is not available yet."
fee_text = fee_path.read_text(encoding="utf-8") if fee_path.exists() else "Fee explainer is not available yet."
entry = json.loads(entry_path.read_text(encoding="utf-8")) if entry_path.exists() else {}

fee_pattern = re.compile(r"\b(brokerage|brokerage charges?|dp charges?|depository|deduct(?:ed|ion|ions)?|hidden charges?|transaction charges?|charge[s]?|levies|gst|stt|stamp duty|square.?off|subscription fee|fees?)\b", re.I)
fee_df = df[df["Review"].str.contains(fee_pattern, na=False)].copy()
if not fee_df.empty:
    # Prioritize reviews explicitly describing confusion/unexpected charges.
    confusion_pattern = re.compile(r"\b(hidden|unexpected|not expected|didn.t expect|why.*charge|extra|charged|deduct|bina bataye|pata nahi|too much|more than|confus|unclear|surprise)\b", re.I)
    fee_df["fee_confusion"] = fee_df["Review"].str.contains(confusion_pattern, na=False)
else:
    fee_df["fee_confusion"] = False

with st.sidebar:
    st.markdown('<div class="brand">◈ Groww<span>.</span> Pulse</div>', unsafe_allow_html=True)
    st.markdown('<div class="small-muted">CUSTOMER VOICE WORKSPACE</div>', unsafe_allow_html=True)
    st.divider()
    nav = [
        ("Overview", "Overview"),
        ("All reviews", "Reviews"),
        ("Themes", "Themes"),
        ("Fee issue", "Fee issue"),
        ("Weekly pulse", "Weekly pulse"),
        ("Fee explainer", "Fee explainer"),
        ("Approval & log", "Approval & log"),
    ]
    for label, value in nav:
        if st.button(("●  " if st.session_state.page == value else "   ") + label, key=f"nav_{value}", use_container_width=True,
                     type="primary" if st.session_state.page == value else "secondary"):
            st.session_state.page = value
            st.rerun()
    st.divider()
    dates = df["Review Date"].dropna()
    date_text = f"{dates.min():%d %b} – {dates.max():%d %b %Y}" if not dates.empty else "Dates unavailable"
    st.markdown(f'<div class="panel"><div class="eyebrow">ACTIVE DATASET</div><b>Groww · Public reviews</b><p class="small-muted">{len(df):,} reviews<br>{date_text}</p></div>', unsafe_allow_html=True)
    

def metric(label, value, note):
    st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>', unsafe_allow_html=True)

def render_reviews(data, keyprefix="reviews", page_size=10):
    if data.empty:
        st.info("No reviews match these filters.")
        return
    total_pages = max(1, (len(data) + page_size - 1) // page_size)
    page_key = f"{keyprefix}_page"
    if page_key not in st.session_state: st.session_state[page_key] = 1
    st.session_state[page_key] = min(st.session_state[page_key], total_pages)
    start = (st.session_state[page_key] - 1) * page_size
    for _, row in data.iloc[start:start + page_size].iterrows():
        date = row["Review Date"].strftime("%d %b %Y") if pd.notna(row["Review Date"]) else "Date unavailable"
        stars = "★" * max(0, min(5, int(row["Rating"]))) + "☆" * (5 - max(0, min(5, int(row["Rating"]))))
        theme = row["theme"]
        text = row["Review"]
        if len(text) > 1000: text = text[:1000] + "…"
        st.markdown(f'<div class="review-card"><div class="review-meta"><span style="color:#d75e49">{stars}</span> &nbsp; {date} &nbsp; <span class="pill">{theme}</span></div><div style="margin-top:.6rem;line-height:1.55">{text}</div></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("← Previous", key=f"{keyprefix}_prev", disabled=st.session_state[page_key] <= 1, use_container_width=True):
            st.session_state[page_key] -= 1
            st.rerun()
    with c2:
        st.markdown(f"<p style='text-align:center;color:#747a75;padding-top:.5rem'>Page {st.session_state[page_key]} of {total_pages} · {len(data):,} matching reviews</p>", unsafe_allow_html=True)
    with c3:
        if st.button("Next →", key=f"{keyprefix}_next", disabled=st.session_state[page_key] >= total_pages, use_container_width=True):
            st.session_state[page_key] += 1
            st.rerun()

# --- Pages ---
page = st.session_state.page
if page == "Overview":
    dates = df["Review Date"].dropna()
    start = dates.min().strftime("%d %b %Y") if not dates.empty else "—"
    end = dates.max().strftime("%d %b %Y") if not dates.empty else "—"
    avg = df.loc[df["Rating"].between(1,5), "Rating"].mean()
    low = df["Rating"].isin([1,2]).mean() * 100 if len(df) else 0
    st.markdown(f'<div class="hero"><div class="eyebrow">WEEKLY CUSTOMER SIGNAL · GROWW</div><h1>Every review leaves a signal.<br>Find the ones that matter.</h1><p>One workspace to explore customer feedback, spot recurring product friction, explain charges clearly, and prepare a weekly update for the team.</p><div class="small-muted">{len(df):,} reviews · {start} – {end}</div></div>', unsafe_allow_html=True)
    cols = st.columns(4)
    with cols[0]: metric("REVIEWS ANALYSED", f"{len(df):,}", "Customer reviews for the selected period")
    with cols[1]: metric("AVERAGE RATING", f"{avg:.2f} ★" if pd.notna(avg) else "—", "Across rated reviews")
    with cols[2]: metric("1–2 STAR REVIEWS", f"{low:.1f}%", "Potential friction signal")
    with cols[3]: metric("FEE-RELATED REVIEWS", f"{len(fee_df):,}", "Keyword-matched; inspect results")
    st.markdown("## Where customers are speaking")
    counts = df["theme"].value_counts().head(5)
    left, right = st.columns([1.1, .9])
    with left:
        st.markdown('<div class="panel"><h3>Theme volume</h3>', unsafe_allow_html=True)
        if not counts.empty:
            chart = counts.rename_axis("Theme").reset_index(name="Reviews")
            st.bar_chart(chart.set_index("Theme"), horizontal=True, height=270)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown('<div class="panel"><h3>Rating mix</h3>', unsafe_allow_html=True)
        ratings = df[df["Rating"].between(1,5)]["Rating"].value_counts().sort_index()
        if not ratings.empty:
            st.bar_chart(ratings.rename_axis("Stars").reset_index(name="Reviews").set_index("Stars"), height=270)
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("## Start exploring")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.markdown('<div class="panel explore-card"><div class="eyebrow">01 / EXPLORE</div><h3>Read the reviews</h3><p class="small-muted">Search the full dataset and filter by rating or theme.</p></div>', unsafe_allow_html=True)
        if st.button("Browse all reviews →", key="go_reviews", use_container_width=True): st.session_state.page="Reviews"; st.rerun()
    with c2:
        st.markdown('<div class="panel explore-card"><div class="eyebrow">02 / UNDERSTAND</div><h3>Investigate charges</h3><p class="small-muted">Focus on feedback that mentions brokerage, deductions and fees.</p></div>', unsafe_allow_html=True)
        if st.button("Explore fee issue →", key="go_fee", use_container_width=True): st.session_state.page="Fee issue"; st.rerun()
    with c3:
        st.markdown('<div class="panel explore-card"><div class="eyebrow">03 / SHARE</div><h3>Prepare the pulse</h3><p class="small-muted">Review the internal summary and proposed product actions.</p></div>', unsafe_allow_html=True)
        if st.button("Open weekly pulse →", key="go_pulse", use_container_width=True): st.session_state.page="Weekly pulse"; st.rerun()

elif page == "Reviews":
    st.markdown('<div class="eyebrow">CUSTOMER VOICE / LIBRARY</div>', unsafe_allow_html=True)
    st.title("All reviews")
    st.caption("Search and filter the uploaded public review export. The list is paginated so it remains easy to scan.")
    c1,c2,c3 = st.columns([2,1,1.35])
    with c1: query = st.text_input("Search review text", placeholder="Try: withdrawal, slow app, brokerage…", key="all_search")
    with c2: rating = st.selectbox("Rating", ["Any", "5 stars", "4 stars", "3 stars", "2 stars", "1 star"], key="all_rating")
    with c3:
        themes = ["All themes"] + sorted(df["theme"].unique().tolist())
        theme = st.selectbox("Theme", themes, key="all_theme")
    filtered = df.copy()
    if query.strip(): filtered = filtered[filtered["Review"].str.contains(re.escape(query.strip()), case=False, na=False)]
    if rating != "Any": filtered = filtered[filtered["Rating"] == int(rating[0])]
    if theme != "All themes": filtered = filtered[filtered["theme"] == theme]
    st.markdown(f"**{len(filtered):,} reviews match** your filters.")
    render_reviews(filtered, "all_reviews", 10)

elif page == "Themes":
    st.markdown('<div class="eyebrow">PATTERNS / CLUSTERS</div>', unsafe_allow_html=True)
    st.title("Themes")
    st.caption("Five keyword-rule buckets from the current analysis. Review the examples before treating a theme as a confirmed product issue.")
    total = len(df)
    for i, (theme, count) in enumerate(df["theme"].value_counts().head(5).items(), start=1):
        subset = df[df["theme"] == theme]
        share = count / total * 100 if total else 0
        avg_rating = subset.loc[subset["Rating"].between(1,5), "Rating"].mean()
        bad_share = subset["Rating"].isin([1,2]).mean()*100 if len(subset) else 0
        with st.container(border=True):
            a,b = st.columns([3,1])
            with a:
                st.markdown(f'<div class="eyebrow">THEME {i:02d}</div><h3>{theme}</h3><p class="small-muted">{count:,} reviews · {share:.1f}% of dataset</p>', unsafe_allow_html=True)
                st.progress(min(1.0, share/100))
            with b:
                st.metric("Avg. rating", f"{avg_rating:.2f} ★" if pd.notna(avg_rating) else "—")
                st.metric("1–2 stars", f"{bad_share:.1f}%")
            with st.expander("Read example reviews"):
                render_reviews(subset.sort_values("Review Date", ascending=False), f"theme_{i}", 5)

elif page == "Fee issue":
    st.markdown('<div class="eyebrow">CHARGES / CUSTOMER CONFUSION</div>', unsafe_allow_html=True)
    st.title("Fee issue")
    st.caption("A review appears here when its text mentions a fee or charge term. Confusion signals are heuristic and should be verified against the original review.")
    c1,c2 = st.columns([2,1])
    with c1:
        fee_query = st.text_input("Search within fee-related reviews", placeholder="brokerage, DP charge, deducted…", key="fee_search")
    with c2:
        confused_only = st.toggle("Likely confusion only", value=False)
    filtered = fee_df.copy()
    if fee_query.strip(): filtered = filtered[filtered["Review"].str.contains(re.escape(fee_query.strip()), case=False, na=False)]
    if confused_only: filtered = filtered[filtered["fee_confusion"]]
    n_conf = int(fee_df["fee_confusion"].sum()) if "fee_confusion" in fee_df else 0
    c1,c2,c3 = st.columns(3)
    with c1: metric("FEE-MENTIONING REVIEWS", f"{len(fee_df):,}", "Keyword-matched")
    with c2: metric("POSSIBLE CONFUSION", f"{n_conf:,}", "Heuristic; review manually")
    with c3: metric("LOW-RATING FEE REVIEWS", f"{int(fee_df['Rating'].isin([1,2]).sum()):,}", "1–2 star ratings")
    st.markdown("### Reviews to inspect")
    render_reviews(filtered.sort_values("Review Date", ascending=False), "fee_reviews", 10)
    st.info("These keyword counts are not a verified count of billing errors. Customer statements describe perceptions; check official pricing and transaction records before drawing conclusions.")

elif page == "Weekly pulse":
    st.markdown('<div class="eyebrow">INTERNAL UPDATE / WEEKLY</div>', unsafe_allow_html=True)
    st.title("Weekly product pulse")
    words = re.findall(r"\b[\w’'-]+\b", pulse_text)
    # Give the word-count metric enough room so Streamlit never truncates 250 to "25..."
    c1,c2 = st.columns([2.2,1.5])
    with c1: st.caption("A concise update for product, support and operations.")
    with c2:
        st.metric("Word count", f"{len(words)} / 250", "Milestone limit")
    with st.container(border=True):
        st.markdown(pulse_text)
    st.download_button("Download pulse (.md)", pulse_text, file_name="weekly_product_pulse.md", mime="text/markdown", type="primary")
    st.caption("Theme assignment is rule-based; quotes should be checked against the source before external use.")

elif page == "Fee explainer":
    st.markdown('<div class="eyebrow">CUSTOMER COMMUNICATION / FEES</div>', unsafe_allow_html=True)
    st.title("Fee explainer")
    st.caption("Neutral, source-linked clarification for support teams. Review current official pricing before sending to a customer.")
    with st.container(border=True):
        st.markdown(fee_text)
    st.download_button("Download fee explainer (.md)", fee_text, file_name="fee_explainer.md", mime="text/markdown", type="primary")
    st.markdown("### Official sources")
    for url in entry.get("source_links", []):
        if isinstance(url, str): st.markdown(f"- {url}")
        elif isinstance(url, dict): st.markdown(f"- [{url.get('title', url.get('label','Official source'))}]({url.get('url', url.get('href','#'))})")
    st.caption("Last-checked date is shown in the explainer. Charges and pricing can change.")

elif page == "Approval & log":
    st.markdown('<div class="eyebrow">HUMAN REVIEW / NO AUTO-SEND</div>', unsafe_allow_html=True)
    st.title("Approval & log")
    st.caption("Review the report and email, then approve. Approval saves a draft to the previously authorized Gmail account and never sends it automatically.")
    # Gmail connection controls and account identity are intentionally hidden.
    # The saved OAuth token is loaded silently; approval uses it to create a Gmail draft.
    st.session_state.pop("gmail_connected_notice", None)
    if st.session_state.get("gmail_oauth_error"):
        st.error("Gmail connection failed: " + st.session_state.pop("gmail_oauth_error"))

    def _as_text(value, fallback=""):
        if value is None:
            return fallback
        if isinstance(value, (list, tuple)):
            return "\n".join(f"- {item}" for item in value)
        return str(value)

    themes_value = entry.get("top_themes", entry.get("themes", []))
    sources_value = entry.get("source_links", entry.get("sources", []))
    explanation_value = entry.get("explanation_bullets", entry.get("fee_explanation", []))
    issue_value = entry.get("identified_fee_issue", entry.get("fee_issue", "Review fee-related customer feedback and clarify charges where needed."))

    notes_default = (
        f"# Weekly Product Pulse — Groww\n\n"
        f"**Date:** {entry.get('date', datetime.now().strftime('%d %b %Y'))}\n\n"
        f"## Top themes\n{_as_text(themes_value, 'See the weekly pulse below.')}\n\n"
        f"## Weekly product pulse\n{pulse_text.strip()}\n\n"
        f"## Identified fee issue\n{_as_text(issue_value)}\n\n"
        f"## Fee explanation\n{_as_text(explanation_value, fee_text.strip())}\n\n"
        f"## Official sources\n{_as_text(sources_value, 'See the Fee explainer tab for official source links.')}\n"
    )
    subject_default = f"Weekly Product Pulse + Customer Clarification — {entry.get('date', datetime.now().strftime('%d %b %Y'))}"
    email_default = (
        "Hello Team,\n\n"
        + pulse_text.strip()
        + "\n\nCustomer clarification:\n"
        + fee_text.strip()
        + "\n\nBest regards,\n[Your Name]\nProduct Team\n"
    )

    left, right = st.columns(2, gap="large")
    with left:
        with st.container(border=True):
            st.subheader("1. Notes / Doc draft")
            st.caption("This is the internal report. Edit the text before approving.")
            notes_content = st.text_area(
                "Notes / Doc content",
                value=notes_default,
                key="approval_notes_content",
                height=430,
                help="Edit this report. The approved version is saved locally as a Markdown file and in the approval log."
            )
    with right:
        with st.container(border=True):
            st.subheader("2. Email draft")
            st.caption("Edit the subject and body. The approved version is saved as an .eml draft; it is not sent.")
            email_subject = st.text_input(
                "Subject",
                value=subject_default,
                key="approval_email_subject"
            )
            email_body = st.text_area(
                "Email body",
                value=email_default,
                key="approval_email_body",
                height=430
            )

    st.info("Approval never sends email. If Gmail is connected, Approve also creates a draft in Gmail Drafts; otherwise it saves the .eml draft locally. Google Docs is not connected.")
    approved = st.checkbox("I reviewed the Notes/Doc report and email draft.", key="approval_check")
    approve_col, reject_col = st.columns(2, gap="medium")
    with approve_col:
        approve_clicked = st.button(
            "Approve",
            type="primary",
            disabled=not approved,
            use_container_width=True,
            key="approve_local_artifacts"
        )
    with reject_col:
        reject_clicked = st.button(
            "Reject",
            type="secondary",
            use_container_width=True,
            key="reject_local_artifacts"
        )

    if approve_clicked:
        now = datetime.now().astimezone()
        OUTPUTS.mkdir(exist_ok=True)

        record = dict(entry)
        record["approved_at"] = now.isoformat(timespec="seconds")
        record["status"] = "approved"
        record["approval_mode"] = "local_simulation"
        record["notes_content"] = notes_content
        record["email_subject"] = email_subject
        record["email_body"] = email_body

        notes_file = OUTPUTS / f"weekly_product_pulse_notes_{now.strftime('%Y%m%d_%H%M%S')}.md"
        notes_file.write_text(notes_content, encoding="utf-8")
        msg = EmailMessage()
        msg["Subject"] = email_subject
        recipient_email = gmail_connected_email() if gmail_credentials() else None
        msg["To"] = recipient_email or "[add-recipient-before-sending]"
        msg.set_content(email_body)
        draft = OUTPUTS / f"weekly_product_pulse_{now.strftime('%Y%m%d_%H%M%S')}.eml"
        draft.write_bytes(msg.as_bytes())

        gmail_draft_id = None
        gmail_draft_error = None
        if gmail_credentials():
            try:
                if not recipient_email:
                    raise RuntimeError("Could not read the connected Gmail address. Reconnect Gmail and approve the email permission.")
                gmail_draft_id = gmail_create_draft(email_subject, email_body, recipient_email)
                record["gmail_draft_id"] = gmail_draft_id
                record["approval_mode"] = "local_and_gmail_draft"
            except Exception as exc:
                gmail_draft_error = str(exc)
                record["approval_mode"] = "local_only_gmail_error"
        else:
            record["approval_mode"] = "local_simulation"

        with (OUTPUTS / "notes_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\\n")

        st.success("Approved. The report, approval log and local .eml draft were saved. No email was sent.")
        if gmail_draft_id:
            st.success("Gmail draft created successfully in the connected account's Drafts folder. It has not been sent.")
        elif gmail_draft_error:
            st.warning("Local draft saved, but Gmail draft creation failed: " + gmail_draft_error)
        else:
            st.info("Gmail isn't connected, so the email draft was saved locally only. Connect Gmail above to create drafts in Gmail.")

    if reject_clicked:
        now = datetime.now().astimezone()
        OUTPUTS.mkdir(exist_ok=True)
        record = dict(entry)
        record["rejected_at"] = now.isoformat(timespec="seconds")
        record["status"] = "rejected"
        record["approval_mode"] = "local_simulation"
        record["notes_content"] = notes_content
        record["email_subject"] = email_subject
        record["email_body"] = email_body
        with (OUTPUTS / "notes_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        st.warning("Rejected. The rejection was recorded locally. No email draft was created.")

    log = OUTPUTS / "notes_log.jsonl"
    if log.exists():
        st.markdown("### Previous local approvals")
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        st.write(f"{len(lines)} approval record(s) saved locally.")
        with st.expander("View log"):
            st.code("\n".join(lines[-10:]))

st.divider()
st.markdown('<p class="small-muted">Groww Review Intelligence · Rule-based theme assignment · Email drafts require Gmail connection · No email is sent automatically.</p>', unsafe_allow_html=True)
