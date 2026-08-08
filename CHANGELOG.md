# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Monthly Rate ignored `subscriptionDiscount`, so accounts with a discount saw a higher rate than the NeN app shows. The sensor now reports the rate net of the discount. Accounts without a discount are unaffected.

### Added

- Monthly Rate exposes `rate_before_discount`, `discount` and `cost_breakdown` attributes, the last splitting the rate into the categories NeN itself uses.

## [1.0.0] - 2026-08-08

First tagged release. Everything below is what the integration ships with, not a diff against an earlier version.

### Added

- Config flow for setup through the UI with a NeN account email and password, authenticating against Cognito.
- A separate device per contract/POD, so accounts with more than one property are represented distinctly.
- Electricity sensors: consumption year-to-date, annual cap, annual cap usage percentage, last day consumption.
- Gas sensors: consumption year-to-date, last month consumption.
- Sensors for both utilities: monthly rate, commodity unit price, last bill date, last bill charge date, last bill payment status.
- English and Italian translations for the config flow.
- Device deletion for contracts the account no longer reports, so closed contracts can be removed from the UI.

### Notes

- Data is polled every 6 hours. NeN publishes no official API, so endpoints may change without notice.
- These sensors expose account-level totals and are not suitable as primary sources for the Home Assistant Energy Dashboard. See the README for details.
- Requires Home Assistant 2026.4.4 or later, enforced through `hacs.json`.

[1.0.0]: https://github.com/abonforti/nen-hacs-component/releases/tag/v1.0.0
