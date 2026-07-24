using System.IdentityModel.Tokens.Jwt;
using Microsoft.Extensions.Options;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Domain.Entities;
using RagMiddleware.Infrastructure.Authentication;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class JwtTokenServiceTests
{
    [Fact]
    public async Task Issues_valid_application_claims_and_hashes_refresh_tokens()
    {
        var user = User();
        var users = new UserRepository(user);
        var refresh = new RefreshRepository();
        var service = Service(users, refresh);

        var pair = await service.IssueTokensAsync(user, "127.0.0.1");
        var jwt = new JwtSecurityTokenHandler().ReadJwtToken(pair.AccessToken);

        Assert.Equal("rag-middleware", jwt.Issuer);
        Assert.Contains("rag-ui", jwt.Audiences);
        Assert.Equal(user.Id, jwt.Subject);
        Assert.Contains(jwt.Claims, claim => claim.Type == "role" && claim.Value == "Admin");
        Assert.Single(refresh.Tokens);
        Assert.NotEqual(pair.RefreshToken, refresh.Tokens[0].TokenHash);
        Assert.DoesNotContain(pair.RefreshToken, jwt.Claims.Select(x => x.Value));
    }

    [Fact]
    public async Task Refresh_rotation_revokes_the_old_token_and_logout_revokes_the_new_one()
    {
        var user = User();
        var refresh = new RefreshRepository();
        var service = Service(new UserRepository(user), refresh);
        var issued = await service.IssueTokensAsync(user, null);

        var rotated = await service.RotateRefreshTokenAsync(issued.RefreshToken, null);

        Assert.NotNull(rotated);
        Assert.NotEqual(issued.RefreshToken, rotated.RefreshToken);
        Assert.NotNull(refresh.Tokens[0].RevokedAtUtc);
        await service.RevokeRefreshTokenAsync(rotated.RefreshToken, null);
        Assert.NotNull(refresh.Tokens[1].RevokedAtUtc);
    }

    private static JwtTokenService Service(
        IUserRepository users,
        IRefreshTokenRepository refreshTokens) =>
        new(
            Options.Create(new JwtOptions
            {
                Issuer = "rag-middleware",
                Audience = "rag-ui",
                SigningKey = "test-signing-key-that-is-at-least-32-characters"
            }),
            users,
            refreshTokens);

    private static ApplicationUser User() => new()
    {
        GoogleSubject = "google-subject",
        Email = "person@example.com",
        NormalizedEmail = "PERSON@EXAMPLE.COM",
        DisplayName = "Person",
        Roles = ["Admin"]
    };

    private sealed class UserRepository(ApplicationUser user) : IUserRepository
    {
        public Task<ApplicationUser?> FindByIdAsync(string id, CancellationToken cancellationToken) =>
            Task.FromResult<ApplicationUser?>(id == user.Id ? user : null);
        public Task<ApplicationUser?> FindByGoogleSubjectAsync(string subject, CancellationToken cancellationToken) =>
            Task.FromResult<ApplicationUser?>(user.GoogleSubject == subject ? user : null);
        public Task<ApplicationUser?> FindByNormalizedEmailAsync(string normalizedEmail, CancellationToken cancellationToken) =>
            Task.FromResult<ApplicationUser?>(user.NormalizedEmail == normalizedEmail ? user : null);
        public Task<ApplicationUser> CreateAsync(ApplicationUser value, CancellationToken cancellationToken) =>
            Task.FromResult(value);
        public Task UpdateAsync(ApplicationUser value, CancellationToken cancellationToken) => Task.CompletedTask;
    }

    private sealed class RefreshRepository : IRefreshTokenRepository
    {
        public List<RefreshToken> Tokens { get; } = [];

        public Task InsertAsync(RefreshToken token, CancellationToken cancellationToken)
        {
            Tokens.Add(token);
            return Task.CompletedTask;
        }

        public Task<RefreshToken?> FindByHashAsync(string tokenHash, CancellationToken cancellationToken) =>
            Task.FromResult(Tokens.SingleOrDefault(x => x.TokenHash == tokenHash));

        public Task<bool> RotateAsync(
            string tokenHash,
            DateTimeOffset revokedAtUtc,
            string replacementHash,
            string? revokedByIp,
            CancellationToken cancellationToken)
        {
            var token = Tokens.SingleOrDefault(x => x.TokenHash == tokenHash && x.RevokedAtUtc is null);
            if (token is null) return Task.FromResult(false);
            token.RevokedAtUtc = revokedAtUtc;
            token.ReplacedByTokenHash = replacementHash;
            token.RevokedByIp = revokedByIp;
            return Task.FromResult(true);
        }

        public Task RevokeAsync(
            string tokenHash,
            DateTimeOffset revokedAtUtc,
            string? revokedByIp,
            CancellationToken cancellationToken)
        {
            var token = Tokens.SingleOrDefault(x => x.TokenHash == tokenHash);
            if (token is not null) token.RevokedAtUtc = revokedAtUtc;
            return Task.CompletedTask;
        }

        public Task RevokeFamilyAsync(
            string familyId,
            DateTimeOffset revokedAtUtc,
            string? revokedByIp,
            CancellationToken cancellationToken)
        {
            foreach (var token in Tokens.Where(x => x.FamilyId == familyId))
                token.RevokedAtUtc ??= revokedAtUtc;
            return Task.CompletedTask;
        }
    }
}
