# Security Policy

## Reporting a vulnerability

Please do not open a public issue for authentication, authorization, credential,
file-upload, or remote-code-execution vulnerabilities. Use GitHub's private
security advisory feature for this repository instead.

Include the affected route or component, reproduction steps, expected impact,
and a minimal proof of concept. Do not include real passwords, API keys, student
data, or uploaded course files in the report.

## Deployment expectations

- Store `SECRET_KEY`, `DEEPSEEK_API_KEY`, database files, and user uploads only
  on the server; never commit them to Git.
- Serve PAM login pages over HTTPS outside a trusted private network.
- Run the application as a dedicated unprivileged Linux account.
- Grant teacher and assistant roles through dedicated groups, not through root
  or sudo access.
- Rotate any credential immediately if it is ever committed, even if the commit
  is later deleted.
