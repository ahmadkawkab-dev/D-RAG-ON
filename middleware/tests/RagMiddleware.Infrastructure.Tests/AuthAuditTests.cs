using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using RagMiddleware.Api.Controllers;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class AuthAuditTests
{
    [Fact]
    public async Task Missing_refresh_cookie_writes_sanitized_failure()
    {
        var audit = new RecordingAuditService();
        var controller = Controller(
            new TokenService(null),
            audit,
            new DefaultHttpContext());

        var result = await controller.Refresh(default);

        Assert.IsType<UnauthorizedResult>(result.Result);
        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.AuthRefreshFailed, entry.Action);
        Assert.Equal("INVALID_REFRESH_TOKEN", entry.FailureCode);
        Assert.Null(entry.RequestSummary);
    }

    [Fact]
    public async Task Successful_refresh_audits_user_without_token_material()
    {
        var accessToken = new JwtSecurityTokenHandler().WriteToken(
            new JwtSecurityToken(
                claims: [new Claim(JwtRegisteredClaimNames.Sub, "user-7")]));
        var pair = new TokenPair(accessToken, "plaintext-refresh-secret", 900);
        var audit = new RecordingAuditService();
        var context = new DefaultHttpContext();
        context.Request.Headers.Cookie = "__Secure-rag-refresh=incoming-secret";
        var controller = Controller(new TokenService(pair), audit, context);

        var result = await controller.Refresh(default);

        Assert.IsType<OkObjectResult>(result.Result);
        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.AuthRefreshSuccess, entry.Action);
        Assert.Equal("user-7", entry.UserId);
        var fields = string.Join(
            "|",
            entry.Action,
            entry.RequestSummary,
            entry.FailureCode,
            entry.UserId);
        Assert.DoesNotContain("plaintext-refresh-secret", fields);
        Assert.DoesNotContain("incoming-secret", fields);
        Assert.DoesNotContain(accessToken, fields);
    }

    private static AuthController Controller(
        ITokenService tokens,
        IAuditLogService audit,
        HttpContext context) =>
        new(
            new UserRepository(),
            tokens,
            audit,
            Options.Create(new JwtOptions
            {
                Issuer = "rag-middleware",
                Audience = "rag-ui",
                SigningKey = "test-signing-key-that-is-at-least-32-characters"
            }),
            Options.Create(new FrontendOptions
            {
                BaseUrl = "http://localhost:5173",
                OAuthCallbackPath = "/auth/callback",
                AllowedOrigins = ["http://localhost:5173"]
            }))
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = context
            }
        };

    private sealed class RecordingAuditService : IAuditLogService
    {
        public List<AuditLogEntry> Entries { get; } = [];

        public Task WriteAsync(
            AuditLogEntry entry,
            CancellationToken cancellationToken = default)
        {
            Entries.Add(entry);
            return Task.CompletedTask;
        }

        public Task<AuditLogPage> QueryAsync(
            AuditLogQuery query,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }

    private sealed class TokenService(TokenPair? pair) : ITokenService
    {
        public Task<TokenPair> IssueTokensAsync(
            ApplicationUser user,
            string? ipAddress,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<TokenPair?> RotateRefreshTokenAsync(
            string refreshToken,
            string? ipAddress,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(pair);

        public Task RevokeRefreshTokenAsync(
            string refreshToken,
            string? ipAddress,
            CancellationToken cancellationToken = default) =>
            Task.CompletedTask;
    }

    private sealed class UserRepository : IUserRepository
    {
        public Task<ApplicationUser?> FindByIdAsync(
            string id,
            CancellationToken cancellationToken) =>
            Task.FromResult<ApplicationUser?>(null);

        public Task<ApplicationUser?> FindByGoogleSubjectAsync(
            string subject,
            CancellationToken cancellationToken) =>
            Task.FromResult<ApplicationUser?>(null);

        public Task<ApplicationUser?> FindByNormalizedEmailAsync(
            string normalizedEmail,
            CancellationToken cancellationToken) =>
            Task.FromResult<ApplicationUser?>(null);

        public Task<ApplicationUser> CreateAsync(
            ApplicationUser user,
            CancellationToken cancellationToken) =>
            Task.FromResult(user);

        public Task UpdateAsync(
            ApplicationUser user,
            CancellationToken cancellationToken) =>
            Task.CompletedTask;
    }
}
