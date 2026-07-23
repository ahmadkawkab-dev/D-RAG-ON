using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;

namespace RagMiddleware.Application.Abstractions;

public interface IUserRepository
{
    Task<ApplicationUser?> FindByIdAsync(string id, CancellationToken cancellationToken);
    Task<ApplicationUser?> FindByGoogleSubjectAsync(string subject, CancellationToken cancellationToken);
    Task<ApplicationUser?> FindByNormalizedEmailAsync(string normalizedEmail, CancellationToken cancellationToken);
    Task<ApplicationUser> CreateAsync(ApplicationUser user, CancellationToken cancellationToken);
    Task UpdateAsync(ApplicationUser user, CancellationToken cancellationToken);
}

public interface IRefreshTokenRepository
{
    Task InsertAsync(RefreshToken token, CancellationToken cancellationToken);
    Task<RefreshToken?> FindByHashAsync(string tokenHash, CancellationToken cancellationToken);
    Task<bool> RotateAsync(
        string tokenHash,
        DateTimeOffset revokedAtUtc,
        string replacementHash,
        string? revokedByIp,
        CancellationToken cancellationToken);
    Task RevokeAsync(
        string tokenHash,
        DateTimeOffset revokedAtUtc,
        string? revokedByIp,
        CancellationToken cancellationToken);
    Task RevokeFamilyAsync(
        string familyId,
        DateTimeOffset revokedAtUtc,
        string? revokedByIp,
        CancellationToken cancellationToken);
}

public interface ITokenService
{
    Task<TokenPair> IssueTokensAsync(
        ApplicationUser user,
        string? ipAddress,
        CancellationToken cancellationToken = default);

    Task<TokenPair?> RotateRefreshTokenAsync(
        string refreshToken,
        string? ipAddress,
        CancellationToken cancellationToken = default);

    Task RevokeRefreshTokenAsync(
        string refreshToken,
        string? ipAddress,
        CancellationToken cancellationToken = default);
}
