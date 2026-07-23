using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using RagMiddleware.Api.Controllers;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class AuthEventControllerTests
{
    [Fact]
    public async Task Successful_google_completion_writes_login_success()
    {
        var principal = new ClaimsPrincipal(new ClaimsIdentity(
            [
                new Claim(ClaimTypes.NameIdentifier, "google-subject"),
                new Claim(ClaimTypes.Email, "person@example.com"),
                new Claim(ClaimTypes.Name, "Person")
            ],
            "External"));
        var auth = new StubAuthenticationService(
            AuthenticateResult.Success(
                new AuthenticationTicket(
                    principal,
                    new AuthenticationProperties(),
                    "External")));
        var audit = new RecordingAuditService();
        var controller = Controller(auth, audit);

        var result = await controller.CompleteGoogleLogin(default);

        Assert.IsType<RedirectResult>(result);
        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.AuthLoginSuccess, entry.Action);
        Assert.NotNull(entry.UserId);
        Assert.DoesNotContain("google-subject", entry.RequestSummary ?? "");
        Assert.DoesNotContain("person@example.com", entry.RequestSummary ?? "");
    }

    [Fact]
    public async Task Failed_google_completion_writes_high_level_failure()
    {
        var audit = new RecordingAuditService();
        var controller = Controller(
            new StubAuthenticationService(
                AuthenticateResult.Fail("provider detail")),
            audit);

        var result = await controller.CompleteGoogleLogin(default);

        Assert.IsType<UnauthorizedObjectResult>(result);
        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.AuthLoginFailed, entry.Action);
        Assert.Equal("GOOGLE_CALLBACK_FAILED", entry.FailureCode);
        Assert.DoesNotContain("provider detail", entry.RequestSummary ?? "");
    }

    [Fact]
    public async Task Logout_writes_one_event_without_cookie_content()
    {
        var audit = new RecordingAuditService();
        var controller = Controller(
            new StubAuthenticationService(AuthenticateResult.NoResult()),
            audit);

        var result = await controller.Logout(default);

        Assert.IsType<NoContentResult>(result);
        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.AuthLogout, entry.Action);
        Assert.Equal("Session logout requested", entry.RequestSummary);
    }

    private static AuthController Controller(
        IAuthenticationService authentication,
        IAuditLogService audit)
    {
        var services = new ServiceCollection()
            .AddSingleton(authentication)
            .BuildServiceProvider();
        var context = new DefaultHttpContext
        {
            RequestServices = services,
            Response = { Body = new MemoryStream() }
        };
        return new AuthController(
            new UserRepository(),
            new TokenService(),
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
    }

    private sealed class StubAuthenticationService(
        AuthenticateResult result) : IAuthenticationService
    {
        public Task<AuthenticateResult> AuthenticateAsync(
            HttpContext context,
            string? scheme) =>
            Task.FromResult(result);

        public Task ChallengeAsync(
            HttpContext context,
            string? scheme,
            AuthenticationProperties? properties) =>
            Task.CompletedTask;

        public Task ForbidAsync(
            HttpContext context,
            string? scheme,
            AuthenticationProperties? properties) =>
            Task.CompletedTask;

        public Task SignInAsync(
            HttpContext context,
            string? scheme,
            ClaimsPrincipal principal,
            AuthenticationProperties? properties) =>
            Task.CompletedTask;

        public Task SignOutAsync(
            HttpContext context,
            string? scheme,
            AuthenticationProperties? properties) =>
            Task.CompletedTask;
    }

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

    private sealed class TokenService : ITokenService
    {
        public Task<TokenPair> IssueTokensAsync(
            ApplicationUser user,
            string? ipAddress,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(new TokenPair(
                "access-token-not-audited",
                "refresh-token-not-audited",
                900));

        public Task<TokenPair?> RotateRefreshTokenAsync(
            string refreshToken,
            string? ipAddress,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<TokenPair?>(null);

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
