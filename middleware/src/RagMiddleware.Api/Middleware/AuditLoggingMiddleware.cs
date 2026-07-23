using System.Diagnostics;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Routing;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Api.Middleware;

public sealed class AuditLoggingMiddleware(RequestDelegate next)
{
    public const string SummaryItem = "Audit.RequestSummary";
    public const string FailureCodeItem = "Audit.FailureCode";

    public async Task InvokeAsync(
        HttpContext context,
        IAuditLogService auditLogs)
    {
        if (!ShouldAudit(context.Request.Path))
        {
            await next(context);
            return;
        }

        var startedUtc = DateTimeOffset.UtcNow;
        var stopwatch = Stopwatch.StartNew();
        Exception? failure = null;
        try
        {
            await next(context);
        }
        catch (Exception exception)
        {
            failure = exception;
            throw;
        }
        finally
        {
            stopwatch.Stop();
            var statusCode = failure is OperationCanceledException
                && context.RequestAborted.IsCancellationRequested
                ? StatusCodes.Status499ClientClosedRequest
                : failure is null
                    ? context.Response.StatusCode
                    : StatusCodes.Status500InternalServerError;
            var action = ResolveAction(context, statusCode);
            var failureCode = ResolveFailureCode(context, statusCode, failure);
            await auditLogs.WriteAsync(
                new AuditLogEntry(
                    action,
                    NormalizedEndpoint(context),
                    context.Request.Method,
                    statusCode,
                    failure is null && statusCode is >= 200 and < 400,
                    startedUtc,
                    stopwatch.ElapsedMilliseconds,
                    UserId(context.User),
                    context.Items[SummaryItem] as string,
                    context.Connection.RemoteIpAddress?.ToString(),
                    SanitizeUserAgent(context.Request.Headers.UserAgent.ToString()),
                    Activity.Current?.TraceId.ToString() ?? context.TraceIdentifier,
                    failureCode),
                CancellationToken.None);
        }
    }

    private static bool ShouldAudit(PathString path) =>
        path.StartsWithSegments("/api/rag", StringComparison.OrdinalIgnoreCase)
        || path.StartsWithSegments("/api/admin/audit-logs", StringComparison.OrdinalIgnoreCase)
        || path.Equals("/api/auth/me", StringComparison.OrdinalIgnoreCase);

    private static string ResolveAction(HttpContext context, int statusCode)
    {
        var path = context.Request.Path;
        if (path.StartsWithSegments("/api/admin/audit-logs", StringComparison.OrdinalIgnoreCase))
            return AuditActions.AdminAuditLogView;
        if (path.Equals("/api/auth/me", StringComparison.OrdinalIgnoreCase))
            return statusCode switch
            {
                StatusCodes.Status401Unauthorized => AuditActions.AuthUnauthorized,
                StatusCodes.Status403Forbidden => AuditActions.AuthForbidden,
                _ => AuditActions.AuthProfileView
            };
        if (statusCode == StatusCodes.Status401Unauthorized)
            return AuditActions.AuthUnauthorized;
        if (statusCode == StatusCodes.Status403Forbidden)
            return AuditActions.AuthForbidden;

        var route = NormalizedEndpoint(context);
        var failed = statusCode >= 400;
        if (route.EndsWith("/general/stream", StringComparison.OrdinalIgnoreCase)
            || route.EndsWith("/document/stream", StringComparison.OrdinalIgnoreCase))
            return failed ? AuditActions.RagQueryFailed : AuditActions.RagQuery;
        if (route.EndsWith("/documents/upload", StringComparison.OrdinalIgnoreCase))
            return failed ? AuditActions.RagRequestFailed : AuditActions.RagDocumentUpload;
        if (context.Request.Method == HttpMethods.Delete)
            return failed ? AuditActions.RagRequestFailed : AuditActions.RagHistoryDelete;
        if (route.Contains("/feedback/", StringComparison.OrdinalIgnoreCase))
            return failed ? AuditActions.RagRequestFailed : AuditActions.RagFeedbackSave;
        if (route.Contains("{sessionId}", StringComparison.OrdinalIgnoreCase))
            return failed ? AuditActions.RagRequestFailed : AuditActions.RagHistoryGet;
        if (route.EndsWith("/history/sessions", StringComparison.OrdinalIgnoreCase))
            return failed ? AuditActions.RagRequestFailed : AuditActions.RagHistoryList;
        return AuditActions.RagRequestFailed;
    }

    private static string? ResolveFailureCode(
        HttpContext context,
        int statusCode,
        Exception? exception)
    {
        if (context.Items[FailureCodeItem] is string specified)
            return specified;
        if (exception is OperationCanceledException && context.RequestAborted.IsCancellationRequested)
            return "CLIENT_DISCONNECTED";
        if (exception is not null)
            return "UNHANDLED_EXCEPTION";
        if (statusCode == StatusCodes.Status401Unauthorized)
            return context.Request.Headers.Authorization.Count == 0
                ? "MISSING_ACCESS_TOKEN"
                : "INVALID_ACCESS_TOKEN";
        if (statusCode == StatusCodes.Status403Forbidden)
            return "INSUFFICIENT_PERMISSION";
        if (statusCode == StatusCodes.Status504GatewayTimeout)
            return "RAG_STREAM_TIMEOUT";
        if (statusCode >= 500)
            return "RAG_SERVICE_FAILURE";
        if (statusCode >= 400)
            return "REQUEST_REJECTED";
        return null;
    }

    private static string NormalizedEndpoint(HttpContext context)
    {
        var pattern = (context.GetEndpoint() as RouteEndpoint)?.RoutePattern.RawText;
        if (!string.IsNullOrWhiteSpace(pattern))
            return "/" + pattern.TrimStart('/');
        if (context.Request.Path.StartsWithSegments(
                "/api/admin/audit-logs",
                StringComparison.OrdinalIgnoreCase))
            return "/api/admin/audit-logs";
        if (context.Request.Path.StartsWithSegments(
                "/api/rag",
                StringComparison.OrdinalIgnoreCase))
            return "/api/rag";
        return context.Request.Path.Value ?? "/";
    }

    private static string? UserId(ClaimsPrincipal principal) =>
        principal.FindFirstValue(JwtRegisteredClaimNames.Sub);

    private static string? SanitizeUserAgent(string userAgent)
    {
        if (string.IsNullOrWhiteSpace(userAgent))
            return null;
        var clean = new string(userAgent
            .Where(character => !char.IsControl(character))
            .ToArray());
        return clean.Length <= 256 ? clean : clean[..256];
    }
}
