using System.IdentityModel.Tokens.Jwt;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Infrastructure.Persistence;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class HardeningIntegrationTests
{
    [Fact]
    public async Task Approved_cors_and_security_headers_are_applied()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            "https://localhost/health");
        request.Headers.TryAddWithoutValidation("Origin", "http://localhost:5173");

        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(
            "http://localhost:5173",
            response.Headers.GetValues("Access-Control-Allow-Origin").Single());
        Assert.Equal(
            "nosniff",
            response.Headers.GetValues("X-Content-Type-Options").Single());
        Assert.Equal(
            "no-referrer",
            response.Headers.GetValues("Referrer-Policy").Single());
        Assert.False(response.Headers.Contains("Server"));
    }

    [Fact]
    public async Task Unknown_cors_origin_is_not_reflected()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            "https://localhost/health");
        request.Headers.TryAddWithoutValidation("Origin", "https://untrusted.example");

        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(response.Headers.Contains("Access-Control-Allow-Origin"));
    }

    [Fact]
    public async Task Cors_preflight_allows_only_expected_method_and_headers()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        using var request = new HttpRequestMessage(
            HttpMethod.Options,
            "https://localhost/api/rag/general/stream");
        request.Headers.TryAddWithoutValidation("Origin", "http://localhost:5173");
        request.Headers.TryAddWithoutValidation(
            "Access-Control-Request-Method",
            "POST");
        request.Headers.TryAddWithoutValidation(
            "Access-Control-Request-Headers",
            "authorization,content-type");

        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Contains(
            "POST",
            response.Headers.GetValues("Access-Control-Allow-Methods").Single());
        var headers = response.Headers
            .GetValues("Access-Control-Allow-Headers")
            .Single();
        Assert.Contains("authorization", headers, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("content-type", headers, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Anonymous_rag_is_unauthorized_and_non_admin_is_forbidden()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();

        using var anonymous = await client.GetAsync(
            "https://localhost/api/rag/history/sessions");
        using var nonAdmin = new HttpRequestMessage(
            HttpMethod.Get,
            "https://localhost/api/admin/audit-logs");
        nonAdmin.Headers.Authorization =
            new AuthenticationHeaderValue("Bearer", Token("user-1"));
        using var forbidden = await client.SendAsync(nonAdmin);

        Assert.Equal(HttpStatusCode.Unauthorized, anonymous.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, forbidden.StatusCode);
    }

    [Fact]
    public async Task Admin_can_query_audit_logs()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            "https://localhost/api/admin/audit-logs?page=1&pageSize=10");
        request.Headers.Authorization =
            new AuthenticationHeaderValue("Bearer", Token("admin-1", "Admin"));

        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Rag_rate_limit_returns_429_retry_after_and_audit()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        var statuses = new List<HttpStatusCode>();
        for (var index = 0; index < 3; index++)
        {
            using var request = new HttpRequestMessage(
                HttpMethod.Get,
                "https://localhost/api/rag/history/sessions");
            request.Headers.Authorization =
                new AuthenticationHeaderValue("Bearer", Token("rate-user"));
            using var response = await client.SendAsync(request);
            statuses.Add(response.StatusCode);
            if (index == 2)
                Assert.True(response.Headers.RetryAfter is not null);
        }

        Assert.Equal(
            [
                HttpStatusCode.OK,
                HttpStatusCode.OK,
                HttpStatusCode.TooManyRequests
            ],
            statuses);
        Assert.Contains(
            factory.Audit.Entries,
            entry => entry.StatusCode == 429
                && entry.Endpoint.Contains("/api/rag", StringComparison.Ordinal));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Empty_rag_message_returns_400(string message)
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            "https://localhost/api/rag/general/stream");
        request.Headers.Authorization =
            new AuthenticationHeaderValue("Bearer", Token(Guid.NewGuid().ToString("N")));
        request.Content = JsonContent.Create(new
        {
            message,
            session_id = (string?)null,
            regenerate_message_id = (string?)null
        });

        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Invalid_upload_is_rejected_before_python()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            "https://localhost/api/rag/documents/upload");
        request.Headers.Authorization =
            new AuthenticationHeaderValue("Bearer", Token("upload-user"));
        using var form = new MultipartFormDataContent();
        using var content = new ByteArrayContent("not a pdf"u8.ToArray());
        content.Headers.ContentType = new MediaTypeHeaderValue("text/plain");
        form.Add(content, "file", "unsafe.txt");
        request.Content = form;

        using var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal(0, factory.Rag.UploadCalls);
    }

    [Fact]
    public async Task Unexpected_failure_returns_safe_500_with_trace()
    {
        await using var factory = new HardeningFactory();
        using var client = factory.Client();
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            "https://localhost/api/rag/history/sessions?mode=document");
        request.Headers.Authorization =
            new AuthenticationHeaderValue("Bearer", Token("error-user"));

        using var response = await client.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Contains("trace_id", body);
        Assert.DoesNotContain("sensitive stack detail", body);
        Assert.DoesNotContain("InvalidOperationException", body);
    }

    [Fact]
    public async Task Swagger_is_development_only_and_contains_no_internal_key_input()
    {
        await using var development = new HardeningFactory();
        using var developmentClient = development.Client();
        using var swagger = await developmentClient.GetAsync(
            "https://localhost/swagger/v1/swagger.json");
        var document = await swagger.Content.ReadAsStringAsync();

        await using var production = new HardeningFactory("Production");
        using var productionClient = production.Client();
        using var unavailable = await productionClient.GetAsync(
            "https://localhost/swagger/v1/swagger.json");

        Assert.Equal(HttpStatusCode.OK, swagger.StatusCode);
        Assert.DoesNotContain("X-RAG-API-Key", document);
        Assert.Equal(HttpStatusCode.NotFound, unavailable.StatusCode);
    }

    [Fact]
    public async Task Production_redirects_http_and_adds_hsts_to_https()
    {
        await using var factory = new HardeningFactory("Production");
        using var redirectClient = factory.Client();
        using var secureClient = factory.Client();

        using var redirect = await redirectClient.GetAsync("http://localhost/health");
        using var secure = await secureClient.GetAsync("/health");

        Assert.Equal(HttpStatusCode.TemporaryRedirect, redirect.StatusCode);
        Assert.StartsWith("https://", redirect.Headers.Location?.ToString());
        Assert.True(secure.Headers.Contains("Strict-Transport-Security"));
    }

    private static string Token(string userId, params string[] roles)
    {
        var now = DateTime.UtcNow;
        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, userId),
            new(JwtRegisteredClaimNames.Email, "test@example.com")
        };
        claims.AddRange(roles.Select(role => new Claim("role", role)));
        var key = new SymmetricSecurityKey(
            Encoding.UTF8.GetBytes(HardeningFactory.SigningKey));
        return new JwtSecurityTokenHandler().WriteToken(new JwtSecurityToken(
            issuer: "rag-middleware",
            audience: "rag-ui",
            claims: claims,
            notBefore: now.AddMinutes(-1),
            expires: now.AddMinutes(5),
            signingCredentials: new SigningCredentials(
                key,
                SecurityAlgorithms.HmacSha256)));
    }

    private sealed class HardeningFactory(
        string environment = "Development") : WebApplicationFactory<Program>
    {
        public const string SigningKey =
            "hardening-test-signing-key-that-is-at-least-32-characters";

        public RecordingAuditService Audit { get; } = new();
        public FakeRagClient Rag { get; } = new();

        protected override void ConfigureWebHost(IWebHostBuilder builder)
        {
            builder.UseEnvironment(environment);
            builder.ConfigureAppConfiguration((_, configuration) =>
                configuration.AddInMemoryCollection(
                    new Dictionary<string, string?>
                    {
                        ["RagApi:BaseUrl"] = "http://python.internal",
                        ["RagApi:ApiKey"] =
                            "internal-test-key-that-is-at-least-32-characters",
                        ["MongoDb:ConnectionString"] =
                            "mongodb://localhost:27017",
                        ["MongoDb:DatabaseName"] = "test",
                        ["Authentication:Google:ClientId"] = "test-client",
                        ["Authentication:Google:ClientSecret"] = "test-secret",
                        ["Authentication:Jwt:Issuer"] = "rag-middleware",
                        ["Authentication:Jwt:Audience"] = "rag-ui",
                        ["Authentication:Jwt:SigningKey"] = SigningKey,
                        ["Frontend:BaseUrl"] = "http://localhost:5173",
                        ["Frontend:OAuthCallbackPath"] = "/auth/callback",
                        ["Frontend:AllowedOrigins:0"] =
                            "http://localhost:5173",
                        ["RateLimiting:RagTokenLimit"] = "2",
                        ["RateLimiting:RagTokensPerPeriod"] = "2",
                        ["RateLimiting:RagReplenishmentSeconds"] = "3600",
                        ["HttpsRedirection:HttpsPort"] = "443"
                    }));
            builder.ConfigureTestServices(services =>
            {
                services.RemoveAll<IHostedService>();
                services.RemoveAll<IAuditLogService>();
                services.RemoveAll<IRagApiClient>();
                services.AddSingleton<IAuditLogService>(Audit);
                services.AddSingleton<IRagApiClient>(Rag);
            });
        }

        public HttpClient Client() =>
            CreateClient(new WebApplicationFactoryClientOptions
            {
                AllowAutoRedirect = false,
                BaseAddress = new Uri("https://localhost")
            });
    }

    private sealed class RecordingAuditService : IAuditLogService
    {
        public List<AuditLogEntry> Entries { get; } = [];

        public Task WriteAsync(
            AuditLogEntry entry,
            CancellationToken cancellationToken = default)
        {
            lock (Entries)
                Entries.Add(entry);
            return Task.CompletedTask;
        }

        public Task<AuditLogPage> QueryAsync(
            AuditLogQuery query,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(new AuditLogPage(
                [],
                query.Page,
                query.PageSize,
                0));
    }

    private sealed class FakeRagClient : IRagApiClient
    {
        public int UploadCalls { get; private set; }

        public Task<RagStreamResponse> StreamChatAsync(
            string mode,
            RagChatRequest request,
            string userId,
            CancellationToken cancellationToken)
        {
            var response = new HttpResponseMessage(HttpStatusCode.OK);
            return Task.FromResult(new RagStreamResponse(
                response,
                new MemoryStream()));
        }

        public Task<IReadOnlyList<ChatSessionResponse>> ListSessionsAsync(
            string? mode,
            string userId,
            CancellationToken cancellationToken) =>
            mode == "document"
                ? throw new InvalidOperationException("sensitive stack detail")
                : Task.FromResult<IReadOnlyList<ChatSessionResponse>>([]);

        public Task<ChatSessionDetail> GetSessionAsync(
            string sessionId,
            string userId,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<DeleteSessionResponse> DeleteSessionAsync(
            string sessionId,
            string userId,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();

        public Task<DocumentUploadResponse> UploadDocumentAsync(
            Stream stream,
            long sizeBytes,
            string userId,
            CancellationToken cancellationToken)
        {
            UploadCalls++;
            return Task.FromResult(
                new DocumentUploadResponse("document-1", 1, "indexed"));
        }

        public Task<FeedbackResponse> SaveFeedbackAsync(
            string messageId,
            FeedbackRequest request,
            string userId,
            CancellationToken cancellationToken) =>
            throw new NotSupportedException();
    }
}
