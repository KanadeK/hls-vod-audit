# Security

Only the latest 0.1.x release is currently supported. This is a small utility, with the
limitations described in README.md; it is not a general security certification tool.

Report a suspected vulnerability through the repository's **Security → Advisories →
Report a vulnerability** feature if available:
https://github.com/KanadeK/hls-vod-audit/security/advisories/new

If private reporting is unavailable, open an issue requesting a private contact channel,
without exploit details, credentials, or private files. Do not attach real secrets or
customer data to public issues. Supply a synthetic reproduction when possible.

There are no runtime package dependencies, telemetry, or automatic update services.
Use a supported Python build with current security updates. Development/build tooling is
separate from the installed runtime. See docs/design.md for project-specific boundaries.
