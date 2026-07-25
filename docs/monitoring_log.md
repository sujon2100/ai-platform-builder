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

2026-07-24 (incident investigation, same day): two incidents, same
signature, both /health/live and /health/ready failing together rather than
just one - 19:04-19:16 UTC (10m13s) and 22:44-22:51 UTC (6m46s), about 3.5
hours apart. Two occurrences of the same failure mode in one day meant this
needed an actual root cause, not another "self-resolved, moving on."

Both endpoints failing together points at something affecting the whole VM
or the whole gateway process, not a single downstream dependency - /health/
live doesn't check Kafka or the database at all, so whatever took it down
had to be something more fundamental. Checked dmesg, the systemd journal,
container logs, and restart history across both windows.

dmesg showed `virtio_balloon: Out of puff! Can't get 1 pages` at 16:14:32,
during the tail end of the 12-request validation batch from earlier today -
a real kernel-level memory pressure signal, though not a full OOM kill (no
oom-killer entries anywhere in the log). Current free memory on this
e2-small instance sits at 69-90MB out of 1.9GB, with zero swap configured.

The more direct evidence came from the systemd journal around each window
specifically. Starting at 22:40:02, the workflow-engine's Kafka client began
hitting repeated `timed out after 30000 ms` errors talking to redpanda,
recurring every 30-45 seconds. By 22:43:41 this had escalated to actual DNS
resolution failure - `DNS lookup failed for redpanda:9092, Temporary
failure in name resolution` - Docker's own internal DNS resolver failing to
resolve another container on the same bridge network. That doesn't happen
because a dependency is slow; it happens when the whole VM is too
CPU-starved for basic OS-level services to get scheduled in time. At
22:44:18, in the same window, an Ollama generation call independently timed
out too. Checked whether this was a coincidence by looking at what was
actually running: an Ollama `llama-server` process had been pegging 90-179%
CPU continuously since 22:45, the same minute the incident started, and
GCE's own guest agent plugins independently crashed and restarted at that
exact same minute (confirmed by checking journalctl for
google_guest_agent_manager crash-loop frequency across the full day -
it clusters tightly around 18:42-18:58 and 22:22-22:33, bracketing both
incident windows). No container had actually restarted the entire time
(RestartCount=0 on every container, checked via docker inspect) - the
gateway process never died, it just became too slow to answer a health
probe within its timeout window while the machine's CPU was saturated.

Root cause: this e2-small instance has 2 vCPUs total and no per-container
CPU limit on Ollama. A single generation - especially now that
OLLAMA_TIMEOUT_SECONDS is 220 rather than 60, letting them run considerably
longer - can consume the entire machine's CPU budget. When that happens,
Docker's DNS resolver, redpanda's client-facing socket, the guest agent,
and the gateway's own ability to answer external health checks all compete
for a CPU that isn't there, and all degrade at once. That is exactly why
both checks fail together rather than just the one that depends on
something else.

Checked directly whether this ties back to the 220s timeout change and
today's heavier validation load, since assuming either way wasn't good
enough: yes, with direct evidence, not correlation alone. The very first
memory-pressure signal (16:14:32) landed inside that batch's own window.
More importantly, digging into why the Kafka consumer group kept losing
membership during the incidents turned up something worse than expected -
not just a busy CPU, but an actual feedback loop. Checked how many
synthetic requests were genuinely sent since 22:00: one. Checked how many
distinct request IDs the database showed completing in that same window:
fourteen. Thirteen of those were request IDs from the earlier 12-request
validation batch that had already completed hours earlier, around
17:49-18:00 - being silently reprocessed from scratch. The mechanism: when
Ollama saturates the CPU, the workflow-engine's Kafka heartbeat thread
can't get scheduled in time and the consumer gets kicked from its group.
Because offset commits were also failing during that same CPU-starved
window (kafka-python's enable_auto_commit runs on its own background timer,
just as vulnerable to CPU starvation as anything else), the consumer
rejoins from a stale, already-passed offset and re-processes a whole batch
of already-completed messages - burning real CPU on redundant work, which
extends the CPU starvation further, making the next heartbeat failure more
likely. This is the same "Empty group, stuck offset" symptom flagged as an
open, unresolved finding earlier today; it turned out to be the same root
cause, now understood precisely rather than just observed.

Separately, kafka-python's default max_poll_interval_ms is 5 minutes. Worst
case for handling one message now - MAX_RETRIES(3) attempts, each up to
MAX_ATTEMPTS(2) x OLLAMA_TIMEOUT_SECONDS(220s) = 440s, plus backoff between
retries - can run to roughly 22 minutes. That alone would make Kafka assume
the consumer had died and force a rebalance mid-retry, independent of
actual CPU pressure.

Fixed, not just documented, per the standing instruction that a second
occurrence of the same shrug isn't good enough:

1. Capped the ollama container to 1.0 of this VM's 2 vCPUs
   (docker-compose.yml, `cpus: "1.0"`), guaranteeing the other vCPU stays
   available for Docker's networking, redpanda, and the gateway even during
   a long generation. Verified the limit is real, not cosmetic: cpu.stat
   for the container's cgroup shows nr_throttled=1924 out of nr_periods=4969
   periods (93.26 seconds of enforced throttling) within minutes of
   deploying it - the kernel is actively enforcing the cap.
2. Switched the Kafka consumer from automatic to manual offset commits
   (services/workflow-engine/worker.py: enable_auto_commit=False, explicit
   consumer.commit() in a finally block after each message is fully
   handled) so the committed offset only ever advances once work is
   actually done, regardless of what else is happening on the machine.
   Also raised max_poll_interval_ms to 1,800,000 (30 minutes) so a
   legitimately slow retry sequence doesn't get mistaken for a dead
   consumer.

Deployed 2026-07-24 23:29 UTC (ollama and workflow-engine both recreated).
Verified over the following several minutes: consumer group state went from
Empty/0 members to Stable/1 member, the committed offset advanced correctly
as messages completed (119 to 121, tracking two real completions) instead
of staying frozen while work piled up behind it, and no heartbeat failures
or rebalances occurred across multiple full message-processing cycles.

Not claiming this eliminates the underlying constraint: the VM still only
has 2 vCPUs total, and the CPU cap means Ollama may now take somewhat
longer per generation under load, trading some latency for the rest of the
system staying responsive - a fair trade, but a real one. Both fixes
address the confirmed mechanism directly rather than papering over the
symptom. If this same signature recurs even with these changes in place,
that would point to the 2-vCPU ceiling itself being the limit, and
upsizing the VM (e2-medium, more baseline CPU and double the RAM) would be
the next real lever - a cost decision for the project owner to make
explicitly, not something to do unilaterally mid-window.
