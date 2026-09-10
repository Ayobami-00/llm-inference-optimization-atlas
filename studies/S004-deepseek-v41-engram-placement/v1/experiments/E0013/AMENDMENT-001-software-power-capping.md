# Preregistration amendment 001: NVIDIA software power capping

Status: approved prospectively on 2026-09-10 at 22:35:09 UTC, before restarting
the first confirmatory configuration.

## Why this amendment exists

The original invalidation rule grouped every power- or thermal-throttling reason
into one condition. During two otherwise independent CFG021 attempts, GPU 0
intermittently reported NVIDIA clocks-event reason `0x4` (`SW_POWER_CAP`) on a
node whose preflight and point-in-time post-attempt checks reported the expected
1000 W configured limit. The first attempt contained 24 such samples among
7,312 GPU samples; the second contained 20 among 7,816. Neither attempt reported
a GPU Xid, a new ECC error, a thermal slowdown, a hardware power brake, or a
competing GPU process. Those attempts did not record `power.limit` in every
collector cycle, however, so they cannot establish that the configured limit
remained unchanged throughout measurement.

`SW_POWER_CAP` means software power scaling reduced clocks while the accelerator
was operating against its configured power envelope. It is a property of the
measured deployment and may affect performance, so it must be retained and
reported. It is not, by itself, evidence that the provider changed the frozen
power limit or that the machine suffered a thermal or hardware slowdown.

## Prospective policy

Starting with the next freshly initialized CFG021 attempt:

- `0x4` (`SW_POWER_CAP`) is non-invalidating only when every mandatory collector
  sample contains a readable per-GPU configured power limit equal to the frozen
  1000 W value.
- Every `0x4` observation remains in telemetry. The run summary reports its
  count, observation count, and incidence for each GPU and in aggregate.
- Any configured power-limit change invalidates the attempt.
- NVIDIA hardware slowdown (`0x8`), software thermal slowdown (`0x20`), hardware
  thermal slowdown (`0x40`), or hardware power brake (`0x80`) invalidates the
  attempt. GPU Xid events and new ECC errors remain invalidating.
- Existing treatment, fingerprint, request-accounting, dispatch-lag, server,
  evidence-completeness, and competing-process rules are unchanged.
- Because the telemetry query changed, the preregistered collector-on/off
  overhead pilot is repeated with the amended collector before any new
  confirmatory attempt. The original pilot remains preserved but is not reused.
- Collector shutdown waits for a complete bounded sampling cycle. A collector
  that cannot terminate within that bound records a terminal error and makes
  the attempt ineligible rather than exposing a mutable partial snapshot.

This amendment does not change the model, configurations, workload, ordering,
SLOs, quality gate, metrics, estimand, analysis, or decision thresholds.

## Treatment of data observed before approval

Both prior CFG021 attempts remain invalid and are never eligible for promotion,
comparison, inference, or a finding. They were evaluated under the original
rule and lack per-cycle configured-power-limit observations required by the new
rule. `block-1-CFG021` also remains invalid for its dispatch-lag failure;
`block-1-CFG021-retry-1` remains invalid under the original all-power-throttling
rule. Their files remain preserved under the ignored `.atlas/work` directory
for audit. No CFG022 or CFG023 confirmatory attempt had begun and no run had
been accepted when this amendment was approved. CFG021 therefore restarts from
a new server process and clean runtime-cache state after this amendment is
committed, pushed, and the public proposal is re-approved.

The amendment was triggered by baseline-only health telemetry, not by a
between-configuration effect. Although the invalid attempts reached performance
measurement, none of their performance observations may be substituted into the
five preregistered paired blocks.

## Rationale

Keeping the old attempts invalid avoids retrospectively changing whether
already-observed data qualify. Applying the refined rule only to new attempts
preserves a clear temporal boundary while measuring the B200s inside their real,
unchanged 1000 W operating envelope. Reporting `SW_POWER_CAP` incidence allows
readers to judge whether the behavior is balanced across treatments or could
limit generalization.

The clock-event and power-limit terminology follows the official NVIDIA
Management Library API Reference Guide (`atlas://source/SRC0113@v1`).
