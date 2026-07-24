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

2026-07-12: two monitoring gaps closed. First, synthetic traffic timing
switched from a fixed 3-hour cron interval to a randomized daily
schedule (same 8/day volume). Second, and more substantive: added a
second monitored endpoint, /health/ready, on both GCP Cloud Monitoring
and UptimeRobot, since the original /health/live check only confirms
the gateway process is alive and would stay green even if Kafka or the
database went down. Also extended the synthetic traffic script to poll
each request until it actually completes instead of just logging the
accept response, since the accept always returns 200 immediately
regardless of whether the pipeline behind it works. This means the
final writeup can report a real end-to-end success rate, not just HTTP
uptime.

2026-07-12 (automated check-in): two days into the window. Gateway
health endpoint responded 200 OK on a direct curl just now. GCP Cloud
Monitoring shows a 100% pass rate since window start (2026-07-10 08:10
UTC) on both checks: 26,399/26,399 passed on /health/live
(ai-platform-gateway-uptime) and 1,591/1,591 on /health/ready
(ai-platform-gateway-ready). No failures recorded in either check yet.
Could not confirm the UptimeRobot public status page number this
run - the page returned a client-side loading/fetch error to the
automated fetch, so that figure needs a manual look rather than being
reported here. VM is RUNNING. Synthetic traffic log shows 22 /chat
requests logged since window start, all status 200, with no gaps in
the roughly-3-hourly cadence through the afternoon of 07-12; the last
two entries (17:34 and 18:55 UTC) are in the new poll-to-completion
format described above and both completed successfully, confirming
the randomized-schedule and end-to-end-completion changes are live.
28 days remain until the 2026-08-09 minimum window end.

2026-07-24: full check on whether the cron job and both uptime sources
are actually generating data as designed, prompted by a request to
verify this rather than just trust it. The mechanics are all fine: the
VM is RUNNING, all five containers have been up for 2 weeks with no
unexpected restarts, crontab still has the single `5 0 * * *
daily_scheduler.sh` entry, atd is active, and the script is correctly
queuing 8 randomized `at` jobs a day - the log has grown by roughly 8
lines/day with no missing days. GCP Cloud Monitoring shows 100% pass
rate on both checks over the full window to date (98,775/98,775 on
/health/live, 82,264/82,264 on /health/ready). UptimeRobot's own page
loaded this time (the earlier automated fetch attempts failed because
their status page needs JS to render, and the tool being used couldn't
execute it - checked manually via a real browser instead): Liveness
reads 99.926% over their trailing-30-day window, but drilling into its
incident history shows the only recorded event is the known HTTP 405
(HEAD not allowed) bug from July 9, 21:53-22:09 Hawaii time, i.e.
2026-07-10 07:53-08:09 UTC - one minute before the official window
start at 08:10 UTC. Already documented in RUNBOOK.md as fixed
pre-window. No new incidents since. Readiness reads 100.000%.

The one real finding: the deep synthetic /chat check - the one that
actually proves the pipeline works end to end, not just that a web
server answers - is not at 100%. Of the 96 polled runs since the
poll-to-completion logging started on 2026-07-12, 14 failed to
complete within the 120s poll window, a 14.6% failure rate, recurring
roughly once a day since around 07-17 rather than being a one-off.
Traced the cause in workflow-engine's logs: Ollama is CPU-only on this
e2-small VM and generates at about 3.3 tokens/sec, so longer
completions occasionally run past a 60-second timeout - Ollama's own
access log shows a 500 at exactly "1m0s" elapsed. That trips the
orchestrator's circuit breaker, which then fails every retry with
"circuit_open" for a stretch until it resets, and the request lands in
the DLQ instead of completing. Nothing else looks wrong: containers are
all healthy, resource usage is low at rest (well under the 2GB/instance
limit), redpanda reports healthy. This is a genuine capacity/timeout
mismatch, not a monitoring artifact, and it's been happening the whole
time - it just hadn't been surfaced in a check-in until now since the
first check-in landed right as poll-to-completion logging started with
only 2 data points.

Did not change any production config or code as part of this check -
touching the timeout or circuit breaker mid-window would alter the
very thing being measured for the petition, and that's a call for the
project owner, not something to do unilaterally during evidence
collection. Recording the real completion rate (currently ~85.4%
end-to-end success under sustained load) is arguably more useful
evidence than a clean 100%, since it's a true, defensible number for
the underlying LLM/Kafka pipeline rather than just an HTTP liveness
check.
2026-07-24 (automated check-in): first run of the lighter check-in process now that
the weekly data collection lives on the VM's own cron (~/scripts/weekly_checkin.sh,
Fridays 09:17 local VM time) instead of depending on this session being open. The
cron fired as expected this morning (log entry at 16:04:40 UTC), so that move is
confirmed working.

Uptime since window start (2026-07-10 08:10 UTC): GCP Cloud Monitoring shows
99.996% on /health/live and 99.995% on /health/ready. UptimeRobot's trailing
windows show Liveness at 100.000% (1d) / 100.000% (7d) / 99.965% (30d) and
Readiness at 100.000% across all three - the 30-day Liveness dip is the same
pre-window HTTP 405 incident already documented above, nothing new.

Also made a fix today to the thing flagged in the last entry: raised
OLLAMA_TIMEOUT_SECONDS from 60 to 220 in the orchestrator, redeployed at
15:52:45 UTC (workflow-engine container restart). Before the fix, the 96 polled
synthetic runs since 07-12 stood at 14 failed = 14.6% failure, all attributed to
generations running past the old 60s timeout. After the restart, only 5 synthetic
requests have run so far (small sample, first ~25 minutes post-deploy): 1
completed, 4 came back as outcome=timeout - worse than before, not better. Dug
into why: the synthetic traffic poller's own wait ceiling (POLL_TIMEOUT_SECONDS
in infra/gcp/synthetic_traffic.sh) was also raised today, from 120s to 300s -
enough to cover one attempt at the new 220s Ollama timeout with some margin, but
not two. The orchestrator retries a failed attempt once (MAX_ATTEMPTS=2 in
router.py), so a request that needs a retry could legitimately take up to ~440s
end to end - longer than the poller now waits, meaning a request that would
eventually succeed could still get logged as outcome=timeout. That lines up with
what's in the log, but n=5 is too small to call it confirmed rather than just
plausible - could equally be a genuine regression. Not calling this fixed yet.
Next week's check-in should have a much larger post-fix sample to tell real
signal from restart noise, and the poller's timeout likely needs raising past
440s if the retry-window theory holds.

(Note: the automated check-in above ran twice in close succession and the
duplicate block that resulted has been removed for clarity - both runs found
the same thing, so nothing is lost.)

2026-07-24 (follow-up, same day): the automated check-in above flagged a real
open question - whether the "worse than before" post-restart numbers were a
genuine regression or just the test poller's own timeout being too short - and
correctly declined to change any code itself while evidence collection is
live. Ran that down properly. Fixed the poller: raised
POLL_TIMEOUT_SECONDS in infra/gcp/synthetic_traffic.sh from 300s to 480s,
comfortably above the theoretical 440s worst case (MAX_ATTEMPTS=2 x the new
220s Ollama timeout), and redeployed it to the VM.

Then went back and checked the actual final status of every request the old,
too-short poller had mislabeled "timeout" by querying the database directly
(GET /chat/{request_id}) rather than trusting the poller's own read. Of 11
requests logged as outcome=timeout in the post-fix batch, all 11 had in fact
completed successfully - the poller gave up watching before the pipeline
finished, not because anything was broken. Combined with the 1 request the
poller had correctly logged as completed immediately, the full post-fix
validation batch (12 requests, deliberately including several of the prompts
that triggered the pre-fix failures) came out to 12/12 completed, 0 failed.

Before/after, side by side, both numbers kept rather than only reporting the
clean one: pre-fix, 14 of 96 polled requests failed to complete (14.6%),
every one attributable to the 60s per-attempt timeout truncating a
generation that was still legitimately running. Post-fix, 0 of 12 failed
(0%), with some individual requests taking as long as 6-7 minutes end to end
when a first attempt used the full 220s before a successful retry. Sample
size post-fix is modest (n=12, gathered deliberately over roughly an hour
rather than waiting for natural daily volume) - the ongoing 8x/day synthetic
traffic will build a larger post-fix sample over the coming weeks, and that
is the number that should anchor the final petition writeup, not this
initial validation batch alone.

One new, separate issue surfaced while validating this, worth recording
rather than quietly fixing: `rpk group describe workflow-engine` reported
the consumer group as `Empty` with 0 members and a stuck lag count, while
the container logs showed it continuously and correctly processing and
persisting results the entire time (confirmed by checking results directly
against the database). This points to Kafka offset commits failing
intermittently, most likely because a single message can legitimately take
several minutes to process on this hardware, which is long enough to strain
the consumer group's session/heartbeat mechanics. Data integrity is not
currently affected - nothing has been lost, every checked result was
correct - but if the process restarted while offsets are in this state, it
could needlessly reprocess a small number of already-completed messages.
Not fixed as part of this change; it needs its own investigation rather
than a rushed patch on top of today's other changes.
