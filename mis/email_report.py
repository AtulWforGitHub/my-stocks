"""Mobile-friendly HTML email + plain-text twin. Ranked by materiality. Never built for synthetic data."""
from __future__ import annotations
import html

C = {"CRITICAL": "#b3261e", "HIGH": "#8a5700", "MEDIUM": "#0b5d7a", "LOW": "#566670"}


def _u(u):
    from .news import safe_url
    return html.escape(safe_url(u) or "#")


def _e(x):
    return html.escape("" if x is None else str(x))


def render(summary: dict, items: list[dict], url: str, kind: str, portfolio: dict | None = None) -> tuple[str, str]:
    """summary: mode, run_date, price_date, provider, market_risk, headlines(list), stale_note. kind: urgent|update|weekly."""
    if summary["mode"] != "real":
        raise ValueError("refusing to build an email from synthetic/demo data")
    title = {"urgent": "Urgent: critical risk to review", "update": "What changed", "weekly": "Weekly summary"}[kind]
    top = [i for i in items if i["category"] != "none"][:6]
    stale = summary.get("stale_note")
    text = [f"MIS {title} - {summary['run_date']} (market data as of {summary['price_date']}; source: {summary['provider']})",
            "Research and decision support, not personalised financial advice.", ""]
    parts = [f"<h2 style='margin:0 0 4px;font-size:20px'>{_e(title)}</h2><p style='margin:0 0 14px;color:#566670'>Market data as of {_e(summary['price_date'])}. "
             f"Source: {_e(summary['provider'])} (delayed, unofficial).</p>"]
    if stale:
        parts.append(f"<p style='background:#fff2d1;padding:8px 10px'>{_e(stale)}</p>"); text.append("NOTE: " + stale)

    def section(h, rows_html, rows_text):
        if rows_text:
            parts.append(f"<h3 style='margin:18px 0 6px;font-size:16px'>{_e(h)}</h3>" + rows_html); text.append(h.upper()); text.extend(rows_text); text.append("")

    def card(i):
        c = C.get(i["level"], "#566670")
        return (f"<div style='border-left:4px solid {c};padding:6px 10px;margin:6px 0;background:#f6f8f9'><b>{_e(i['title'])}</b><br>"
                f"<span style='color:#13202a'>{_e(i['reason'])}</span><br><span style='color:#566670;font-size:13px'>Changed: {_e(i['changed'])}. Evidence: {_e(i['evidence'])}"
                f"{' (' + _e(i['asof']) + ')' if i.get('asof') else ''}. Confidence: {_e(i['confidence'])}.</span><br>"
                f"<span style='font-size:13px'>Next: {_e(i['next_step'])}</span> "
                f"<a href='{_e(url)}{_e(i['link']) if str(i['link']).startswith('#') else ''}' style='font-size:13px'>Open analysis</a></div>")

    def ctext(i):
        return f"[{i['level']}] {i['title']}: {i['reason']} | Changed: {i['changed']} | Next: {i['next_step']} | Confidence: {i['confidence']}"
    if top:
        section("Needs your attention (ranked by materiality)", "".join(card(i) for i in top), [ctext(i) for i in top])
    else:
        section("Needs your attention", "<p>No material changes detected.</p>", ["No material changes detected."])
    if portfolio and not portfolio.get("error"):
        acts = portfolio.get("actions", [])
        ph = (f"<p>Value Rs {portfolio['value']:,.0f}, invested Rs {portfolio['invested']:,.0f}. "
              + (f"Today's change about Rs {portfolio['dayChange']:,.0f}. " if portfolio.get("dayChange") is not None else "")
              + (f"{len(portfolio.get('missing', []))} holding(s) lack a price. " if portfolio.get("missing") else "") + "</p>")
        ph += "".join(f"<div style='margin:4px 0'><b>{_e(a['name'])}</b>: {_e(a['action'])}. {_e(' '.join(a['reasons'][:1]))} {_e(a.get('priceNote', ''))} <i>(confidence {_e(a['confidence'])})</i></div>" for a in acts)
        pt = [f"Value Rs {portfolio['value']:,.0f}; invested Rs {portfolio['invested']:,.0f}"] + [f"{a['name']}: {a['action']}. {' '.join(a['reasons'][:1])} {a.get('priceNote', '')}" for a in acts]
        for b in portfolio.get("breaches", []):
            ph += f"<div style='color:#8a5700'>Limit: {_e(b['subject'])} at {b['value']:.1f}% (limit {b['limit']}%)</div>"; pt.append(f"Limit breach: {b['subject']} {b['value']:.1f}% vs {b['limit']}%")
        section("Your portfolio", ph, pt)
    risk = summary.get("market_risk") or {}
    section("Market risk", f"<p>{_e(risk.get('reason', 'n/a'))}</p>", [risk.get("reason", "n/a")])
    hl = summary.get("headlines", [])[:5]
    if hl:
        section("Headlines (unverified, read the source)", "<ul>" + "".join(f"<li><a href='{_u(h['url'])}'>{_e(h['title'])}</a> <span style='color:#566670'>{_e(h['source'])}, {_e(h['published'])}</span></li>" for h in hl) + "</ul>",
                [f"- {h['title']} ({h['source']}, {h['published']})" for h in hl])
    chk = ["Is the price inside the entry range on your broker's live quote?", "Have you read the latest results and news for each name?",
           "Is this month's amount safe after emergency savings and debt?"]
    section("Before your next investment", "<ul>" + "".join(f"<li>{_e(c)}</li>" for c in chk) + "</ul>", [f"- {c}" for c in chk])
    parts.append(f"<p><a href='{_e(url)}'>Open the dashboard</a></p><p style='color:#566670;font-size:12px'>Scores are not probabilities of returns. "
                 "Decisions and taxes are yours. This email never contains your holdings unless you enabled the private portfolio secret.</p>")
    text.append(f"Dashboard: {url}")
    body = ("<div style='font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:640px;margin:auto;padding:12px;color:#13202a'>" + "".join(parts) + "</div>")
    return body, "\n".join(text)
