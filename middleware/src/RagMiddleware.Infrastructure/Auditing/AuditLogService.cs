using Microsoft.Extensions.Logging;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;

namespace RagMiddleware.Infrastructure.Auditing;

public sealed class AuditLogService(
    IAuditLogRepository repository,
    ILogger<AuditLogService> logger) : IAuditLogService
{
    private const int ActionLength = 64;
    private const int EndpointLength = 256;
    private const int MethodLength = 16;
    private const int SummaryLength = 512;
    private const int IpLength = 64;
    private const int UserAgentLength = 256;
    private const int TraceLength = 128;
    private const int FailureLength = 64;

    public async Task WriteAsync(
        AuditLogEntry entry,
        CancellationToken cancellationToken = default)
    {
        try
        {
            await repository.InsertAsync(Map(entry), cancellationToken);
        }
        catch (Exception exception)
        {
            logger.LogError(
                exception,
                "Audit persistence failed for action {AuditAction} and trace {TraceId}",
                Clean(entry.Action, ActionLength),
                Clean(entry.TraceId, TraceLength));
        }
    }

    public async Task<AuditLogPage> QueryAsync(
        AuditLogQuery query,
        CancellationToken cancellationToken = default)
    {
        var page = Math.Max(1, query.Page);
        var pageSize = Math.Clamp(query.PageSize, 1, 100);
        var (rows, total) = await repository.QueryAsync(
            query,
            page,
            pageSize,
            cancellationToken);
        return new AuditLogPage(
            rows.Select(ToItem).ToArray(),
            page,
            pageSize,
            total);
    }

    internal static AuditLog Map(AuditLogEntry entry) =>
        new()
        {
            UserId = Clean(entry.UserId, 64),
            Action = Clean(entry.Action, ActionLength) ?? "UNKNOWN",
            Endpoint = Clean(entry.Endpoint, EndpointLength) ?? "/",
            HttpMethod = Clean(entry.HttpMethod, MethodLength) ?? "UNKNOWN",
            RequestSummary = Clean(entry.RequestSummary, SummaryLength),
            StatusCode = entry.StatusCode,
            IpAddress = Clean(entry.IpAddress, IpLength),
            UserAgent = Clean(entry.UserAgent, UserAgentLength),
            TraceId = Clean(entry.TraceId, TraceLength),
            TimestampUtc = entry.TimestampUtc.ToUniversalTime(),
            DurationMs = Math.Max(0, entry.DurationMs),
            Succeeded = entry.Succeeded,
            FailureCode = Clean(entry.FailureCode, FailureLength)
        };

    private static AuditLogItem ToItem(AuditLog row) =>
        new(
            row.Id,
            row.UserId,
            row.Action,
            row.Endpoint,
            row.HttpMethod,
            row.RequestSummary,
            row.StatusCode,
            row.IpAddress,
            row.TraceId,
            row.TimestampUtc,
            row.DurationMs,
            row.Succeeded,
            row.FailureCode);

    internal static string? Clean(string? value, int maximumLength)
    {
        if (string.IsNullOrWhiteSpace(value))
            return null;
        var sanitized = new string(value
            .Where(character => !char.IsControl(character))
            .ToArray())
            .Trim();
        return sanitized.Length <= maximumLength
            ? sanitized
            : sanitized[..maximumLength];
    }
}
