# Security Policy

## Supported Versions

Only the latest release receives security fixes.

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Use the [Private Vulnerability reporting](https://github.com/abonforti/nen-hacs-component/security/advisories/new).

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

You will receive a response within 7 days. If the issue is confirmed, a fix will be released as soon as possible and you will be credited in the release notes unless you prefer otherwise.

## Scope

This integration handles NeN account credentials (email and password). These are stored by Home Assistant using its standard secrets mechanism and are never logged or transmitted anywhere other than the NeN API (`prod.api.nen.it`).

The NeN API is unofficial and unauthenticated endpoints are not used. All requests require a valid Cognito session token obtained via SRP authentication.

## Out of Scope

- Vulnerabilities in Home Assistant core
- Vulnerabilities in NeN's own infrastructure or API
- Issues requiring physical access to the HA host
