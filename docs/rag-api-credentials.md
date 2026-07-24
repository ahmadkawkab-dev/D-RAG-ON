# RAG API credential ownership

| Configuration name | Purpose | Owner | Secret |
| --- | --- | --- | --- |
| `RagApi:BaseUrl` | Locates the internal Python API | .NET middleware | No |
| `RagApi:ApiKey` / `RAG_INTERNAL_API_KEY` | Authenticates .NET to Python | .NET User Secrets/Key Vault and Python environment | Yes |
| `MongoDb:ConnectionString` | Persists .NET users and refresh-token hashes in MongoDB | .NET User Secrets/Key Vault | Yes when credentials are embedded |
| `Authentication:Google:ClientSecret` | Authenticates the OAuth client to Google | .NET User Secrets/Key Vault | Yes |
| `Authentication:Jwt:SigningKey` | Signs application access tokens | .NET User Secrets/Key Vault | Yes |
| `RAG_OLLAMA_API_KEY` | Authenticates Python-owned provider calls | Python environment | Yes |

The UI owns none of these values. It receives only a short-lived .NET access token and never receives the refresh token or Python service credential.

See [authentication.md](authentication.md) for setup commands and [rag-api-proxy.md](rag-api-proxy.md) for the server-to-server trust boundary.
