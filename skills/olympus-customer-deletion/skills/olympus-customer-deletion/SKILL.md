---
name: olympus-customer-deletion
description: >
  Standardized workflow for Olympus customer data termination tickets. Guides engineers through
  the full lifecycle: JIRA ticket intake → Excel-to-CSV conversion → dry-run validation →
  live deletion → JIRA update → certificate of destruction.

  Use when:
  - A DEVOPS ticket involves "Termination", "Terminated Clients", "delete customer", or "certificate of destruction"
  - User says "customer deletion", "terminate customer data", "data deletion ticket", or "deletion workflow"
  - User references a DEVOPS ticket with an Excel attachment of files to delete
  - User wants to generate a certificate of destruction for a customer

  Key systems: S3, SFTP (old + new), MySQL (Zeus metadata). Uses delete_with_ai.py for actual deletion.
  MCP servers: artemis-atlassian (JIRA), Bash (script execution).
version: "1.0.0"
author:
  name: "Ari Sela"
tags: [olympus, customer-deletion, sftp, s3, jira, certificate-of-destruction, data-termination, devops]
category: automation
requires:
  tools: []
  skills: []
---

# Olympus Customer Deletion Workflow

## Safety Rules (NEVER skip these)
1. **Always run `--dry-run` first** before any live deletion
2. **Always confirm with engineer** before transitioning to live mode
3. **Never delete without a JIRA ticket number** recorded
4. **Certificate of destruction must be generated and attached to JIRA** before closing the ticket
5. **All 6 steps are mandatory** — do not skip any

---

## Step 1 — Ticket Intake

1. Fetch the DEVOPS JIRA ticket using `artemis-atlassian` MCP:
   - Tool: `jira_get_issue` with the ticket key (e.g., `DEVOPS-8035`)
2. Look for the Excel attachment in: `tickets/<TICKET>/`
   - Example: `tickets/DEVOPS-8035/Terminated Clients - Atlantic Constructors.xlsx`
3. Extract and display:
   - Customer name
   - JIRA ticket number
   - Linked ticket keys (ZEUS, PP, AN, DMI — from ticket description/links)
   - Any notes or special instructions from the ticket

**Display a summary before proceeding to Step 2.**

---

## Step 2 — Excel → CSV Conversion

Use the bundled conversion script. First, find the skill's base directory by reading this file's path, then run:

```bash
python3 <SKILL_BASE_DIR>/scripts/excel_to_csv.py \
  --input "tickets/<TICKET>/<EXCEL_FILENAME>.xlsx" \
  --output ".ralph-projects/olympus-customer-deletions/deletion_lists/<TICKET>-<CUSTOMER_SLUG>.csv"
```

The script maps Excel columns → `file_path,company,date,notes` format required by `delete_with_ai.py`.

Show a CSV preview (first 10 rows) before proceeding.

> If the Excel file has an unusual structure, read it manually and adapt the column mapping.

---

## Step 3 — Dry-Run Validation

**3a. Run the dry-run and save output:**
```bash
cd /Users/ari.sela/git/olympus
PYTHONPATH=scripts/otools/src/otools/tools python3 scripts/otools/src/otools/tools/delete_with_ai.py \
  --csv ".ralph-projects/olympus-customer-deletions/deletion_lists/<TICKET>-<CUSTOMER_SLUG>.csv" \
  --dry-run --no-ai --skip-mysql \
  2>&1 | tee ".ralph-projects/olympus-customer-deletions/deletion_lists/<TICKET>-<CUSTOMER_SLUG>-dryrun.txt"
```

**3b. Generate the review CSV from the dry-run output:**
```bash
python3 <SKILL_BASE_DIR>/scripts/review_dry_run.py \
  --dry-run-output ".ralph-projects/olympus-customer-deletions/deletion_lists/<TICKET>-<CUSTOMER_SLUG>-dryrun.txt" \
  --output ".ralph-projects/olympus-customer-deletions/deletion_lists/<TICKET>-<CUSTOMER_SLUG>-review.csv"
```

The review CSV has one row per file with columns: `s3_prod`, `s3_dev`, `s3_sftp`, `sftp_old_etl`, `sftp_new`, `mysql`, `exists_count`.

**3c. Open the review CSV and ask the engineer to confirm before proceeding.**
- If any paths are invalid, fix the deletion list CSV and re-run from 3a.

---

## Step 4 — Live Deletion

**Ask the engineer which mode to use:**

### Manual mode (default)
```bash
cd /Users/ari.sela/git/olympus
python3 scripts/otools/src/otools/tools/delete_with_ai.py \
  --csv ".ralph-projects/olympus-customer-deletions/deletion_lists/<TICKET>-<CUSTOMER_SLUG>.csv"
```
- Requires `ANTHROPIC_API_KEY` in environment for AI analysis; omit `--no-ai` for AI summary
- The script prompts for `DELETE` confirmation — engineer must type it manually
- Capture the output (file count per system) for the certificate

### Ralph mode (optional)
- Update `.ralph-projects/olympus-customer-deletions/PROMPT.md` with the specific ticket's CSV path
- Update `.ralph-projects/olympus-customer-deletions/@fix_plan.md` with deletion tasks
- Instruct user to run `ralph-loop` from the ralph-projects directory
- See `docs/OLYMPUS-customer-deletion-ralph.md` for Ralph integration details

---

## Step 5 — JIRA Updates

After successful deletion, add a JIRA comment using `artemis-atlassian` MCP (`jira_add_comment`).

**Use JIRA markup** (not Markdown):

```
h2. Customer Data Deletion Complete

*Ticket:* DEVOPS-XXXX
*Customer:* <Customer Name>
*Date:* <Today's Date>

h3. Systems Cleared

|| System || Files Deleted ||
| S3 (prod) | X files |
| S3 (sftp) | X files |
| SFTP (old) | X files |
| SFTP (new) | X files |
| MySQL (Zeus metadata) | X rows |

h3. Notes
* Dry-run validated before deletion
* Certificate of destruction generated (see next comment)
* All file paths validated and confirmed deleted
```

Then transition the ticket to Done: first call `jira_get_transitions` to get the transition ID, then `jira_transition_issue`.

---

## Step 6 — Certificate of Destruction

Read `references/certificate-template.md` and fill in:
- Customer name, JIRA ticket, date, engineer name
- Systems cleared with file counts from Step 4 output

Save to: `docs/certificates/<TICKET>-certificate-of-destruction.md`

Then add the certificate content as a JIRA comment (`jira_add_comment`) formatted in JIRA markup.

> Ask the engineer for their name if not already known.

---

## Key File Paths

| Purpose | Path |
|---------|------|
| Main deletion script | `scripts/otools/src/otools/tools/delete_with_ai.py` |
| Deletion client | `scripts/otools/src/otools/tools/delete_customer_files.py` |
| Usage guide | `scripts/otools/DELETE_WITH_AI_GUIDE.md` |
| Ralph integration guide | `docs/OLYMPUS-customer-deletion-ralph.md` |
| Ralph project dir | `.ralph-projects/olympus-customer-deletions/` |
| Deletion lists | `.ralph-projects/olympus-customer-deletions/deletion_lists/` |
| Ticket attachments | `tickets/DEVOPS-XXXX/` |
| Certificates output | `docs/certificates/` |
