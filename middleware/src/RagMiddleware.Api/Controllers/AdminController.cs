using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.AspNetCore.Mvc;
using RagMiddleware.Api.Middleware;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Api.Controllers;

[ApiController]
[Authorize(Roles = "Admin")]
[Route("api/admin")]
[EnableRateLimiting("Admin")]
public sealed class AdminController(IAuditLogService auditLogs) : ControllerBase
{
    [HttpGet("audit-logs")]
    public async Task<ActionResult<AuditLogPage>> GetAuditLogs(
        [FromQuery] AuditLogRequest request,
        CancellationToken cancellationToken)
    {
        if (request.FromUtc is not null
            && request.ToUtc is not null
            && request.FromUtc > request.ToUtc)
        {
            return BadRequest(new
            {
                code = "invalid_date_range",
                message = "fromUtc must be earlier than or equal to toUtc."
            });
        }

        HttpContext.Items[AuditLoggingMiddleware.SummaryItem] =
            $"Audit log view; page={request.Page}; pageSize={request.PageSize}; "
            + $"filters={request.FilterCount}";
        return Ok(await auditLogs.QueryAsync(
            new AuditLogQuery(
                request.Page,
                request.PageSize,
                request.UserId,
                request.Action,
                request.FromUtc,
                request.ToUtc,
                request.Succeeded,
                request.StatusCode),
            cancellationToken));
    }
}

public sealed class AuditLogRequest
{
    [Range(1, int.MaxValue)]
    public int Page { get; init; } = 1;

    [Range(1, 100)]
    public int PageSize { get; init; } = 50;

    [MaxLength(64)]
    public string? UserId { get; init; }

    [MaxLength(64)]
    public string? Action { get; init; }

    public DateTimeOffset? FromUtc { get; init; }
    public DateTimeOffset? ToUtc { get; init; }
    public bool? Succeeded { get; init; }

    [Range(100, 599)]
    public int? StatusCode { get; init; }

    public int FilterCount =>
        new object?[] { UserId, Action, FromUtc, ToUtc, Succeeded, StatusCode }
            .Count(value => value is not null);
}
