# OnCue cloud service

This service stores account-owned projections of local OnCue task history and
queues commands for linked computers. It never executes tasks or receives model
provider credentials, workspace files, attachments, or execution logs.

## Auth0

Create an Auth0 Single Page Application and an API. Enable only the Google social
connection for the application and configure your own Google production OAuth
credentials. Give the SPA `openid profile email` plus the API audience; Gmail API
scopes are neither needed nor requested. Add the hosted origin and each supported
OnCue loopback origin to Auth0's callback, logout, web-origin, and CORS lists.

The deployment needs these environment variables:

```text
DATABASE_URL=postgresql://...
AUTH0_DOMAIN=tenant.example.auth0.com
AUTH0_AUDIENCE=https://api.oncue.example
AUTH0_CLIENT_ID=public-spa-client-id
ONCUE_WEB_ORIGIN=https://app.oncue.example
```

Deploy `render.yaml` from the repository root. The service creates its initial
tables at startup. Use managed PostgreSQL backups before production migrations.

Each local installation needs matching non-secret configuration:

```text
ONCUE_CLOUD_URL=https://app.oncue.example
ONCUE_AUTH0_DOMAIN=tenant.example.auth0.com
ONCUE_AUTH0_AUDIENCE=https://api.oncue.example
ONCUE_AUTH0_CLIENT_ID=public-spa-client-id
```

Do not put the Google client secret or any Auth0 client secret in the local app.
The hosted service validates RS256 access tokens against Auth0's JWKS endpoint.

## Run locally

Install `cloud_service/requirements.txt`, set the variables above, and run:

```bash
uvicorn cloud_service.app:create_app --factory --reload
```

For local development only, `DATABASE_URL=sqlite:///./oncue-cloud.sqlite3` is
supported. Production uses PostgreSQL through the included Render blueprint.
