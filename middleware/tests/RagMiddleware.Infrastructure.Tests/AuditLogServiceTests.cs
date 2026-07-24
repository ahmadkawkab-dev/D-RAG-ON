using Microsoft.Extensions.Logging.Abstractions;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;
using RagMiddleware.Infrastructure.Auditing;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class AuditLogServiceTests
{
    [Fact]
    public async Task Maps_bounded_sanitized_fields_without_body_or_token_properties()
    {
        var repository = new RecordingAuditRepository();
        var service = new AuditLogService(
            repository,
            NullLogger<AuditLogService>.Instance);

        await service.WriteAsync(new AuditLogEntry(
            AuditActions.RagQuery,
            "/api/rag/document/stream",
            "POST",
            200,
            true,
            DateTimeOffset.Now,
            -10,
            RequestSummary: "Query submitted;\r\nlength=42",
            UserAgent: new string('a', 400),
            TraceId: "trace"));

        var saved = Assert.Single(repository.Items);
        Assert.Equal(0, saved.DurationMs);
        Assert.Equal(TimeSpan.Zero, saved.TimestampUtc.Offset);
        Assert.DoesNotContain('\r', saved.RequestSummary!);
        Assert.DoesNotContain('\n', saved.RequestSummary!);
        Assert.Equal(256, saved.UserAgent!.Length);
        var propertyNames = typeof(AuditLog)
            .GetProperties()
            .Select(property => property.Name)
            .ToArray();
        Assert.DoesNotContain("Authorization", propertyNames);
        Assert.DoesNotContain("Cookie", propertyNames);
        Assert.DoesNotContain("RequestBody", propertyNames);
        Assert.DoesNotContain("ResponseBody", propertyNames);
        Assert.DoesNotContain("AccessToken", propertyNames);
        Assert.DoesNotContain("RefreshToken", propertyNames);
    }

    [Fact]
    public async Task Persistence_failure_is_best_effort_and_not_returned_to_caller()
    {
        var service = new AuditLogService(
            new ThrowingAuditRepository(),
            NullLogger<AuditLogService>.Instance);

        await service.WriteAsync(new AuditLogEntry(
            AuditActions.AuthLoginFailed,
            "/api/auth/google/complete",
            "GET",
            401,
            false,
            DateTimeOffset.UtcNow,
            1,
            FailureCode: "GOOGLE_CALLBACK_FAILED"));
    }

    [Fact]
    public async Task Query_bounds_page_size_and_projects_safe_dto()
    {
        var repository = new RecordingAuditRepository();
        repository.Items.Add(new AuditLog
        {
            Action = AuditActions.RagQuery,
            Endpoint = "/api/rag/general/stream",
            HttpMethod = "POST",
            StatusCode = 200,
            TimestampUtc = DateTimeOffset.UtcNow,
            Succeeded = true
        });
        var service = new AuditLogService(
            repository,
            NullLogger<AuditLogService>.Instance);

        var page = await service.QueryAsync(new AuditLogQuery(
            Page: 0,
            PageSize: 1000));

        Assert.Equal(1, page.Page);
        Assert.Equal(100, page.PageSize);
        Assert.Single(page.Items);
        Assert.Equal(1, page.TotalCount);
    }

    private sealed class RecordingAuditRepository : IAuditLogRepository
    {
        public List<AuditLog> Items { get; } = [];

        public Task InsertAsync(
            AuditLog auditLog,
            CancellationToken cancellationToken)
        {
            Items.Add(auditLog);
            return Task.CompletedTask;
        }

        public Task<(IReadOnlyList<AuditLog> Items, long TotalCount)> QueryAsync(
            AuditLogQuery query,
            int page,
            int pageSize,
            CancellationToken cancellationToken) =>
            Task.FromResult((
                (IReadOnlyList<AuditLog>)Items.ToArray(),
                (long)Items.Count));
    }

    private sealed class ThrowingAuditRepository : IAuditLogRepository
    {
        public Task InsertAsync(
            AuditLog auditLog,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("database unavailable");

        public Task<(IReadOnlyList<AuditLog> Items, long TotalCount)> QueryAsync(
            AuditLogQuery query,
            int page,
            int pageSize,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("database unavailable");
    }
}
