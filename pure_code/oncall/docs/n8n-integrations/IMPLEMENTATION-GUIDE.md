# n8n Microsoft Teams Trigger Fix - Implementation Guide

## Problem Summary

The n8n Teams trigger fails with error:
```
Subscription validation request timed out.
Notification endpoint must respond with 200 OK to validation request.
```

**Root Cause**: Microsoft Graph API webhook validation requests are being **blocked by IP allowlisting** on your external webhook ingress (`n8n-dev-webhook.artemishealth.com`).

Your current allowlist only includes Power Automate IPs, but **Microsoft Graph webhooks use different infrastructure**.

## Solution

Add Microsoft Graph API IP ranges to your webhook ingress allowlist.

---

## Files Generated

1. **`microsoft-graph-webhook-ips.txt`** - Specific IPs needed for Graph API webhooks
2. **`combined-webhook-ips.txt`** - Merged Power Automate + Graph API IPs (193 IPv4 ranges)
3. **`generate-webhook-allowlist.py`** - Script to regenerate combined list
4. **`webhook-ingress-example.yaml`** - Kubernetes ingress configuration example

---

## Implementation Steps

### Step 1: Verify Current Ingress Configuration

Check your current webhook ingress:

```bash
kubectl get ingress -n <your-namespace> n8n-webhook-ingress -o yaml
```

Look for the `nginx.ingress.kubernetes.io/whitelist-source-range` annotation.

### Step 2: Backup Current Configuration

```bash
kubectl get ingress -n <your-namespace> n8n-webhook-ingress -o yaml > n8n-webhook-ingress-backup.yaml
```

### Step 3: Update Ingress with New IPs

**Option A: Quick Test (Add Critical IPs Only)**

Add just the Microsoft Graph API ranges to test:

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/whitelist-source-range: |
      20.20.32.0/19,
      20.190.128.0/18,
      20.231.128.0/19,
      40.126.0.0/18,
      52.112.0.0/14,
      52.122.0.0/15,
      <...your existing Power Automate IPs...>
```

**Option B: Complete Implementation**

Use the generated `combined-webhook-ips.txt`:

```bash
# Extract IPv4 IPs into comma-separated format
grep -v "^#" combined-webhook-ips.txt | grep "\." | tr '\n' ',' > ips-formatted.txt
```

Then update your ingress annotation with this list.

**Option C: ConfigMap Approach (Recommended for Large Lists)**

If annotation size exceeds NGINX limits (~256KB), use the ConfigMap approach shown in `webhook-ingress-example.yaml`.

### Step 4: Apply Changes

```bash
kubectl apply -f your-updated-ingress.yaml -n <your-namespace>
```

### Step 5: Verify Ingress Updated

```bash
kubectl get ingress -n <your-namespace> n8n-webhook-ingress -o yaml | grep whitelist-source-range
```

### Step 6: Test Teams Trigger

1. Go to your n8n workflow with Teams trigger
2. Click **"Pull in events from Microsoft Teams"**
3. The validation should now succeed

### Step 7: Monitor Ingress Logs

Watch for incoming validation requests:

```bash
# Get NGINX ingress controller pod
kubectl get pods -n ingress-nginx

# Watch logs for webhook validation attempts
kubectl logs -n ingress-nginx <nginx-pod-name> -f | grep "n8n-dev-webhook"
```

**Expected logs on success**:
```
[date] "GET /webhook/xyz?validationToken=abc123" 200
```

**Expected logs on failure** (before fix):
```
[date] "GET /webhook/xyz?validationToken=abc123" 403 "IP not in allowlist"
```

---

## Verification Checklist

- [ ] Backup current ingress configuration
- [ ] Add Microsoft Graph API IPs to allowlist
- [ ] Apply updated ingress
- [ ] Verify ingress annotation updated
- [ ] Test Teams trigger - validation succeeds
- [ ] Monitor logs - see 200 responses for validation requests
- [ ] Verify existing Power Automate webhooks still work

---

## Critical IP Ranges (Minimum Required)

If you have size constraints, these are the **absolute minimum** IPs needed:

```
# Microsoft Graph API (ID 56) - REQUIRED
20.20.32.0/19
20.190.128.0/18
20.231.128.0/19
40.126.0.0/18

# Microsoft Teams (ID 12) - REQUIRED
52.112.0.0/14
52.122.0.0/15
```

These 6 CIDR ranges cover the core Microsoft Graph API infrastructure that sends webhook validation requests.

---

## Troubleshooting

### Issue: Ingress annotation too large

**Symptom**:
```
error: annotations length exceeds maximum size
```

**Solution**: Use ConfigMap approach (see `webhook-ingress-example.yaml` for ConfigMap method)

### Issue: Still getting 403 errors

**Check**:
1. Verify ingress updated: `kubectl get ingress -o yaml`
2. Check NGINX controller reloaded: `kubectl logs -n ingress-nginx <pod>`
3. Test specific IP: `curl -H "X-Forwarded-For: 20.20.32.1" https://n8n-dev-webhook.artemishealth.com/webhook/test`

### Issue: Teams trigger still fails

**Possible causes**:
1. **Port 443 blocked** - Ensure firewall allows HTTPS
2. **SSL certificate invalid** - Must be trusted CA (Let's Encrypt, etc.)
3. **Slow response** - Must respond within 10 seconds
4. **IPv6 used** - Add IPv6 ranges if Microsoft uses IPv6 in your region

### Issue: Can't find which IPs are being blocked

**Enable detailed logging**:

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/configuration-snippet: |
      # Log all requests including blocked ones
      access_log /var/log/nginx/webhook-debug.log combined;

      # Add custom headers
      add_header X-Client-IP $remote_addr always;
      add_header X-Request-ID $request_id always;
```

Then check logs:
```bash
kubectl logs -n ingress-nginx <pod> | grep 403
```

---

## Alternative Solutions

### 1. Remove IP Allowlisting (Not Recommended)

Temporarily remove IP restrictions to test:

```yaml
metadata:
  annotations:
    # nginx.ingress.kubernetes.io/whitelist-source-range: ""  # Comment out
```

**Security Risk**: Opens webhook endpoint to entire internet. Only use for testing.

### 2. Use Azure Application Gateway WAF

Instead of IP allowlisting, use Azure Application Gateway with Web Application Firewall:
- Validate requests based on User-Agent
- Validate TLS client certificates
- More flexible than IP-based rules

### 3. Separate Internal vs External Ingress

You already have this setup:
- **Internal**: `n8n-dev.internal.artemishealth.com` (Zscaler + cluster)
- **External**: `n8n-dev-webhook.artemishealth.com` (webhook only)

This is the **recommended architecture**. Just ensure external ingress has correct IPs.

---

## Maintenance

### Keeping IPs Updated

Microsoft updates these IP ranges monthly. To stay current:

1. **Subscribe to change notifications**:
   - RSS: https://learn.microsoft.com/en-us/microsoft-365/enterprise/urls-and-ip-address-ranges
   - JSON API: https://endpoints.office.com/endpoints/worldwide?clientrequestid=b10c5ed1-bad1-445f-b386-b919946339a7

2. **Automated updates**:
   ```bash
   # Download latest IPs monthly
   curl -o microsoft-ips-latest.json https://endpoints.office.com/endpoints/worldwide?clientrequestid=$(uuidgen)

   # Regenerate allowlist
   python3 generate-webhook-allowlist.py > combined-webhook-ips.txt

   # Apply to Kubernetes
   kubectl apply -f updated-ingress.yaml
   ```

3. **Monitor Microsoft announcements**:
   - 30 days advance notice for new IPs
   - Check at start of each month

---

## Security Considerations

### What We're Allowing

- **Microsoft Graph API**: webhook validation and data delivery
- **Microsoft Teams**: Teams service infrastructure
- **Power Automate**: Existing workflow integrations

### What We're NOT Allowing

- General internet traffic (unless explicitly added)
- Unauthorized webhook senders

### Audit Recommendations

1. **Log all webhook requests** with source IPs
2. **Monitor for suspicious patterns** (unusual frequency, unknown IPs)
3. **Review allowlist quarterly** against Microsoft's published ranges
4. **Alert on validation failures** (may indicate IP changes)

---

## Success Criteria

You'll know it's working when:

1. ✅ Teams trigger configuration shows "Connected" status
2. ✅ n8n logs show successful webhook subscription creation
3. ✅ Sending a Teams message triggers workflow execution
4. ✅ No "validation timed out" errors
5. ✅ NGINX logs show 200 OK for validation requests

---

## References

- **Microsoft 365 IP Ranges**: https://learn.microsoft.com/en-us/microsoft-365/enterprise/urls-and-ip-address-ranges
- **Microsoft Graph Webhooks**: https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks
- **n8n GitHub Issue**: https://github.com/n8n-io/n8n/issues/17887
- **NGINX Ingress Annotations**: https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations/

---

## Support

If issues persist after implementing this fix:

1. Check GitHub issue for updates: https://github.com/n8n-io/n8n/issues/17887
2. Verify your n8n version is updated (bug may be fixed in newer versions)
3. Consider the workarounds mentioned in the GitHub thread:
   - Use Webhook node directly with manual subscription management
   - Use scheduled polling instead of real-time triggers

---

**Last Updated**: 2025-10-10
**Author**: Claude Code Analysis
**Version**: 1.0
