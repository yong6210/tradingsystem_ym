# Operator Session Brief Delivery Preflight

- generated_at: 2026-03-23T17:37:24.607143+00:00
- healthy: True
- launchd_channel: system
- launchd_dry_run: 1
- launchd_allow_live_send: unset

## Channels

- system: healthy=True configured=True
  - routes: discord
- discord: healthy=True configured=True
  - target: https:...8KST

## Issues

- none

## Raw Payload

```json
{
  "generated_at": "2026-03-23T17:37:24.607143+00:00",
  "healthy": true,
  "issues": [],
  "launchd_env": {
    "OPERATOR_BRIEF_CHANNEL": "system",
    "OPERATOR_BRIEF_DRY_RUN": "1",
    "OPERATOR_BRIEF_ALLOW_LIVE_SEND": "",
    "OPERATOR_BRIEF_DISCORD_WEBHOOK_URL": false
  },
  "channels": {
    "system": {
      "channel": "system",
      "configured": true,
      "healthy": true,
      "routes": [
        "discord"
      ],
      "issues": []
    },
    "discord": {
      "channel": "discord",
      "configured": true,
      "healthy": true,
      "target": "https:...8KST",
      "issues": []
    }
  },
  "circuit_snapshot": {}
}
```