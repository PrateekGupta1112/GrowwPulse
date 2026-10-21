# Groww Review Analysis — Updated 19 Oct 2026

## Executive summary
This package now uses the newly uploaded `Groww_Reviews_2026.csv` export. After removing duplicate `reviewId` values, the analyzed dataset contains **12,995 unique reviews** dated **27 Jul 2026 to 18 Oct 2026**. No 200-review cap was applied.

## Data validation
- Uploaded file: `Groww_Reviews_2026.csv`
- Unique reviews analyzed: 12,995
- Date range: 27 Jul 2026–18 Oct 2026
- Unique review IDs: 12,995
- Mean rating: 4.40/5
- Reviews rated 1–2 stars: 1,564 (12.0%)
- Ratings:
| Rating | Count |
|---|---:|
| 1★ | 1,347 |
| 2★ | 217 |
| 3★ | 360 |
| 4★ | 1,046 |
| 5★ | 10,025 |

## Theme buckets
| Theme | Count | Share |
|---|---:|---:|
| General app experience / mixed feedback | 10,943 | 84.2% |
| Trading & order execution | 858 | 6.6% |
| Account, KYC & support | 560 | 4.3% |
| Fees & charge transparency | 362 | 2.8% |
| App stability & performance | 272 | 2.1% |
These are rule-based buckets, not human-verified semantic clusters. Existing theme labels were retained for review IDs that appeared in the previous analysis; newly added review IDs were classified using first-match keyword rules. General/mixed feedback is a catch-all and should not be read as one specific product issue.

## Sample review excerpts
- **Fees / charges** — 18 Oct 2026, rating 1★: “worest broker charges to High customer support nill”
- **Stability** — 16 Oct 2026, rating 1★: “It very bad app for stock . Because at last moment it technical issues. It doesn't use and coustomer services is not good. bad mutual funds. because my found is...”
- **Account / support** — 18 Oct 2026, rating 1★: “worst service, withdrawal amount is not created after 1month also”

## Fee-related feedback
The current dataset has 338 reviews matching the fee/charge keyword pattern. This is a keyword count, not a verified count of billing errors. Customer comments express perceptions and should be checked against official pricing and transaction details.

## Deliverables
- `Groww_Reviews_source.csv` — refreshed uploaded export.
- `groww_review_analysis.csv` — all analyzed reviews with theme labels.
- `weekly_product_pulse.md` — refreshed pulse.
- `fee_explainer.md` — neutral explainer with official source links.
- `app.py` — local approval-gated Streamlit prototype.
- `source_list.md` — source references.

## Prototype limitation
Approval is simulated locally. It does not connect to live Google Docs/Notes or Gmail and does not send email.
