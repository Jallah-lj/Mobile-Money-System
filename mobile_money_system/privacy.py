"""Privacy & data controls (GDPR-style / Rwanda Law No. 058/2021).

Capabilities:

* **Data export** — a user can download everything the platform holds about
  them (profile, transactions, beneficiaries, scheduled payments, tickets,
  notification channels, sessions, consents) as JSON or CSV.
* **Account deletion** — a user requests deletion; an admin reviews and
  approves/rejects. On approval the account row is removed and the user's
  phone number is **pseudonymized** in retained financial records (audit and
  transaction history must survive for compliance, but no longer identify the
  person). Beneficiaries, scheduled payments, tickets, notification channels
  and sessions are deleted outright.
* **Consent ledger** — versioned, revocable consent for the Terms of Service,
  the Privacy Policy, and marketing, recorded with timestamp and source.
* **Legal documents** — versioned Privacy Policy / Terms of Service with a
  publish workflow; users are prompted to re-accept when a new version goes
  live.
* **Right to rectification** — users correct their own profile data.
* **Data breach register** — record, track, and resolve personal-data
  breaches (GDPR Art. 33 record-keeping).

Every action is audit-logged.
"""

import hashlib

if __package__:
    from .audit import log_event
    from .database import get_db, init_db, write_transaction
    from .models import utcnow
else:
    from audit import log_event  # type: ignore[no-redef]
    from database import get_db, init_db, write_transaction  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]

DELETION_STATUSES = ("pending", "approved", "rejected")

CONSENT_PURPOSES = ("terms", "privacy", "marketing")
LEGAL_DOC_TYPES = ("privacy_policy", "terms_of_service")
BREACH_SEVERITIES = ("low", "medium", "high", "critical")
BREACH_STATUSES = ("open", "investigating", "resolved", "notified")

DEFAULT_PRIVACY_POLICY = """Mobile Money System — Privacy Policy

1. CONTROLLER
The Mobile Money System platform ("we", "us") is the data controller for the
personal data described below. Contact the Data Protection Officer at
privacy@mobilemoney.example (replace with the real contact in production).

2. DATA WE COLLECT
- Account data: phone number, name, PIN (stored only as a bcrypt hash),
  security question/answer (hashed), currency preference.
- Identity data (KYC): ID type and ID number (masked in all displays).
- Financial data: transactions, beneficiaries, scheduled payments, balances,
  and a double-entry ledger.
- Security data: login sessions, login attempts, OTP codes (hashed), the
  audit trail, and rate-limit records.
- Consent records: which legal documents you accepted, when, and from where.

3. PURPOSES AND LEGAL BASES
- Operating your wallet and processing payments — performance of a contract.
- Fraud prevention, AML screening, audit trail — legal obligation and
  legitimate interest.
- Security (2FA, lockouts) — legitimate interest.
- Marketing messages — your consent (withdrawable at any time).

4. RETENTION
Financial records are kept as long as legally required; security and
operational records are pruned automatically per the configured retention
policy. When you delete your account, your phone number is pseudonymized in
the records we must retain.

5. YOUR RIGHTS (GDPR / Rwanda Law No. 058/2021)
You may: access and export your data; rectify (correct) your data; erase
your account; restrict processing; receive your data in a machine-readable
format (JSON/CSV export); and object to marketing. Exercise them in
Settings, or contact the DPO. We respond within 30 days.

6. SECURITY
PINs and OTPs are hashed; sessions are server-side and revocable; all
balance changes are atomic; every privacy-relevant action is audit-logged.

7. TRANSFERS
Data stays on the platform's own servers. We share data only with the
payment counterparties you choose, and with authorities where the law
requires it.

8. CHANGES
New versions of this policy are published with a version number; you are
asked to re-accept when a version changes.
"""

DEFAULT_TERMS_OF_SERVICE = """Mobile Money System — Terms of Service

1. SERVICE. We provide a mobile-money wallet: transfers, bill payments,
scheduled payments, and money requests between registered users.
2. ACCOUNT. Keep your PIN confidential; you are responsible for activity on
your account. One account per phone number.
3. MONEY MOVEMENT. Transfers are final once completed. Any fees are shown
before you confirm. We may reverse transactions in cases of fraud or error,
with an audit trail.
4. COMPLIANCE. You must complete KYC before transacting. We may suspend
accounts for fraud, AML, or legal reasons.
5. ACCEPTABLE USE. No illegal use, no API abuse, no attempts to circumvent
limits or security.
6. LIABILITY. The service is provided as-is; we are not liable for indirect
damages. Our liability is limited to the balance in your wallet.
7. TERMINATION. You may request account deletion (admin-approved). We may
suspend or terminate accounts that breach these terms.
8. CHANGES. We may update these terms; continued use after an update means
acceptance. Material changes are re-presented for acceptance.
9. LAW. These terms are governed by the laws of Rwanda; data protection is
governed by Rwanda Law No. 058/2021 and, where applicable, the GDPR.
"""


def ensure_legal_documents() -> None:
    """Seed the default legal documents on first run and backfill consent
    records for users who registered before consent tracking existed.
    Idempotent — safe to call on every PrivacyManager init."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM legal_documents").fetchone()
        if row["n"] == 0:
            now = utcnow().isoformat()
            conn.execute(
                "INSERT INTO legal_documents (doc_type, version, content, published_at, active)"
                " VALUES (?, ?, ?, ?, 1)",
                ("privacy_policy", "1.0", DEFAULT_PRIVACY_POLICY, now))
            conn.execute(
                "INSERT INTO legal_documents (doc_type, version, content, published_at, active)"
                " VALUES (?, ?, ?, ?, 1)",
                ("terms_of_service", "1.0", DEFAULT_TERMS_OF_SERVICE, now))
            conn.commit()
    # Backfill: users without an active 'privacy' consent get a legacy record
    # at the currently-active versions (they registered pre-consent-tracking).
    with write_transaction() as conn:
        missing = conn.execute(
            "SELECT COUNT(*) AS n FROM users u WHERE NOT EXISTS ("
            " SELECT 1 FROM consents c WHERE c.phone = u.phone AND c.purpose = 'privacy'"
            " AND c.revoked_at IS NULL)").fetchone()
        if not missing["n"]:
            return
        now = utcnow().isoformat()
        for u in conn.execute("SELECT phone FROM users").fetchall():
            phone = u["phone"]
            for purpose, doc_type in (("terms", "terms_of_service"), ("privacy", "privacy_policy")):
                exists = conn.execute(
                    "SELECT 1 FROM consents WHERE phone = ? AND purpose = ? AND revoked_at IS NULL",
                    (phone, purpose)).fetchone()
                if exists:
                    continue
                version = conn.execute(
                    "SELECT version FROM legal_documents WHERE doc_type = ? AND active = 1",
                    (doc_type,)).fetchone()
                if not version:
                    continue
                conn.execute(
                    "INSERT INTO consents (phone, purpose, policy_version, accepted_at, ip_address, user_agent)"
                    " VALUES (?, ?, ?, ?, '', 'legacy-backfill')",
                    (phone, purpose, version["version"], now))


def pseudonymize(phone: str) -> str:
    """Stable, non-reversible placeholder for a deleted user's phone number."""
    return "DELETED-" + hashlib.sha256(phone.encode()).hexdigest()[:12]


class PrivacyManager:
    def __init__(self):
        init_db()  # Creates schema + seeds legal documents (idempotent)

    # --- Data export ---

    def export_user_data(self, phone: str) -> dict | None:
        """Everything the platform holds about the user, as a plain dict."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
            user_row = cursor.fetchone()
            if not user_row:
                return None
            data: dict = {"exported_at": utcnow().isoformat(), "profile": dict(user_row)}
            # Never export credentials
            data["profile"].pop("pin", None)
            data["profile"].pop("sec_a", None)

            def fetch_all(table, where, params):
                cursor.execute(f"SELECT * FROM {table} WHERE {where}", params)
                return [dict(r) for r in cursor.fetchall()]

            data["transactions"] = fetch_all(
                "transactions", "sender_phone = ? OR receiver_phone = ?", (phone, phone))
            data["beneficiaries"] = fetch_all("beneficiaries", "owner_phone = ?", (phone,))
            data["scheduled_payments"] = fetch_all("scheduled_payments", "owner_phone = ?", (phone,))
            data["tickets"] = fetch_all("tickets", "phone = ?", (phone,))
            data["notification_channels"] = fetch_all(
                "notification_channels", "phone = ?", (phone,))
            data["sessions"] = fetch_all("sessions", "phone = ?", (phone,))
            data["audit_trail"] = fetch_all("audit_log", "actor_phone = ?", (phone,))
            return data

    # --- Deletion requests ---

    def request_deletion(self, phone: str, reason: str = "") -> tuple[bool, str]:
        """User asks to delete their account. Requires admin approval."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone FROM users WHERE phone = ?", (phone,))
            if not cursor.fetchone():
                return False, "User not found"
            cursor.execute(
                "SELECT id FROM account_deletions WHERE phone = ? AND status = 'pending'", (phone,))
            if cursor.fetchone():
                return False, "A deletion request is already pending."
            cursor.execute('''
            INSERT INTO account_deletions (phone, reason, status, requested_at)
            VALUES (?, ?, 'pending', ?)
            ''', (phone, reason, utcnow().isoformat()))
            req_id = cursor.lastrowid
            conn.commit()
        log_event(phone, "DELETION_REQUESTED", target=str(req_id), details=reason[:200])
        return True, f"Deletion request #{req_id} submitted. An admin will review it."

    def pending_deletions(self) -> list[dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM account_deletions WHERE status = 'pending' ORDER BY requested_at")
            return [dict(r) for r in cursor.fetchall()]

    def get_request(self, request_id: int) -> dict | None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM account_deletions WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def reject_deletion(self, request_id: int, admin_phone: str, note: str = "") -> tuple[bool, str]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE account_deletions
            SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, review_note = ?
            WHERE id = ? AND status = 'pending'
            ''', (admin_phone, utcnow().isoformat(), note, request_id))
            changed = cursor.rowcount
            conn.commit()
        if not changed:
            return False, "Request not found or already reviewed."
        req = self.get_request(request_id)
        log_event(admin_phone, "DELETION_REJECTED", target=str(request_id),
                  details=f"for {req['phone'] if req else '?'}: {note[:200]}")
        return True, "Deletion request rejected. The account stays active."

    @staticmethod
    def _purge_user_data(cursor, phone: str) -> str:
        """Delete a user's personal data and pseudonymize their financial
        records. Runs inside the caller's transaction. Returns the pseudonym."""
        pseudo = pseudonymize(phone)
        # 1. Pseudonymize retained financial/compliance records
        cursor.execute(
            "UPDATE transactions SET sender_phone = ? WHERE sender_phone = ?", (pseudo, phone))
        cursor.execute(
            "UPDATE transactions SET receiver_phone = ? WHERE receiver_phone = ?", (pseudo, phone))
        cursor.execute(
            "UPDATE audit_log SET actor_phone = ? WHERE actor_phone = ?", (pseudo, phone))
        cursor.execute(
            "UPDATE ledger SET account_id = ? WHERE account_id = ?", (pseudo, phone))
        # 2. Delete personal data outright
        for table, col in (("users", "phone"), ("beneficiaries", "owner_phone"),
                           ("scheduled_payments", "owner_phone"), ("tickets", "phone"),
                           ("notification_channels", "phone"), ("sessions", "phone")):
            cursor.execute(f"DELETE FROM {table} WHERE {col} = ?", (phone,))
        return pseudo

    def approve_deletion(self, request_id: int, admin_phone: str) -> tuple[bool, str]:
        """Approve a deletion: remove the account, pseudonymize financial records."""
        req = self.get_request(request_id)
        if not req or req["status"] != "pending":
            return False, "Request not found or already reviewed."
        phone = req["phone"]
        now = utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            pseudo = self._purge_user_data(cursor, phone)
            # 3. Close the request
            cursor.execute('''
            UPDATE account_deletions
            SET status = 'approved', reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            ''', (admin_phone, now, request_id))
            conn.commit()
        log_event(admin_phone, "DELETION_APPROVED", target=phone,
                  details=f"Account deleted; records pseudonymized as {pseudo}")
        return True, f"Account {phone} deleted. Financial records were pseudonymized ({pseudo})."

    def admin_delete_user(self, phone: str, admin_phone: str, reason: str = "") -> tuple[bool, str]:
        """Admin-initiated account deletion (no user request needed).

        Same data rules as an approved GDPR request: personal data is deleted,
        financial records are pseudonymized. Runs atomically.
        """
        with get_db() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT phone FROM users WHERE phone = ?", (phone,)).fetchone()
            if not row:
                return False, "User not found"
        with write_transaction() as conn:
            pseudo = self._purge_user_data(conn.cursor(), phone)
        log_event(admin_phone, "ADMIN_DELETE_USER", target=phone,
                  details=f"Admin-initiated deletion; records pseudonymized as {pseudo}. Reason: {reason[:200]}")
        return True, f"Account {phone} deleted. Financial records were pseudonymized ({pseudo})."

    def cancel_deletion_request(self, phone: str, request_id: int) -> bool:
        """A user withdraws their own pending request."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM account_deletions WHERE id = ? AND phone = ? AND status = 'pending'",
                (request_id, phone))
            changed = cursor.rowcount
            conn.commit()
        return changed > 0

    def my_deletion_requests(self, phone: str) -> list[dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM account_deletions WHERE phone = ? ORDER BY requested_at DESC", (phone,))
            return [dict(r) for r in cursor.fetchall()]


    # --- Legal documents (versioned privacy policy / terms) ---

    def get_active_document(self, doc_type: str) -> dict | None:
        """The currently-active version of a legal document, or None."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM legal_documents WHERE doc_type = ? AND active = 1 ORDER BY id DESC LIMIT 1",
                (doc_type,)).fetchone()
            return dict(row) if row else None

    def list_documents(self, doc_type: str) -> list[dict]:
        """All versions of a legal document, newest first."""
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM legal_documents WHERE doc_type = ? ORDER BY id DESC",
                (doc_type,)).fetchall()
            return [dict(r) for r in rows]

    def publish_document(self, doc_type: str, version: str, content: str, actor: str) -> tuple[bool, str]:
        """Publish a new version of a legal document. Older versions are kept
        for the record (users who accepted them stay traceable)."""
        if doc_type not in LEGAL_DOC_TYPES:
            return False, f"Invalid document type (must be one of {LEGAL_DOC_TYPES})"
        version = (version or "").strip()
        content = (content or "").strip()
        if not version or not content:
            return False, "Version and content are required."
        with write_transaction() as conn:
            conn.execute("UPDATE legal_documents SET active = 0 WHERE doc_type = ?", (doc_type,))
            conn.execute(
                "INSERT OR IGNORE INTO legal_documents (doc_type, version, content, published_at, active)"
                " VALUES (?, ?, ?, ?, 1)",
                (doc_type, version, content, utcnow().isoformat()))
        log_event(actor, "LEGAL_DOCUMENT_PUBLISHED", target=doc_type, details=f"version {version}")
        return True, f"{doc_type} v{version} published."

    # --- Consent ledger ---

    def record_consent(self, phone: str, purpose: str, policy_version: str,
                       ip: str = "", user_agent: str = "") -> tuple[bool, str]:
        """Record consent for a purpose at a policy version. Any previous
        active consent for the same purpose is superseded (revoked)."""
        if purpose not in CONSENT_PURPOSES:
            return False, f"Invalid consent purpose (must be one of {CONSENT_PURPOSES})"
        now = utcnow().isoformat()
        with write_transaction() as conn:
            conn.execute(
                "UPDATE consents SET revoked_at = ? WHERE phone = ? AND purpose = ? AND revoked_at IS NULL",
                (now, phone, purpose))
            conn.execute(
                "INSERT INTO consents (phone, purpose, policy_version, accepted_at, ip_address, user_agent)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (phone, purpose, policy_version, now, ip, user_agent))
        log_event(phone, "CONSENT_RECORDED", target=purpose, details=f"version {policy_version}")
        return True, "Consent recorded."

    def get_consents(self, phone: str) -> list[dict]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM consents WHERE phone = ? ORDER BY accepted_at DESC, id DESC",
                (phone,)).fetchall()
            return [dict(r) for r in rows]

    def active_consent(self, phone: str, purpose: str) -> dict | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM consents WHERE phone = ? AND purpose = ? AND revoked_at IS NULL"
                " ORDER BY id DESC LIMIT 1",
                (phone, purpose)).fetchone()
            return dict(row) if row else None

    def has_consent(self, phone: str, purpose: str) -> bool:
        return self.active_consent(phone, purpose) is not None

    def revoke_consent(self, phone: str, purpose: str) -> tuple[bool, str]:
        """Withdraw consent (right to object / withdraw consent)."""
        if purpose not in CONSENT_PURPOSES:
            return False, f"Invalid consent purpose (must be one of {CONSENT_PURPOSES})"
        now = utcnow().isoformat()
        with write_transaction() as conn:
            cur = conn.execute(
                "UPDATE consents SET revoked_at = ? WHERE phone = ? AND purpose = ? AND revoked_at IS NULL",
                (now, phone, purpose))
            changed = cur.rowcount
        if not changed:
            return False, "No active consent to revoke."
        log_event(phone, "CONSENT_REVOKED", target=purpose)
        return True, "Consent revoked."

    def accept_current_policies(self, phone: str, ip: str = "", user_agent: str = "") -> tuple[bool, str]:
        """Record consent to the currently-active Terms + Privacy Policy."""
        terms = self.get_active_document("terms_of_service")
        privacy = self.get_active_document("privacy_policy")
        if not terms or not privacy:
            return False, "Legal documents are not configured."
        ok1, _ = self.record_consent(phone, "terms", terms["version"], ip, user_agent)
        ok2, _ = self.record_consent(phone, "privacy", privacy["version"], ip, user_agent)
        return ok1 and ok2, "Consent recorded for the current Terms & Privacy Policy."

    def policy_update_required(self, phone: str) -> bool:
        """True when the user's accepted privacy version differs from the
        active one (a new policy was published after they accepted)."""
        active = self.get_active_document("privacy_policy")
        if not active:
            return False
        accepted = self.active_consent(phone, "privacy")
        if not accepted:
            return True
        return accepted["policy_version"] != active["version"]

    # --- Right to rectification (self-service profile correction) ---

    def update_profile(self, phone: str, name: str) -> tuple[bool, str]:
        """Right to rectification: the user corrects their own profile data."""
        name = (name or "").strip()
        if not name or len(name) > 100:
            return False, "Name must be 1-100 characters."
        with write_transaction() as conn:
            cur = conn.execute("UPDATE users SET name = ? WHERE phone = ?", (name, phone))
            changed = cur.rowcount
        if not changed:
            return False, "User not found"
        log_event(phone, "PROFILE_UPDATED", target=phone, details=f"name changed to '{name}'")
        return True, "Profile updated."

    # --- Data breach register (GDPR Art. 33 record-keeping) ---

    def report_breach(self, detected_at: str, description: str, severity: str = "medium",
                      affected_count: int = 0, created_by: str = "ADMIN") -> tuple[bool, str]:
        if severity not in BREACH_SEVERITIES:
            return False, f"Invalid severity (must be one of {BREACH_SEVERITIES})"
        description = (description or "").strip()
        if not description:
            return False, "Description is required."
        if not detected_at.strip():
            return False, "Detection date is required."
        now = utcnow().isoformat()
        with write_transaction() as conn:
            cur = conn.execute(
                "INSERT INTO data_breaches"
                " (detected_at, severity, description, affected_count, status, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
                (detected_at.strip(), severity, description, int(affected_count), created_by, now, now))
            breach_id = cur.lastrowid
        log_event(created_by, "BREACH_REPORTED", target=str(breach_id),
                  details=f"[{severity}] {description[:200]}")
        return True, f"Breach #{breach_id} recorded."

    def update_breach(self, breach_id: int, status: str | None = None,
                      resolution: str | None = None, reported_at: str | None = None,
                      actor: str = "ADMIN") -> tuple[bool, str]:
        """Move a breach through its lifecycle; optionally record the
        authority-report timestamp (GDPR 72-hour rule) and a resolution."""
        if status is not None and status not in BREACH_STATUSES:
            return False, f"Invalid status (must be one of {BREACH_STATUSES})"
        fields: list[str] = []
        params: list = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if resolution is not None:
            fields.append("resolution = ?")
            params.append(resolution.strip())
        if reported_at is not None:
            fields.append("reported_at = ?")
            params.append(reported_at.strip())
        if not fields:
            return False, "Nothing to update."
        fields.append("updated_at = ?")
        params.append(utcnow().isoformat())
        params.append(breach_id)
        with write_transaction() as conn:
            cur = conn.execute(
                f"UPDATE data_breaches SET {', '.join(fields)} WHERE id = ?", params)
            changed = cur.rowcount
        if not changed:
            return False, "Breach not found."
        log_event(actor, "BREACH_UPDATED", target=str(breach_id),
                  details=f"status={status or 'unchanged'}")
        return True, f"Breach #{breach_id} updated."

    def list_breaches(self, status: str | None = None) -> list[dict]:
        with get_db() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM data_breaches WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM data_breaches ORDER BY id DESC").fetchall()
            return [dict(r) for r in rows]

    def get_breach(self, breach_id: int) -> dict | None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM data_breaches WHERE id = ?", (breach_id,)).fetchone()
            return dict(row) if row else None


def export_to_csv(data: dict) -> str:
    """Flatten the export into CSV sections (profile + transactions)."""
    import csv
    from io import StringIO
    buf = StringIO()
    buf.write("# PROFILE\n")
    writer = csv.DictWriter(buf, fieldnames=list(data["profile"].keys()))
    writer.writeheader()
    writer.writerow(data["profile"])
    for section in ("transactions", "beneficiaries", "scheduled_payments", "tickets"):
        buf.write(f"\n# {section.upper()}\n")
        rows = data.get(section) or []
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    return buf.getvalue()
