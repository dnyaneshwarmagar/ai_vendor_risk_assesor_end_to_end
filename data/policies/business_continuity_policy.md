# Business Continuity and Backup Policy

Document ID: NM-BC-POL · Version 2026.1 · Effective 1 April 2026 · Owner: Head of Information Security

## 1. Recovery objectives

### BC-1.1 RTO and RPO for customer systems

Production systems that process customer personal data must meet:

| Objective | Target |
|---|---|
| Recovery Time Objective (RTO) | 4 hours |
| Recovery Point Objective (RPO) | 1 hour |

Vendors that hold customer personal data for Nimbu Mart must document how they meet these targets in the security questionnaire.

### BC-2.1 Backup retention

Backups of systems with customer personal data are retained for **90 days**, encrypted at rest, and tested for restore at least once per quarter. Longer retention requires DPO approval.

### BC-3.1 Vendor dependency

If a vendor is the system of record for customer tickets or chat, Procurement must record a fallback plan (export cadence and alternative tool) before the vendor is approved for T3.
