# Application authentication

## Architecture

```text
React UI -> .NET Google OAuth -> MongoDB application_users
React UI -> .NET JWT bearer authorization -> protected /api/rag/*
.NET -> Python -> X-RAG-API-Key + trusted application user ID
```

The .NET API is the sole browser-authentication owner. Python is an internal RAG service and does not issue or validate application-user JWTs.

## Endpoints

| Endpoint | Purpose | Authentication |
| --- | --- | --- |
| `GET /api/auth/login/google` | Starts the correlation-protected Google challenge | Anonymous |
| `GET /signin-google` | Google middleware callback | Google correlation state |
| `GET /api/auth/google/complete` | Creates/updates the MongoDB user and establishes the refresh cookie | External temporary cookie |
| `POST /api/auth/refresh` | Rotates the refresh token and returns a new access token | HttpOnly refresh cookie + allowed Origin |
| `GET /api/auth/me` | Returns the safe application profile | .NET JWT |
| `POST /api/auth/logout` | Revokes the refresh token and clears its cookie | Refresh cookie when present |
| `/api/rag/*` | Public RAG proxy operations | .NET JWT |

## MongoDB persistence

No EF Core, relational provider, SQL schema, or relational migration is used.

- `application_users` stores the internal ID, Google `sub`, normalized email, display name, avatar URL, creation time, and last-login time.
- `refresh_tokens` stores only SHA-256 token hashes, token-family IDs, expiry, revocation, replacement, and optional IP metadata.
- Unique MongoDB indexes protect Google subjects, normalized emails, and refresh-token hashes.
- A MongoDB TTL index removes expired refresh-token documents.

Indexes are created by `MongoIndexInitializer` at application startup. There is no database-migration command.

An existing email with a different Google subject is rejected and is never silently linked.

## Token and cookie decisions

- Access tokens are HMAC-SHA256 JWTs with `sub`, email, `jti`, issuer, audience, issued-at, and expiry claims.
- Default access-token lifetime: 15 minutes.
- Default refresh-token lifetime: 30 days.
- Refresh tokens are 64 random bytes, Base64URL encoded, and stored only as hashes.
- Every refresh rotates the token. Reuse of a revoked token revokes its active token family.
- Access tokens live only in JavaScript memory and disappear on reload.
- Refresh tokens use a `Secure`, `HttpOnly`, `SameSite=None` cookie scoped to `/api/auth` so the HTTP Vite origin can call the HTTPS local API. Production deployments that are same-site may tighten this to `Lax`.
- Logout revokes the refresh token. Already-issued access tokens remain valid until their short expiry; no global denylist is used.

## Google Cloud setup

Create a Web application OAuth client with the minimum `openid`, `profile`, and `email` scopes.

Local settings:

```text
Authorized JavaScript origin: http://localhost:5173
Authorized redirect URI:     https://localhost:7187/signin-google
```

Use the deployed UI/API origins and the same `/signin-google` callback path in production. Never add the Google client secret to frontend configuration.

Trust the local ASP.NET development certificate where supported:

```powershell
dotnet dev-certs https --trust
```

## Local secrets

Use placeholders when running these commands:

```powershell
dotnet user-secrets set "MongoDb:ConnectionString" "<existing-mongodb-connection-string>" --project middleware/src/RagMiddleware.Api/RagMiddleware.Api.csproj
dotnet user-secrets set "RagApi:ApiKey" "<strong-internal-service-key>" --project middleware/src/RagMiddleware.Api/RagMiddleware.Api.csproj
dotnet user-secrets set "Authentication:Google:ClientId" "<google-client-id>" --project middleware/src/RagMiddleware.Api/RagMiddleware.Api.csproj
dotnet user-secrets set "Authentication:Google:ClientSecret" "<google-client-secret>" --project middleware/src/RagMiddleware.Api/RagMiddleware.Api.csproj
dotnet user-secrets set "Authentication:Jwt:SigningKey" "<strong-random-signing-key>" --project middleware/src/RagMiddleware.Api/RagMiddleware.Api.csproj
dotnet user-secrets set "Authentication:Jwt:Issuer" "<issuer>" --project middleware/src/RagMiddleware.Api/RagMiddleware.Api.csproj
dotnet user-secrets set "Authentication:Jwt:Audience" "<audience>" --project middleware/src/RagMiddleware.Api/RagMiddleware.Api.csproj
```

Configure Python with the same internal service value through `RAG_INTERNAL_API_KEY`. Do not commit it.

Production environment-variable names:

```text
MongoDb__ConnectionString
MongoDb__DatabaseName
RagApi__BaseUrl
RagApi__ApiKey
Authentication__Google__ClientId
Authentication__Google__ClientSecret
Authentication__Google__CallbackPath
Authentication__Jwt__Issuer
Authentication__Jwt__Audience
Authentication__Jwt__SigningKey
Authentication__Jwt__AccessTokenLifetimeMinutes
Authentication__Jwt__RefreshTokenLifetimeDays
Frontend__BaseUrl
Frontend__AllowedOrigins__0
```

Azure Key Vault is the intended production secret source when deployment integration is available.
