# Groww Review Pulse — Updated Dataset

## Latest data refresh
The app now uses `Groww_Reviews_2026.csv`, with 12,995 unique reviews from 27 Jul 2026 through 18 Oct 2026. Theme labels are rule-based; existing labels are retained for matching review IDs and newly added reviews are keyword-classified. No 200-review cap is applied.

## Files
- `Groww_Reviews_source.csv` — original uploaded export.
- `groww_review_analysis.csv` — all 12,995 analyzed rows, with theme labels.
- `analysis_report.md` — validation, counts, methodology, quotes and limitations.
- `weekly_product_pulse.md` — pulse kept under 250 words.
- `fee_explainer.md` — customer-ready neutral charge explainer and official sources.
- `notes_entry_preview.json` — requested Notes/Doc fields.
- `email_draft.txt` — email draft text; never auto-sent.
- `source_list.md` — source URLs.
- `app.py` — local approval-gated prototype.
- `requirements.txt` — Python dependencies.

## Run the prototype
Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Review the pulse and fee explainer, then open **Approval & log**. The editable Notes/Doc and email drafts have separate **Approve** and **Reject** actions. Approve saves the report, log and `.eml` draft locally. Reject records the rejection and does not create an email draft. Neither action sends email; Gmail and Google Docs are not connected.


## Test the package

### 1. Run automated checks
After installing requirements, run:

```bash
python -m unittest test_milestone.py -v
python -m py_compile app.py test_milestone.py
```

The refreshed analysis contains 12,995 unique review IDs, review IDs are unique, dates cover the expected period, theme counts reconcile, the pulse is under 250 words, selected quotes appear verbatim in the source data, the Notes/Doc schema contains the required fields, and the approval gate is present.

### 2. Manually test the approval gate
1. Start the app with `streamlit run app.py`.
2. Confirm the pulse, fee explainer and email body preview are visible.
3. Leave the approval checkbox unticked. Confirm the approval button is disabled.
4. Tick the checkbox. Confirm the button becomes enabled.
5. Click the button. Confirm `approved_artifacts/notes_log.jsonl` and a timestamped `.eml` draft are created.
6. Open the `.eml` file in a text editor and confirm the subject starts with `Weekly Product Pulse + Customer Clarification —` and the body includes the pulse and fee explanation.
7. Confirm no email was sent. The prototype only writes local files.

The test suite does not require Streamlit to run; the interactive app does. If `streamlit` is not installed, run `pip install -r requirements.txt` first.

## Where approval occurs
The checkbox and button in `app.py` are the approval gate. The write action is disabled until the checkbox is selected. Generated approval outputs are isolated in `approved_artifacts/`; the provided `email_draft.txt` remains the unapproved preview artifact.

## Fee issue selected
Reviews repeatedly mention brokerage and additional charges (DP/statutory/exchange-related charges). The customer explanation distinguishes brokerage from other possible transaction charges and directs customers to Groww's official pricing/help pages. The reviews are customer perceptions; they do not prove that any particular charge was incorrect.

## Method and limitations
- Validated review dates and ratings; deduplicated by `reviewId`.
- Used a 12-week cutoff of 24 Jul 2026, matching the milestone's 8–12-week recency requirement.
- Theme assignment uses transparent keyword rules, with first-match priority. It is a reproducible prototype baseline, not expert-verified semantic clustering.
- Generic reviews dominate the catch-all category. Interpret its count as non-specific feedback, not a cohesive product issue.
- No arbitrary 200-review cap was applied.
- Approval workflow is local simulation, not a live MCP/Docs/Notes/Gmail integration. No email is sent.


## UI polish update
- Sidebar now shares the main warm off-white canvas, with a subtle divider instead of a contrasting panel.
- Sidebar navigation buttons use explicit readable text/background colors, including active, inactive, and hover states, to avoid dark-tab/low-contrast text.


## Global UI consistency update
- Main canvas and sidebar now use the same warm off-white background across every navigation page.
- Sidebar navigation uses a soft coral selected state and readable charcoal text.
- Primary charcoal buttons use white high-contrast labels; disabled buttons use readable muted text.

## UI readability fixes (v7)
- Explicit light theme and text contrast for metric widgets, JSON/code previews, expanders and disabled fields.
- Weekly pulse and fee explainer now use Streamlit containers, preventing blank space caused by HTML wrappers split across separate Streamlit elements.
- Approval previews use readable JSON and a disabled text area for the email body.
- Groww Pulse branding uses dark text on the light sidebar; sidebar tab borders remain removed while the outer divider stays.
- Removed dark top header/toolbar styling globally.


## Button border fix (v8)
- Removed the accidental border/background styling from button label elements (`p`/`span`); only the outer button surface has a border.
- Applied consistently to overview navigation shortcuts, review pagination, fee issue pagination, downloads and other Streamlit buttons across all pages.
- Kept the sidebar divider unchanged; this fix targets the unwanted grey boxes around button text.
- Added `requirements.txt` to the project folder for setup.

### Approval & log behavior
The Approval & log tab includes editable Notes/Doc and email draft text areas. Approving saves the edited report as a local Markdown file, records the edited content in `outputs/notes_log.jsonl`, and saves an editable email draft as `.eml`. This is a local simulation only: no Google Docs/Notes or Gmail service is connected, and no email is sent automatically.


Approval decisions: **Approve** saves the edited Notes/Doc report, approval log, and `.eml` email draft locally. **Reject** records the rejection in the local log and does not create an email draft. Neither action sends email or connects to Gmail/Google Docs.


## Optional: Connect Gmail to create drafts after approval

The **Connect Gmail** button uses Google OAuth and the Gmail API `gmail.compose` scope. It creates drafts in the connected account's Drafts folder only. It never sends email. If Gmail is not connected, Approve continues to save the local `.eml` draft and local report.

### Google Cloud setup
1. Open Google Cloud Console and create/select a project.
2. Enable the **Gmail API** for the project.
3. Configure the OAuth consent screen. While the app is in Testing, add the Google account you will use as a test user.
4. Create an OAuth client ID of type **Web application**.
5. Add the app's exact URL as an Authorized redirect URI. For local development, use `http://localhost:8501`; for Streamlit Community Cloud, use your deployed app URL (the exact callback URL must match the `redirect_uri` in secrets).
6. In the project root, create `.streamlit/secrets.toml` (do not commit this file) with:

```toml
[gmail]
client_id = "YOUR_GOOGLE_OAUTH_CLIENT_ID"
client_secret = "YOUR_GOOGLE_OAUTH_CLIENT_SECRET"
redirect_uri = "http://localhost:8501"
```

For Streamlit Community Cloud, add the same `[gmail]` values under **App settings → Secrets**, and set `redirect_uri` to the deployed app URL. Keep the client secret private; never put it in source code or a public GitHub repository.

### Use
1. Run `pip install -r requirements.txt` and restart the app.
2. Open **Approval & log** and click **Connect Gmail**.
3. Sign in to Google and grant the requested Gmail draft permission.
4. Review the report and email, tick the approval checkbox, and click **Approve**.
5. Open Gmail → Drafts to review the new draft. The app does not send it.

The OAuth token is held in the current Streamlit session; the user may need to reconnect after the session expires or the app restarts. If your Google OAuth app is still in Testing, Google may expire refresh tokens after seven days, so reconnect when prompted.


## Fix: `ModuleNotFoundError: No module named 'google.oauth2'`

This means the Google authentication dependency is not installed in the Python environment running Streamlit. From the project folder, run:

```bash
python -m pip install -r requirements.txt
```

Or install the Gmail packages directly:

```bash
python -m pip install --upgrade google-auth google-auth-oauthlib google-api-python-client
```

Then stop and restart the app using the same environment:

```bash
streamlit run app.py
```

The app now also handles missing Gmail libraries without crashing at startup and displays an install instruction in the Gmail connection panel.
