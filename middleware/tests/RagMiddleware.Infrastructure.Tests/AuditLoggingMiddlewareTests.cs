using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using RagMiddleware.Api.Middleware;
using Microsoft.AspNetCore.Routing.Patterns;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class AuditLoggingMiddlewareTests
{
    [Fact]
    public async Task Successful_stream_writes_one_sanitized_audit_record()
    {
        var audit = new RecordingAuditService();
        var context = Context(
            "/api/rag/general/stream",
            "api/rag/general/stream",
            StatusCodes.Status200OK,
            "user-1");
        context.Request.Headers.Authorization = "Bearer secret-jwt";
        context.Request.Headers.Cookie = "refresh=secret-cookie";
        context.Items[AuditLoggingMiddleware.SummaryItem] =
            "Query submitted; mode=general; length=25";
        var middleware = new AuditLoggingMiddleware(_ => Task.CompletedTask);

        await middleware.InvokeAsync(context, audit);

        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.RagQuery, entry.Action);
        Assert.Equal("user-1", entry.UserId);
        Assert.True(entry.Succeeded);
        Assert.True(entry.DurationMs >= 0);
        Assert.NotNull(entry.TraceId);
        var serializedFields = string.Join(
            "|",
            entry.Action,
            entry.Endpoint,
            entry.RequestSummary,
            entry.FailureCode);
        Assert.DoesNotContain("secret-jwt", serializedFields);
        Assert.DoesNotContain("secret-cookie", serializedFields);
    }

    [Theory]
    [InlineData(401, "AUTH_UNAUTHORIZED", "MISSING_ACCESS_TOKEN")]
    [InlineData(403, "AUTH_FORBIDDEN", "INSUFFICIENT_PERMISSION")]
    public async Task Authorization_failure_is_audited_once_with_null_user(
        int statusCode,
        string action,
        string failureCode)
    {
        var audit = new RecordingAuditService();
        var context = Context(
            "/api/rag/document/stream",
            "api/rag/document/stream",
            statusCode);
        var middleware = new AuditLoggingMiddleware(_ => Task.CompletedTask);

        await middleware.InvokeAsync(context, audit);

        var entry = Assert.Single(audit.Entries);
        Assert.Equal(action, entry.Action);
        Assert.Equal(failureCode, entry.FailureCode);
        Assert.Null(entry.UserId);
        Assert.False(entry.Succeeded);
    }

    [Fact]
    public async Task Unhandled_exception_is_rethrown_after_audit_attempt()
    {
        var audit = new RecordingAuditService();
        var context = Context(
            "/api/rag/history/sessions",
            "api/rag/history/sessions",
            StatusCodes.Status200OK,
            "user-1");
        var middleware = new AuditLoggingMiddleware(
            _ => throw new InvalidOperationException("sensitive stack detail"));

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => middleware.InvokeAsync(context, audit));

        var entry = Assert.Single(audit.Entries);
        Assert.Equal(StatusCodes.Status500InternalServerError, entry.StatusCode);
        Assert.Equal("UNHANDLED_EXCEPTION", entry.FailureCode);
        Assert.DoesNotContain(
            "sensitive stack detail",
            entry.RequestSummary ?? string.Empty);
    }

    [Fact]
    public async Task Admin_access_is_audited_without_filter_values()
    {
        var audit = new RecordingAuditService();
        var context = Context(
            "/api/admin/audit-logs",
            "api/admin/audit-logs",
            StatusCodes.Status403Forbidden,
            "user-1");
        context.Request.QueryString =
            new QueryString("?userId=sensitive-user-id&action=RAG_QUERY");
        var middleware = new AuditLoggingMiddleware(_ => Task.CompletedTask);

        await middleware.InvokeAsync(context, audit);

        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.AdminAuditLogView, entry.Action);
        Assert.Equal("INSUFFICIENT_PERMISSION", entry.FailureCode);
        Assert.DoesNotContain(
            "sensitive-user-id",
            entry.RequestSummary ?? string.Empty);
    }

    private static DefaultHttpContext Context(
        string path,
        string routePattern,
        int statusCode,
        string? userId = null)
    {
        var context = new DefaultHttpContext();
        context.Request.Path = path;
        context.Request.Method = HttpMethods.Post;
        context.Response.StatusCode = statusCode;
        context.SetEndpoint(new RouteEndpoint(
            _ => Task.CompletedTask,
            RoutePatternFactory.Parse(routePattern),
            0,
            EndpointMetadataCollection.Empty,
            routePattern));
        if (userId is not null)
        {
            context.User = new ClaimsPrincipal(
                new ClaimsIdentity(
                    [new Claim("sub", userId)],
                    "test"));
        }
        return context;
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
}
