# CERTIFICATE OF DATA DESTRUCTION

---

**Certificate Number:** `<TICKET>-<YYYYMMDD>`
**Issue Date:** `<DATE>`

---

## Customer Information

| Field | Value |
|-------|-------|
| **Customer Name** | `<CUSTOMER_NAME>` |
| **JIRA Ticket** | `<TICKET>` |
| **Deletion Date** | `<DATE>` |
| **Authorized By** | `<ENGINEER_NAME>` |

---

## Scope of Deletion

This certificate confirms that all customer data associated with the above customer
has been permanently and irreversibly deleted from the following systems:

### Data Systems Cleared

| System | Location | Records/Files Deleted |
|--------|----------|----------------------|
| **S3 (Production)** | `automation_drop/prod/<company>/...` | `<S3_PROD_COUNT>` files |
| **S3 (SFTP mirror)** | `sftp/<company>/...` | `<S3_SFTP_COUNT>` files |
| **SFTP (Old server)** | `/mnt/use-prod-sftpraw/etl_root_dir/<company>/...` | `<SFTP_OLD_COUNT>` files |
| **SFTP (New server)** | `/sftp-home/<company>/...` | `<SFTP_NEW_COUNT>` files |
| **MySQL (Zeus metadata)** | `prod_zeus.indexed_file` | `<MYSQL_COUNT>` rows |

**Total files/records deleted: `<TOTAL_COUNT>`**

---

## Deletion Process

The following process was followed to ensure complete and verified data destruction:

1. **Ticket Intake** — JIRA ticket `<TICKET>` reviewed and customer data inventory obtained
2. **Data Mapping** — Excel attachment converted to structured deletion list
3. **Dry-Run Validation** — All file paths verified for existence across all systems before deletion
4. **Live Deletion** — `delete_with_ai.py` executed with AI risk analysis and engineer confirmation
5. **JIRA Update** — Deletion summary posted to `<TICKET>` as a comment
6. **Certificate** — This certificate generated and attached to JIRA ticket

---

## Verification

- [ ] All S3 objects verified deleted
- [ ] All SFTP files verified deleted
- [ ] All MySQL metadata rows verified deleted
- [ ] JIRA ticket `<TICKET>` updated with deletion summary
- [ ] JIRA ticket `<TICKET>` transitioned to Done

---

## Statement of Destruction

I hereby certify that all customer data for **`<CUSTOMER_NAME>`** has been permanently deleted
from all Olympus storage systems listed above. This deletion is irreversible and no copies
of the data remain on any Olympus-managed infrastructure.

**Engineer:** `<ENGINEER_NAME>`
**Date:** `<DATE>`
**Reference:** `<TICKET>`

---

*This certificate was generated as part of the Olympus customer termination process.*
*Retain this document for compliance and audit purposes.*
