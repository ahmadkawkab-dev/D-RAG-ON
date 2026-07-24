using MongoDB.Driver;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;

namespace RagMiddleware.Infrastructure.Persistence;

public sealed class MongoAuditLogRepository(
    MongoContext context) : IAuditLogRepository
{
    public Task InsertAsync(
        AuditLog auditLog,
        CancellationToken cancellationToken) =>
        context.AuditLogs.InsertOneAsync(
            auditLog,
            cancellationToken: cancellationToken);

    public async Task<(IReadOnlyList<AuditLog> Items, long TotalCount)> QueryAsync(
        AuditLogQuery query,
        int page,
        int pageSize,
        CancellationToken cancellationToken)
    {
        var filter = BuildFilter(query);
        var total = await context.AuditLogs.CountDocumentsAsync(
            filter,
            cancellationToken: cancellationToken);
        var items = await context.AuditLogs
            .Find(filter)
            .SortByDescending(x => x.TimestampUtc)
            .ThenByDescending(x => x.Id)
            .Skip((page - 1) * pageSize)
            .Limit(pageSize)
            .ToListAsync(cancellationToken);
        return (items, total);
    }

    private static FilterDefinition<AuditLog> BuildFilter(AuditLogQuery query)
    {
        var filters = new List<FilterDefinition<AuditLog>>();
        var builder = Builders<AuditLog>.Filter;
        if (!string.IsNullOrWhiteSpace(query.UserId))
            filters.Add(builder.Eq(x => x.UserId, query.UserId.Trim()));
        if (!string.IsNullOrWhiteSpace(query.Action))
            filters.Add(builder.Eq(x => x.Action, query.Action.Trim()));
        if (query.FromUtc is not null)
        {
            filters.Add(builder.Gte(
                x => x.TimestampUtc,
                query.FromUtc.Value.ToUniversalTime()));
        }
        if (query.ToUtc is not null)
        {
            filters.Add(builder.Lte(
                x => x.TimestampUtc,
                query.ToUtc.Value.ToUniversalTime()));
        }
        if (query.Succeeded is not null)
            filters.Add(builder.Eq(x => x.Succeeded, query.Succeeded.Value));
        if (query.StatusCode is not null)
            filters.Add(builder.Eq(x => x.StatusCode, query.StatusCode.Value));
        return filters.Count == 0 ? builder.Empty : builder.And(filters);
    }
}
