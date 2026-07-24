using System.Diagnostics;
using Microsoft.AspNetCore.Authentication.Google;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Api.Middleware;

public static class GoogleAuditEventsExtensions
{
    public static void ConfigureAuditEvents(this GoogleOptions options)
    {
        options.Events.OnRemoteFailure = async context =>
        {
            var http = context.HttpContext;
            var auditLogs = http.RequestServices
                .GetRequiredService<IAuditLogService>();
            await auditLogs.WriteAsync(
                new AuditLogEntry(
                    AuditActions.AuthLoginFailed,
                    options.CallbackPath.Value ?? "/signin-google",
                    HttpMethods.Get,
                    StatusCodes.Status401Unauthorized,
                    false,
                    DateTimeOffset.UtcNow,
                    0,
                    IpAddress: http.Connection.RemoteIpAddress?.ToString(),
                    UserAgent: http.Request.Headers.UserAgent.ToString(),
                    TraceId: Activity.Current?.TraceId.ToString()
                        ?? http.TraceIdentifier,
                    FailureCode: "GOOGLE_CALLBACK_FAILED"),
                CancellationToken.None);
        };
    }
}
