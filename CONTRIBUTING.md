# Contributing

prism42 is a solo-maintained research build (GOATnote Inc.). Small,
focused contributions are welcome.

- Open an issue or PR against `main`; keep PRs single-topic.
- Every PR must pass `verify.yml` (cleanliness greps + full pytest —
  nothing is masked). Run `python -m pytest tests/ -q` locally first;
  the HealthBench grader tests need `third_party/simple-evals` cloned
  at the pin in `third_party/README.md`, and skip cleanly without it.
- No secrets, no absolute local paths, no pod hostnames in committed
  content. Model IDs stay env-overridable where the code allows it.
- Security reports: see SECURITY.md (b@thegoatnote.com). This is
  research software — not for clinical use.
