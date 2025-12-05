---
title: Incident Response Playbook
category: oncall
severity: critical
---

# Incident Response Playbook

Standard operating procedures for on-call incident response.

## Initial Assessment

When an alert fires, follow this sequence:

### Step 1: Acknowledge

1. Acknowledge the alert in PagerDuty/OpsGenie
2. Join the incident channel (if escalated)
3. Set your status to indicate you're investigating

### Step 2: Assess Severity

Use this matrix to determine severity:

| Impact | User-Facing | Internal Only |
|--------|-------------|---------------|
| Complete outage | SEV1 | SEV2 |
| Degraded | SEV2 | SEV3 |
| Minor | SEV3 | SEV4 |

### Step 3: Initial Triage

1. Check monitoring dashboards for anomalies
2. Review recent deployments (last 24h)
3. Check for related alerts
4. Identify affected services

## Common Scenarios

### High CPU Usage

1. Identify the process consuming CPU:
   ```bash
   kubectl top pods -n <namespace>
   ```

2. Check for runaway queries or loops in logs

3. Consider scaling horizontally if load is legitimate

### Database Connection Exhaustion

1. Check connection count:
   ```sql
   SELECT count(*) FROM pg_stat_activity;
   ```

2. Identify long-running queries:
   ```sql
   SELECT pid, now() - pg_stat_activity.query_start AS duration, query
   FROM pg_stat_activity
   WHERE state = 'active'
   ORDER BY duration DESC;
   ```

3. Kill long-running queries if necessary

### Network Connectivity Issues

1. Check service endpoints:
   ```bash
   kubectl get endpoints <service-name>
   ```

2. Verify network policies aren't blocking traffic

3. Check for DNS resolution issues

## Escalation

Escalate to the next tier if:

- You cannot identify the root cause within 15 minutes
- The issue requires access you don't have
- Multiple services are affected
- Customer impact is severe

### Escalation Contacts

- **Platform Team**: For infrastructure issues
- **Database Team**: For database-related issues
- **Security Team**: For security incidents
- **Management**: For SEV1 incidents

## Post-Incident

After resolution:

1. Update the incident ticket with resolution
2. Send all-clear notification
3. Schedule post-mortem if SEV1/SEV2
4. Create follow-up tickets for improvements
