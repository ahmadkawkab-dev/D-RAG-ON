using Microsoft.Extensions.Hosting;
using MongoDB.Driver;
using RagMiddleware.Domain.Entities;

namespace RagMiddleware.Infrastructure.Persistence;

public sealed class MongoIndexInitializer(MongoContext context) : IHostedService
{
    public async Task StartAsync(CancellationToken cancellationToken)
    {
        var userIndexes = new[]
        {
            new CreateIndexModel<ApplicationUser>(
                Builders<ApplicationUser>.IndexKeys.Ascending(x => x.GoogleSubject),
                new CreateIndexOptions { Unique = true, Name = "application_users_google_subject_unique" }),
            new CreateIndexModel<ApplicationUser>(
                Builders<ApplicationUser>.IndexKeys.Ascending(x => x.NormalizedEmail),
                new CreateIndexOptions { Unique = true, Name = "application_users_email_unique" })
        };
        await context.Users.Indexes.CreateManyAsync(userIndexes, cancellationToken);

        var tokenIndexes = new[]
        {
            new CreateIndexModel<RefreshToken>(
                Builders<RefreshToken>.IndexKeys.Ascending(x => x.TokenHash),
                new CreateIndexOptions { Unique = true, Name = "refresh_tokens_hash_unique" }),
            new CreateIndexModel<RefreshToken>(
                Builders<RefreshToken>.IndexKeys
                    .Ascending(x => x.UserId)
                    .Ascending(x => x.FamilyId),
                new CreateIndexOptions { Name = "refresh_tokens_user_family" }),
            new CreateIndexModel<RefreshToken>(
                Builders<RefreshToken>.IndexKeys.Ascending(x => x.ExpiresAtUtc),
                new CreateIndexOptions { ExpireAfter = TimeSpan.Zero, Name = "refresh_tokens_expiry" })
        };
        await context.RefreshTokens.Indexes.CreateManyAsync(tokenIndexes, cancellationToken);

        var auditIndexes = new[]
        {
            new CreateIndexModel<AuditLog>(
                Builders<AuditLog>.IndexKeys.Descending(x => x.TimestampUtc),
                new CreateIndexOptions { Name = "audit_logs_timestamp_desc" }),
            new CreateIndexModel<AuditLog>(
                Builders<AuditLog>.IndexKeys
                    .Ascending(x => x.UserId)
                    .Descending(x => x.TimestampUtc),
                new CreateIndexOptions { Name = "audit_logs_user_timestamp" }),
            new CreateIndexModel<AuditLog>(
                Builders<AuditLog>.IndexKeys
                    .Ascending(x => x.Action)
                    .Descending(x => x.TimestampUtc),
                new CreateIndexOptions { Name = "audit_logs_action_timestamp" }),
            new CreateIndexModel<AuditLog>(
                Builders<AuditLog>.IndexKeys
                    .Ascending(x => x.StatusCode)
                    .Descending(x => x.TimestampUtc),
                new CreateIndexOptions { Name = "audit_logs_status_timestamp" }),
            new CreateIndexModel<AuditLog>(
                Builders<AuditLog>.IndexKeys
                    .Ascending(x => x.Succeeded)
                    .Descending(x => x.TimestampUtc),
                new CreateIndexOptions { Name = "audit_logs_success_timestamp" })
        };
        await context.AuditLogs.Indexes.CreateManyAsync(auditIndexes, cancellationToken);
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
