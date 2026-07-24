using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using RagMiddleware.Api.Middleware;
using RagMiddleware.Api.Controllers;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class AdminControllerTests
{
    [Fact]
    public void Audit_endpoint_requires_persisted_admin_role()
    {
        var authorize = Assert.Single(
            typeof(AdminController)
                .GetCustomAttributes(typeof(AuthorizeAttribute), true)
                .Cast<AuthorizeAttribute>());

        Assert.Equal("Admin", authorize.Roles);
    }

    [Fact]
    public async Task Admin_query_forwards_filters_and_sets_sanitized_summary()
    {
        var audit = new RecordingAuditService();
        var controller = new AdminController(audit)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = new DefaultHttpContext()
            }
        };
        var request = new AuditLogRequest
        {
            Page = 2,
            PageSize = 25,
            Action = AuditActions.RagQuery,
            Succeeded = true
        };

        var result = await controller.GetAuditLogs(request, default);

        Assert.IsType<OkObjectResult>(result.Result);
        Assert.Equal(2, audit.Query!.Page);
        Assert.Equal(25, audit.Query.PageSize);
        Assert.Equal(AuditActions.RagQuery, audit.Query.Action);
        var summary = controller.HttpContext.Items[
            AuditLoggingMiddleware.SummaryItem] as string;
        Assert.Contains("filters=2", summary);
        Assert.DoesNotContain(AuditActions.RagQuery, summary);
    }

    [Fact]
    public void Page_size_is_bounded_by_model_validation()
    {
        var request = new AuditLogRequest { PageSize = 101 };
        var results = new List<ValidationResult>();

        var valid = Validator.TryValidateObject(
            request,
            new ValidationContext(request),
            results,
            true);

        Assert.False(valid);
        Assert.Contains(results, result =>
            result.MemberNames.Contains(nameof(AuditLogRequest.PageSize)));
    }

    [Fact]
    public async Task Reversed_date_range_returns_safe_bad_request()
    {
        var controller = new AdminController(new RecordingAuditService())
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = new DefaultHttpContext()
            }
        };

        var result = await controller.GetAuditLogs(
            new AuditLogRequest
            {
                FromUtc = DateTimeOffset.UtcNow,
                ToUtc = DateTimeOffset.UtcNow.AddDays(-1)
            },
            default);

        Assert.IsType<BadRequestObjectResult>(result.Result);
    }

    private sealed class RecordingAuditService : IAuditLogService
    {
        public AuditLogQuery? Query { get; private set; }

        public Task WriteAsync(
            AuditLogEntry entry,
            CancellationToken cancellationToken = default) =>
            Task.CompletedTask;

        public Task<AuditLogPage> QueryAsync(
            AuditLogQuery query,
            CancellationToken cancellationToken = default)
        {
            Query = query;
            return Task.FromResult(new AuditLogPage(
                [],
                query.Page,
                query.PageSize,
                0));
        }
    }
}
