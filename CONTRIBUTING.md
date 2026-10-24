# Contributing

Start with a minimal reproduction or a proposal in Issues. Use invented data and include
the tool version, Python version, operating system, command, expected result, and actual
result. Keep private data out of reports. Changes should stay inside the documented scope.

Development (Python 3.11+):

```sh
python -m venv .venv
# Activate .venv using your shell, then:
python -m pip install -e . -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m coverage run -m unittest discover -s tests
python -m coverage report
python -m ruff check .
python -m ruff format --check .
python -m build
```

Keep tests independent of external services. Add regression coverage for behavior changes;
document input/output compatibility and avoid new runtime dependencies without a clear
need. All original code is MIT licensed. Preserve third-party copyrights if proposing any
reuse. CI never writes commits, and third-party patches are never automatically merged.
