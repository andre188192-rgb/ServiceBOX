# Locked file notes

## TODOs blocked by lock guard
- Add import regression test for `src.domain.validator` and `src.domain.apply_event` in a new test file.
  (Locked because `tests/test_events.py` is explicitly excluded from edits.)
- Admin KPI rebuild endpoint was not added because it would require wiring into existing router setup.
  (Core routing files are locked.)
