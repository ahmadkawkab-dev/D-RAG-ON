using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.WebUtilities;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Authentication;

public sealed class JwtTokenService(
    IOptions<JwtOptions> options,
    IUserRepository users,
    IRefreshTokenRepository refreshTokens) : ITokenService
{
    private readonly JwtOptions _options = options.Value;

    public async Task<TokenPair> IssueTokensAsync(
        ApplicationUser user,
        string? ipAddress,
        CancellationToken cancellationToken = default)
    {
        var familyId = Guid.NewGuid().ToString("N");
        return await CreateTokenPairAsync(user, familyId, ipAddress, cancellationToken);
    }

    public async Task<TokenPair?> RotateRefreshTokenAsync(
        string refreshToken,
        string? ipAddress,
        CancellationToken cancellationToken = default)
    {
        var hash = HashRefreshToken(refreshToken);
        var current = await refreshTokens.FindByHashAsync(hash, cancellationToken);
        if (current is null)
        {
            return null;
        }

        var now = DateTimeOffset.UtcNow;
        if (current.RevokedAtUtc is not null)
        {
            await refreshTokens.RevokeFamilyAsync(
                current.FamilyId,
                now,
                ipAddress,
                cancellationToken);
            return null;
        }

        if (current.ExpiresAtUtc <= now)
        {
            return null;
        }

        var user = await users.FindByIdAsync(current.UserId, cancellationToken);
        if (user is null)
        {
            return null;
        }

        var replacementValue = GenerateRefreshToken();
        var replacementHash = HashRefreshToken(replacementValue);
        var rotated = await refreshTokens.RotateAsync(
            hash,
            now,
            replacementHash,
            ipAddress,
            cancellationToken);
        if (!rotated)
        {
            await refreshTokens.RevokeFamilyAsync(
                current.FamilyId,
                now,
                ipAddress,
                cancellationToken);
            return null;
        }

        var replacement = NewRefreshToken(
            user.Id,
            current.FamilyId,
            replacementValue,
            ipAddress,
            now);
        await refreshTokens.InsertAsync(replacement, cancellationToken);
        return new TokenPair(
            CreateAccessToken(user, now),
            replacementValue,
            _options.AccessTokenLifetimeMinutes * 60);
    }

    public async Task RevokeRefreshTokenAsync(
        string refreshToken,
        string? ipAddress,
        CancellationToken cancellationToken = default)
    {
        await refreshTokens.RevokeAsync(
            HashRefreshToken(refreshToken),
            DateTimeOffset.UtcNow,
            ipAddress,
            cancellationToken);
    }

    private async Task<TokenPair> CreateTokenPairAsync(
        ApplicationUser user,
        string familyId,
        string? ipAddress,
        CancellationToken cancellationToken)
    {
        var now = DateTimeOffset.UtcNow;
        var refreshValue = GenerateRefreshToken();
        await refreshTokens.InsertAsync(
            NewRefreshToken(user.Id, familyId, refreshValue, ipAddress, now),
            cancellationToken);
        return new TokenPair(
            CreateAccessToken(user, now),
            refreshValue,
            _options.AccessTokenLifetimeMinutes * 60);
    }

    private string CreateAccessToken(ApplicationUser user, DateTimeOffset now)
    {
        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, user.Id),
            new(JwtRegisteredClaimNames.Email, user.Email),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString("N")),
            new(JwtRegisteredClaimNames.Iat, now.ToUnixTimeSeconds().ToString(), ClaimValueTypes.Integer64)
        };
        if (!string.IsNullOrWhiteSpace(user.DisplayName))
        {
            claims.Add(new Claim(ClaimTypes.Name, user.DisplayName));
        }

        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(_options.SigningKey));
        var token = new JwtSecurityToken(
            issuer: _options.Issuer,
            audience: _options.Audience,
            claims: claims,
            notBefore: now.UtcDateTime,
            expires: now.AddMinutes(_options.AccessTokenLifetimeMinutes).UtcDateTime,
            signingCredentials: new SigningCredentials(key, SecurityAlgorithms.HmacSha256));
        return new JwtSecurityTokenHandler().WriteToken(token);
    }

    private RefreshToken NewRefreshToken(
        string userId,
        string familyId,
        string value,
        string? ipAddress,
        DateTimeOffset now) =>
        new()
        {
            UserId = userId,
            FamilyId = familyId,
            TokenHash = HashRefreshToken(value),
            CreatedAtUtc = now,
            ExpiresAtUtc = now.AddDays(_options.RefreshTokenLifetimeDays),
            CreatedByIp = ipAddress
        };

    private static string GenerateRefreshToken() =>
        WebEncoders.Base64UrlEncode(RandomNumberGenerator.GetBytes(64));

    private static string HashRefreshToken(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
}
