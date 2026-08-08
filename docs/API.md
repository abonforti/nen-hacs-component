# NeN API reference

Notes on the endpoints this integration uses, written from observing the NeN web app's own network traffic with a logged-in account.

NeN publishes no API documentation and makes no stability commitment. Everything here describes what was observed, not what is guaranteed. Endpoints and fields change without notice.

Every identifier below is a placeholder. No account data belongs in this file.

## Base URL

```
https://prod.api.nen.it
```

AWS API Gateway behind CloudFront. Responses are JSON.

## Authentication

Login is AWS Cognito with the SRP flow, using the pool and client IDs in [`const.py`](../custom_components/nen/const.py). `pycognito` handles the challenge-response; the integration keeps the resulting **ID token** and refreshes it conservatively, five minutes before expiry.

The non-obvious part is that the ID token is sent **two different ways** depending on the endpoint:

| Header form | Endpoints |
| --- | --- |
| `Authorization: Bearer <id_token>` | `/profile/*`, `/miaproxy-auth/*`, `/invoices` |
| `Authorization: <id_token>` (no prefix) | `/subscriptions/contract/*`, `/consumptions/*`, `/bills/details/*` |

Sending the wrong form returns 401. In the code this is the `raw_auth` argument of `_request()`.

A 401 mid-session means the token expired; re-authenticating and retrying once is enough.

Some endpoints the web app uses but this integration does not, such as `/ocr/bill/extract-data`, require full AWS SigV4 request signing rather than a token.

## Endpoints

### `GET /profile/home-contexts`

The entry point. Returns one entry per property on the account.

```
[
  {
    "id", "name", "address", "fullAddress", "isDefault",
    "iconName", "color", "type",
    "subscriptions": [
      { "id", "utility", "status", "podName", "pdeCode",
        "supplyId", "is2g", "contractInformation" }
    ]
  }
]
```

Notes:

- `utility` is `"EE"` (electricity) or `"GA"` (gas).
- `status` is `"ACTIVE"` here. Other endpoints use the Italian `"ATTIVO"` for the same idea, so do not compare across endpoints.
- An account can hold several properties, and a property several subscriptions. Do not assume `[0]`.
- `supplyId` is needed for consumption queries and is only available here.

### `GET /subscriptions/contract/{subscriptionId}`

Raw ID token, plus `?origin=Web`. Contract and pricing detail.

```
{
  "subscriptionPrice", "subscriptionDiscount",
  "renewalDate", "recalculationDate", "prospectedActivationDate",
  "rawMaterialRenewal", "offerType", "initialConsumption",
  "realVolume", "balanceAmount",
  "timeline": [...], "additionalProduct": [...],
  "documents": { "contract", "rdf" },
  "billDetails": [...],
  "billDetailsPreviousYear": [...],
  "billDetailsExtraordinary": [...]
}
```

Notes:

- `subscriptionPrice` is the monthly rate **before** discounts. `subscriptionDiscount` is already signed negative, so the net rate the app shows is the sum of the two. Accounts without a discount return `0`.
- NeN states how the rate is built: the last twelve months of actual consumption (or a projection of what is missing) multiplied by the energy price, plus the fixed sales quota, taxes, transport, meter management and the TV licence, plus the cuscinetto, all divided by twelve. The `billDetails` categories are that calculation, already broken down.
- `billDetails` splits the rate into categories, each `{ id, categoryLabel, categoryLabelValue, expandedContent }`. Observed category ids include `notOnNeN`, `consumo`, `fixedPrice`, `services` and `cuscinettoDebitoPromo`. The values add up to `subscriptionPrice`.
- A discount appears as its own `billDetails` category **only on accounts that have one**, so it is absent from captures taken on accounts without discounts. `additionalProduct[].discount` is a second place discounts can appear.
- The **cuscinetto** users see in the NeN app is the `cuscinettoDebitoPromo` category inside `billDetails`, a monthly component of the rate. It is not a running total, and the app shows no accumulated figure. The integration exposes it through the Monthly Rate sensor's `cost_breakdown` attribute.
- `balanceAmount` looks like it should be the accumulated cuscinetto balance, but it reads `0` on every contract checked, including on an account that pays a non-zero `cuscinettoDebitoPromo` every month. Its meaning is unconfirmed. Do not expose it as a balance without a non-zero sample and a known sign convention.
- `offerType` encodes the contract length in months, for example `EE_120` or `GA_12`.
- `initialConsumption` and `realVolume` both equal the annual cap already available as `annualConsumptions.maxConsumption`, so they add nothing.
- Dates are `YYYY-MM-DD`. `prospectedActivationDate` is NeN's wording for a *planned* activation, so on a supply still being activated it is a future date rather than a historical one.

### `GET /consumptions/b2c/global-consumptions`

Raw ID token, with `?supplyId={supplyId}&origin=web`.

```
{
  "isRoboActive", "is2G",
  "annualConsumptions": {
    "totalConsumption", "maxConsumption", "deltaPercentage",
    "distributorRealConsumption", "distributorEstimatedConsumption",
    "g2Consumption", "g2EstimatedConsumption", "g2EstimatedDays",
    "consumptionStartDate", "lastDay2GConsumptionReceived",
    "missingValues", "partialValues", "isEmpty", "is2GEmpty"
  },
  "consumptions": {
    "g2": { "data": [ { "period", "value",
                        "isEstimated", "isPartial", "isMissing" } ] },
    "pastMonths": [ { "period", "realConsumption", "estimatedConsumption" } ]
  },
  "peaks": {...},
  "readings": [...]
}
```

Notes:

- Units are kWh for electricity, Sm³ for gas.
- `consumptions.g2.data` is the daily series from a second-generation smart meter. Entries flagged `isMissing` or `isPartial` carry unusable values and must be skipped; zero values appear too.
- Meters that are not 2G leave `g2.data` empty. `pastMonths` is the fallback, at monthly rather than daily resolution, with `realConsumption` preferred over `estimatedConsumption`.
- `maxConsumption` is the annual cap from the contract, `totalConsumption` the year-to-date figure.
- `deltaPercentage` is NeN's own pacing indicator against the cap. Its exact definition is undocumented.

### `GET /miaproxy-auth/users/subscription-detail`

Bearer token, with `?code={opportunityCode}&subscriptionId={subscriptionId}`. Pricing and supply detail.

```
{
  "id", "code", "status", "subscriptionPrice",
  "productVersion": { "consumptionPrice", "price", "annualFixedPrice",
                      "dispatchingPrice", "committedPowerPrice", "pcv", ... },
  "supply": { "id", "name", "utility", "status", "meterType",
              "smartMeter", "committedPower", "address", ... },
  "paymentMethod": {...}, "priceCalculations": [...],
  "additionalProducts": [...], "activeRepetitionDiscounts": [...]
}
```

Notes:

- **Prices here use Italian decimal notation**, as strings with a comma: `"0,13943"`. Passing them to `float()` raises. This is the single most common way to break this integration.
- `supply.name` is the POD/PDR code.
- `supply.status` is `"ATTIVO"`, not `"ACTIVE"`.
- The `code` parameter is the opportunity code, which comes from `/profile/details`, not from `/profile/home-contexts`.

### `GET /profile/details`

Bearer token. Account holder details plus the opportunity `code` per subscription.

```
{
  "id", "email", "firstName", "lastName", "phone", "taxCode",
  "communicationAddress", "contactKey", "privacy1", "privacy2", "privacy3",
  "subscriptions": [ { "id", "code", "supply", "paymentMethod",
                       "homeContextId", "homeContextFullName", ... } ]
}
```

This response carries personal data (tax code, email, address). The integration reads only `subscriptions[].id` and `subscriptions[].code`. Redact the rest before pasting it anywhere.

### `GET /bills/details/{homeContextId}`

Raw ID token. Invoice history for one property.

```
{ "invoices": [ { "utility", "number", "amount",
                  "emissionDate", "chargeDate", "status", "residual" } ] }
```

Notes:

- Scoped by home context, not by subscription, and each invoice is tagged with its own `utility`. Fetch per property, or one property's bills will surface on another's.
- Invoices come newest first.
- `status` values include `PAY_OK`.

### `GET /invoices`

Bearer token, with `?month=MM&year=YYYY&pods=POD1,POD2`. Returns `{ "podInvoices": [...] }`.

**Not used by the integration.** Documented because it exists and once was.

A capture of the site's traffic in 2026-07 showed no call to it; the frontend uses `/bills/details/{homeContextId}` instead. The integration used to call it, but nothing ever read the result, so it was one wasted request per refresh. Removed rather than kept on the chance some account still needs it: if that turns out to be true, the endpoint is documented here and the caller is four lines.

## Capturing traffic

1. Log in at [nen.it](https://www.nen.it) in a browser.
2. Open DevTools, Network tab, filter on `prod.api.nen.it`.
3. Navigate the app until the value you care about appears on screen.
4. Copy the response.

Strip identifiers before sharing: POD/PDR, IBAN, tax code, email, address, and the Salesforce-style ids (`a0K2p...`). Issues on this repository are public.

If a field only appears under a condition you cannot reproduce, such as an active discount, say so rather than assuming it is absent.
