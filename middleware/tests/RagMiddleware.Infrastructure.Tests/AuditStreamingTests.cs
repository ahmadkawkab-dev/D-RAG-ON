using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using Microsoft.AspNetCore.Routing.Patterns;
using RagMiddleware.Api.Middleware;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class AuditStreamingTests
{
    [Fact]
    public async Task Timeout_is_recorded_without_buffering_stream_content()
    {
        var audit = new RecordingAuditService();
        var context = Context(StatusCodes.Status504GatewayTimeout);
        context.Items[AuditLoggingMiddleware.FailureCodeItem] =
            "RAG_STREAM_TIMEOUT";
        var middleware = new AuditLoggingMiddleware(_ => Task.CompletedTask);

        await middleware.InvokeAsync(context, audit);

        var entry = Assert.Single(audit.Entries);
        Assert.Equal(AuditActions.RagQueryFailed, entry.Action);
        Assert.Equal("RAG_STREAM_TIMEOUT", entry.FailureCode);
        Assert.Null(entry.RequestSummary);
    }

    [Fact]
    public async Task Client_cancellation_attempts_audit_and_rethrows()
    {
        var audit = new RecordingAuditService();
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        var context = Context(StatusCodes.Status200OK);
        context.RequestAborted = cancellation.Token;
        var middleware = new AuditLoggingMiddleware(
            _ => throw new OperationCanceledException(cancellation.Token));

        await Assert.ThrowsAsync<OperationCanceledException>(
            () => middleware.InvokeAsync(context, audit));

        var entry = Assert.Single(audit.Entries);
        Assert.Equal("CLIENT_DISCONNECTED", entry.FailureCode);
        Assert.Equal(StatusCodes.Status499ClientClosedRequest, entry.StatusCode);
    }

    private static DefaultHttpContext Context(int statusCode)
    {
        var context = new DefaultHttpContext();
        context.Request.Path = "/api/rag/document/stream";
        context.Request.Method = HttpMethods.Post;
        context.Response.StatusCode = statusCode;
        context.SetEndpoint(new RouteEndpoint(
            _ => Task.CompletedTask,
            RoutePatternFactory.Parse("api/rag/document/stream"),
            0,
            EndpointMetadataCollection.Empty,
            "document stream"));
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
