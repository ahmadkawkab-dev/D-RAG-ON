using System.Text.Json;
using Microsoft.Extensions.Options;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Api.Middleware;

public sealed class RagConcurrencyMiddleware
{
    private readonly RequestDelegate _next;
    private readonly SemaphoreSlim _slots;

    public RagConcurrencyMiddleware(
        RequestDelegate next,
        IOptions<RateLimitOptions> options)
    {
        _next = next;
        _slots = new SemaphoreSlim(options.Value.RagConcurrencyLimit);
    }

    public async Task InvokeAsync(HttpContext context)
    {
        if (!context.Request.Path.StartsWithSegments(
                "/api/rag",
                StringComparison.OrdinalIgnoreCase))
        {
            await _next(context);
            return;
        }

        if (!await _slots.WaitAsync(0, context.RequestAborted))
        {
            context.Response.StatusCode = StatusCodes.Status429TooManyRequests;
            context.Response.ContentType = "application/problem+json";
            context.Response.Headers.RetryAfter = "1";
            await JsonSerializer.SerializeAsync(
                context.Response.Body,
                new
                {
                    type = "about:blank",
                    title = "Too many concurrent RAG requests.",
                    status = StatusCodes.Status429TooManyRequests,
                    code = "rag_concurrency_limited",
                    trace_id = context.TraceIdentifier
                },
                cancellationToken: context.RequestAborted);
            return;
        }

        try
        {
            await _next(context);
        }
        finally
        {
            _slots.Release();
        }
    }
}
