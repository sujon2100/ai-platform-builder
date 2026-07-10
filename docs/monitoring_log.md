# Monitoring log: 30-day evidence window

Official monitoring window start: 2026-07-10 08:10 UTC.

This is the point from which uptime, latency, and error numbers should be
treated as citable. Everything before it was deployment and bug-fixing
work (see the "Issues found and fixed" section in RUNBOOK.md) and should
be excluded from the headline uptime figure in the final writeup.
Counting expected deployment-time restarts as downtime would understate
the deployment's actual reliability once it settled.

Target end of window: 2026-08-09 or later, minimum 30 days.

## Where to pull current numbers

- GCP Cloud Monitoring: https://console.cloud.google.com/monitoring/uptime?project=ai-platform-eb2-demo
- UptimeRobot public status page: https://stats.uptimerobot.com/2JUsdtF71z
- Prometheus, via IAP tunnel (see RUNBOOK.md)
- Synthetic traffic log on the VM: ~/synthetic_traffic.log

## Check-in log

2026-07-10: monitoring window just started. Two bugs found and fixed
before the window began: a silent Kafka publish failure (flush() doesn't
guarantee delivery, fixed by checking the send future) and missing HEAD
support on the health endpoints (caused a false "down" reading in
UptimeRobot). Both documented in RUNBOOK.md. Baseline established, no
data yet to report.
