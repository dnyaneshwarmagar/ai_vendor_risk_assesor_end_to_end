# Incident Response Runbook

Document ID: NM-SEC-IR · Version 2026.1 · Effective 1 March 2026 · Owner: Head of Information Security

## 1. Severity and escalation

### IR-1.1 Severity levels

| Severity | Examples | Initial response |
|---|---|---|
| Critical | Confirmed customer-data breach, ransomware on production | Page on-call within 15 minutes |
| High | Suspected credential exposure, major availability outage | Page on-call within 1 hour |
| Medium | Phishing with limited impact, non-production compromise | Ticket to Security within 1 business day |
| Low | Policy violation without data exposure | Record and review in weekly Security sync |

### IR-2.1 Who to page

For **Critical** and **High** incidents involving customer personal data (tier T3), page:

1. Security on-call
2. Head of Information Security
3. DPO (when customer personal data may be affected)

For Medium and Low, the Security team lead triages without waking the DPO unless personal data is involved.

### IR-3.1 Customer notification

If customer personal data was or may have been accessed, the DPO decides whether and when customers are notified, following the Data Protection Policy. Do not notify customers from the support channel without DPO approval.
