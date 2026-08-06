# ROI Engine — Long-Duration Soak

Scenario: `soak`
Generated: 2026-08-06T10:47:10

Validates stability under continuous processing and checks for memory leaks. FPS and memory are sampled once per second; the memory slope is computed over the last half of the run.

## Verdict

**PASS** — leak limit 100.0 MB/h, slope 0.0 MB/h.

## Configuration

- Camera: `cam_harness`
- Duration: 5.0s
- ROIs: 1600
- Warmup: 1s

## Throughput

| current | average | minimum | maximum |
| --- | --- | --- | --- |
| 2.2590842915612566 | 1.9494984778172297 | 1.0 | 2.288690193613304 |

## Memory

- Slope (tail 50%): 0.0 MB/h
- Delta: 0.0 MB
- Range: {'min': 85.23046875, 'max': 85.5234375}

## Pipeline (ms)

| average_ms | p99_ms | maximum_ms |
| --- | --- | --- |
| 435.9430545459459 | 433.7066000152845 | 576.906100002816 |

## Counters

| processed | dropped | exceptions | halcon_errors | reconnect_events |
| --- | --- | --- | --- | --- |
| 11 | 0 | 0 | 0 | 0 |

## Artifacts

- soak_metrics.json
- soak_memory.png
- soak_fps.png
