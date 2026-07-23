using MongoDB.Driver;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Domain.Entities;

namespace RagMiddleware.Infrastructure.Persistence;

public sealed class MongoUserRepository(MongoContext context) : IUserRepository
{
    public Task<ApplicationUser?> FindByIdAsync(string id, CancellationToken cancellationToken) =>
        context.Users.Find(x => x.Id == id).FirstOrDefaultAsync(cancellationToken);

    public Task<ApplicationUser?> FindByGoogleSubjectAsync(
        string subject,
        CancellationToken cancellationToken) =>
        context.Users.Find(x => x.GoogleSubject == subject).FirstOrDefaultAsync(cancellationToken);

    public Task<ApplicationUser?> FindByNormalizedEmailAsync(
        string normalizedEmail,
        CancellationToken cancellationToken) =>
        context.Users.Find(x => x.NormalizedEmail == normalizedEmail).FirstOrDefaultAsync(cancellationToken);

    public async Task<ApplicationUser> CreateAsync(
        ApplicationUser user,
        CancellationToken cancellationToken)
    {
        await context.Users.InsertOneAsync(user, cancellationToken: cancellationToken);
        return user;
    }

    public Task UpdateAsync(ApplicationUser user, CancellationToken cancellationToken) =>
        context.Users.ReplaceOneAsync(x => x.Id == user.Id, user, cancellationToken: cancellationToken);
}

public sealed class MongoRefreshTokenRepository(MongoContext context) : IRefreshTokenRepository
{
    public Task InsertAsync(RefreshToken token, CancellationToken cancellationToken) =>
        context.RefreshTokens.InsertOneAsync(token, cancellationToken: cancellationToken);

    public Task<RefreshToken?> FindByHashAsync(
        string tokenHash,
        CancellationToken cancellationToken) =>
        context.RefreshTokens.Find(x => x.TokenHash == tokenHash)
            .FirstOrDefaultAsync(cancellationToken);

    public async Task<bool> RotateAsync(
        string tokenHash,
        DateTimeOffset revokedAtUtc,
        string replacementHash,
        string? revokedByIp,
        CancellationToken cancellationToken)
    {
        var filter = Builders<RefreshToken>.Filter.And(
            Builders<RefreshToken>.Filter.Eq(x => x.TokenHash, tokenHash),
            Builders<RefreshToken>.Filter.Eq(x => x.RevokedAtUtc, null),
            Builders<RefreshToken>.Filter.Gt(x => x.ExpiresAtUtc, revokedAtUtc));
        var update = Builders<RefreshToken>.Update
            .Set(x => x.RevokedAtUtc, revokedAtUtc)
            .Set(x => x.ReplacedByTokenHash, replacementHash)
            .Set(x => x.RevokedByIp, revokedByIp);
        var result = await context.RefreshTokens.UpdateOneAsync(
            filter,
            update,
            cancellationToken: cancellationToken);
        return result.ModifiedCount == 1;
    }

    public Task RevokeAsync(
        string tokenHash,
        DateTimeOffset revokedAtUtc,
        string? revokedByIp,
        CancellationToken cancellationToken) =>
        context.RefreshTokens.UpdateOneAsync(
            x => x.TokenHash == tokenHash && x.RevokedAtUtc == null,
            Builders<RefreshToken>.Update
                .Set(x => x.RevokedAtUtc, revokedAtUtc)
                .Set(x => x.RevokedByIp, revokedByIp),
            cancellationToken: cancellationToken);

    public Task RevokeFamilyAsync(
        string familyId,
        DateTimeOffset revokedAtUtc,
        string? revokedByIp,
        CancellationToken cancellationToken) =>
        context.RefreshTokens.UpdateManyAsync(
            x => x.FamilyId == familyId && x.RevokedAtUtc == null,
            Builders<RefreshToken>.Update
                .Set(x => x.RevokedAtUtc, revokedAtUtc)
                .Set(x => x.RevokedByIp, revokedByIp),
            cancellationToken: cancellationToken);
}
