# Security and privacy

This repository is designed to ship mechanisms, not memories.

Do not commit real Vault content, personal Agent rules, worklogs, project evidence, install receipts, absolute personal paths, credentials, API keys, cookies, full database connection strings, or `.env` files.

The installer writes only after an explicit confirmation flag and backs up existing rule files before changing the managed block. Review `install-plan.json` before applying it. If a secret was ever committed, removing it from the latest tree is insufficient: revoke it and clean the Git history before publishing.

Please report vulnerabilities through GitHub's private security reporting rather than a public issue.
