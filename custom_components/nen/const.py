DOMAIN = "nen"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Subscriptions the user chose not to set up. Exclusions are stored rather than
# inclusions so a contract added to the account later appears by default
# instead of being silently dropped.
CONF_EXCLUDED = "excluded_subscriptions"

# These are extracted from NeN's public frontend JS bundle (nen.it/react-assets/index.js)
# and are not private secrets — they identify the Cognito user pool for B2C auth.
COGNITO_USER_POOL_ID = "eu-central-1_zGQHXW8Qs"
COGNITO_CLIENT_ID = "47pks374hb18qs9u050v2ecpl8"
API_BASE_URL = "https://prod.api.nen.it"

SCAN_INTERVAL_HOURS = 6
