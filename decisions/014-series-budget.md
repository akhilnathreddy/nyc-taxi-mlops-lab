# 014: Series budget: a lean keep list, and no label that changes on a deploy

Stage: S5 · Date: 2026-11-22 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`observability/alloy/budget.alloy` keeps metrics by name (a keep list per source) and drops the labels that change on every deploy:

| Source | Kept | Dropped |
| --- | --- | --- |
| Host (node exporter) | CPU, memory available and total, root filesystem space, disk bytes and I/O time, network bytes on real interfaces, load | netstat, sockstat, softnet, xfs, timex, the exporter's own `node_scrape_collector_*`; filesystems other than `/`; `lo`, Docker bridges and veths |
| Containers (cAdvisor) | CPU, working-set memory, OOM events, start time (shows restarts) | cgroups with no container name (the host's own), the `container_fs_*` family; labels `id`, `image`, `container_label_*` |
| Services | everything in `contracts/metrics.yaml` (`lab_*`), Traefik's per-service requests and latency and its entrypoint request count, `up` | Python, Go and process runtime metrics, `*_created`, Traefik's byte counters and entrypoint latency buckets |

The target for the rest of the course: stay under 2,000 active series in total (a fifth of the free tier's 10,000), so S6's LLM host, S8's canary and gameday deploys fit without revisiting this.

## Rejected alternative

Drop only the labels that churn on a deploy and keep every metric (about 3,400 series today, about 5,000 with S6's LLM host). Simplest, and nothing is missing when I'm debugging, but most of those series are exporter detail no dashboard, SLO or incident uses, and they would take half the free tier before gameday's deploys add theirs.

## Why

<!-- Draft from the evidence below: rewrite in your own words, as for 004–006. -->

Measured in Grafana Cloud (`count by (host, job) ({__name__=~".+"})`):

| | Before rules | After rules | After 3 deploys in a row |
| --- | --- | --- | --- |
| app host (Alloy active series) | 1,986 | 301 | 301 |
| platform host | 1,463 | 50 | 50 |
| Total in Grafana Cloud (includes the recording rules' output) | 3,440 | | 426 |

Where the 3,440 went: 521 of the app host's 875 cAdvisor series had no container name (the host's own cgroups); `container_fs_*` was about 15 series per container per device; 239 of its 656 node series were network statistics, and 92 were the exporter describing itself. The app's own `lab_*` metrics were about 230.

The deploy churn: every cAdvisor series carried `id` (the container's cgroup), `image` (with the `sha-` tag) and Docker Compose's labels, including a config hash and image digest. A blue-green deploy replaces a colour's container, so each deploy would have started a new set of series for it while the old set counted as active for a while. With those labels gone, `name` (`lab-app-app-blue-1`) is the identity, and three deploys in a row (cd runs 45019167645, 45019213711, 45019266841) left the count where it was.

A keep list rather than a drop list: a new exporter version or a new container metric costs nothing until I decide I need it.

## What would show this was wrong

- An incident where the metric I needed was one I dropped (disk latency, per-container network, Python GC pauses). Then add it to the keep list, by name.
- The active series count climbing after deploys again: a new label that changes per deploy.
- S6's LLM host pushing the total past 2,000.
