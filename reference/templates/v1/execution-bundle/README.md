# Execution bundle

The implementation inside `src/` may use any language or layout. Keep `run.sh` as the stable entrypoint.
If a service or resource has lifecycle state, implement both `start.sh` and idempotent `destroy.sh` and
declare them in `execution.yaml`.
