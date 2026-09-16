# Security policy

Report vulnerabilities privately through GitHub Security Advisories for this repository. Do not include private media, credentials, tokens, or model-cache contents in a report.

The CLI treats filenames as untrusted and executes FFmpeg and related tools with argument arrays, never a shell. Source media is read-only by design. Cloud transcription is not enabled by default.

The current supported release line is `0.1.x`. Security fixes are published as tagged releases and documented in the changelog.
