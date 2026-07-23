using System.Net;
using System.Text;
using Microsoft.Extensions.Options;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Infrastructure.Clients;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class RagApiClientTests
{
    private const string ApiKey = "internal-test-key-that-is-at-least-32-characters";

    [Fact]
    public async Task Uses_configured_base_url_and_attaches_internal_headers()
    {
        var handler = new RecordingHandler(_ => Json(HttpStatusCode.OK, "[]"));
        var client = CreateClient(handler);

        var sessions = await client.ListSessionsAsync("document", "user-123", default);

        Assert.Empty(sessions);
        Assert.Equal("http://python.internal/api/v1/history/sessions?mode=document", handler.Url);
        Assert.Equal(ApiKey, handler.ApiKey);
        Assert.Equal("user-123", handler.UserId);
        Assert.Null(handler.Authorization);
    }

    [Fact]
    public async Task Preserves_general_and_document_stream_routing()
    {
        var handler = new RecordingHandler(_ =>
            new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("event: done\ndata: {}\n\n")
            });
        var client = CreateClient(handler);

        await using (await client.StreamChatAsync(
            "general",
            new RagChatRequest("hello", null, null),
            "user-1",
            default))
        {
            Assert.EndsWith("/api/v1/general/stream", handler.Url);
        }
        await using (await client.StreamChatAsync(
            "document",
            new RagChatRequest("hello", null, null),
            "user-1",
            default))
        {
            Assert.EndsWith("/api/v1/chat/stream", handler.Url);
        }
    }

    [Theory]
    [InlineData(HttpStatusCode.BadRequest, 400)]
    [InlineData(HttpStatusCode.InternalServerError, 500)]
    public async Task Maps_python_failures_without_returning_raw_payload(
        HttpStatusCode status,
        int expectedStatus)
    {
        var handler = new RecordingHandler(_ =>
            Json(status, "{\"detail\":\"internal stack and secret\"}"));
        var client = CreateClient(handler);

        var exception = await Assert.ThrowsAsync<RagServiceException>(
            () => client.ListSessionsAsync(null, "user-1", default));

        Assert.Equal(expectedStatus, exception.StatusCode);
        Assert.DoesNotContain("internal stack", exception.Message);
    }

    [Fact]
    public async Task Propagates_caller_cancellation()
    {
        var handler = new RecordingHandler(async (_, cancellationToken) =>
        {
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            return Json(HttpStatusCode.OK, "[]");
        });
        var client = CreateClient(handler);
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(
            () => client.ListSessionsAsync(null, "user-1", cancellation.Token));
    }

    private static RagApiClient CreateClient(HttpMessageHandler handler) =>
        new(
            new HttpClient(handler) { BaseAddress = new Uri("http://python.internal/") },
            Options.Create(new RagApiOptions
            {
                BaseUrl = "http://python.internal",
                ApiKey = ApiKey
            }));

    private static HttpResponseMessage Json(HttpStatusCode status, string body) =>
        new(status)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json")
        };

    private sealed class RecordingHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> _response;

        public RecordingHandler(Func<HttpRequestMessage, HttpResponseMessage> response)
            : this((request, _) => Task.FromResult(response(request)))
        {
        }

        public RecordingHandler(
            Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> response) =>
            _response = response;

        public string? Url { get; private set; }
        public string? ApiKey { get; private set; }
        public string? UserId { get; private set; }
        public string? Authorization { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Url = request.RequestUri?.ToString();
            ApiKey = request.Headers.GetValues("X-RAG-API-Key").Single();
            UserId = request.Headers.GetValues("X-Application-User-Id").Single();
            Authorization = request.Headers.Authorization?.ToString();
            return _response(request, cancellationToken);
        }
    }
}
