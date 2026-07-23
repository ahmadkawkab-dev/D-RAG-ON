using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;

namespace RagMiddleware.Application.Abstractions;

public interface IAuditLogService
{
    Task WriteAsync(
        AuditLogEntry entry,
        CancellationToken cancellationToken = default);

    Task<AuditLogPage> QueryAsync(
        AuditLogQuery query,
        CancellationToken cancellationToken = default);
}

public interface IAuditLogRepository
{
    Task InsertAsync(
        AuditLog auditLog,
        CancellationToken cancellationToken);

    Task<(IReadOnlyList<AuditLog> Items, long TotalCount)> QueryAsync(
        AuditLogQuery query,
        int page,
        int pageSize,
        CancellationToken cancellationToken);
}
