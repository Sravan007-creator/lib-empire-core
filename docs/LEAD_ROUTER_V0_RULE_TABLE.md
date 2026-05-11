# Lead Router v0 — Rule Table Template

**Owner:** Sravan AM (Recruitment Head + B2B Enquiry Head)
**Status:** template — Sravan to fill in the actual rules, then ops to wire env vars
**Last updated:** 2026-05-12

## Why this document exists

`empireoe-core.lead_router` knows how to:
- receive Meta webhook events (Instagram DM + WhatsApp Business)
- classify the message with Claude (recruitment / study_abroad / agent / general)
- persist via the product backend's `on_lead` callback
- ping the assignee's Slack channel (new in v0.6.0)

What it doesn't know yet is the **rule table** — the mapping from
`(source, category, product)` to `(assignee, slack_channel, follow-up SLA)`.

This file is the template. Sravan fills in the actual values; ops mirrors
those values into env vars on each backend host.

## Channel inventory (fill these in, Sravan)

| Slack channel | Purpose | Owner | Webhook URL stored in 1Password as |
|---|---|---|---|
| `#leads-recruitment` | All recruitment-tagged inbound | Sravan | `TE-Slack/Leads/Recruitment` |
| `#leads-study-abroad` | EOE study-abroad leads | Athira / Nima | `TE-Slack/Leads/StudyAbroad` |
| `#leads-agents` | B2B agent partnership enquiries | Sravan + Harish | `TE-Slack/Leads/Agents` |
| `#leads-general` | Default catch-all | Shybin | `TE-Slack/Leads/Default` |
| `#leads-hotelo` | Hotelo pilot enquiries | Sharon | `TE-Slack/Leads/Hotelo` |
| `#leads-lwe` | LWE English Training inbound | Jestlin | `TE-Slack/Leads/LWE` |

## Rule table (Sravan)

Per `(category, product)`, who owns the first-touch reply and what's the SLA?

| Category | Product | Assignee | SLA (business hours) | Slack channel |
|---|---|---|---|---|
| recruitment | empireo | Sravan | 2 hours | #leads-recruitment |
| recruitment | * (other) | Sravan | 2 hours | #leads-recruitment |
| study_abroad | eoe | Athira | 4 hours | #leads-study-abroad |
| study_abroad | * | Nima | 4 hours | #leads-study-abroad |
| agent | egpn | Sravan + Harish | 1 business day | #leads-agents |
| agent | * | Sravan | 1 business day | #leads-agents |
| general | hotelo | Sharon | 1 business day | #leads-hotelo |
| general | lwe | Jestlin | 1 business day | #leads-lwe |
| general | * | Shybin | 1 business day | #leads-general |

**Notes for Sravan to revise:**
- Out-of-hours rule? (e.g. after 6pm IST, route everything to the on-call WhatsApp number)
- Escalation if no claim within SLA? (auto-DM to Mano? Auto-reassign to default?)
- Agent (B2B) leads: do you want them quarantined to Harish + Sravan only, or visible to the whole team?

## Env vars to set per backend (Ops)

Once Sravan locks the channels, each backend's `/opt/<service>/.env` needs:

```
# Per-channel Slack webhooks (one per row in the rule table)
SLACK_WEBHOOK_URL_LEADS_RECRUITMENT=https://hooks.slack.com/services/...
SLACK_WEBHOOK_URL_LEADS_DEFAULT=https://hooks.slack.com/services/...
SLACK_WEBHOOK_URL_LEADS_HOTELO=https://hooks.slack.com/services/...
SLACK_WEBHOOK_URL_LEADS_LWE=https://hooks.slack.com/services/...
# (Add one per product / category as the rule table grows.)

# Product slug — picked up by MetaWebhookConfig.from_env() so the router
# can consult SLACK_WEBHOOK_URL_LEADS_<PRODUCT> before the default.
LEAD_ROUTER_PRODUCT_SLUG=lwe   # or empireo, hotelo, eoe, etc. per host
```

After updating: `sudo systemctl restart <service>`.

## Generating the webhook URLs (one-time)

For each Slack channel above:
1. Open https://api.slack.com/apps → the Team Empire workspace's app
2. Incoming Webhooks → Add New Webhook to Workspace → pick the channel
3. Copy the resulting `https://hooks.slack.com/services/...` URL
4. Drop into 1Password under the slot in the channel-inventory table

## Verifying

After env vars land + service restart:

```bash
# From the prod host, fire a synthetic recruitment-category event.
# Should produce a Slack post in #leads-recruitment within 2-3 seconds.
curl -X POST -H 'Content-Type: application/json' \
  https://api.empireo.ai/api/v1/webhooks/meta/whatsapp \
  -d '{ "entry":[{"changes":[{"value":{"messages":[{"type":"text",
       "text":{"body":"Looking for senior frontend role in Dubai"},
       "from":"+919876543210"}],"contacts":[{"wa_id":"+919876543210",
       "profile":{"name":"Test User"}}]}}]}]}'
```

If no Slack post appears, check:
- `journalctl -u <service> -n 50` for `Slack webhook not configured` debug
  lines or `non-2xx` warnings
- That `SLACK_WEBHOOK_URL_LEADS_RECRUITMENT` is actually set in the env
- That the webhook URL still works (Slack invalidates them on app revoke)

## What v0 deliberately doesn't do

- Two-way Slack threading (reply in Slack → reply on WhatsApp). v1 territory.
- Lead deduplication across sources. v1 territory.
- Auto-assignment by load. v1 territory — for now everything is config-driven.
