using System.Net;
using System.Text;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Options;
using RagMiddleware.Infrastructure.Clients;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class DocumentUploadClientTests
{
    [Fact]
    public async Task Upload_uses_internal_document_route_and_service_headers()
    {
        var handler = new UploadHandler();
        var client = new RagApiClient(
            new HttpClient(handler)
            {
                BaseAddress = new Uri("http://python.internal/")
            },
            Options.Create(new RagApiOptions
            {
                BaseUrl = "http://python.internal",
                ApiKey = "internal-test-key-that-is-at-least-32-characters"
            }),
            new HttpContextAccessor());
        await using var stream = new MemoryStream(
            Encoding.ASCII.GetBytes("%PDF-1.7\nfixture"));

        var result = await client.UploadDocumentAsync(
            stream,
            stream.Length,
            "user-1",
            default);

        Assert.Equal(
            "http://python.internal/api/v1/documents/upload",
            handler.Url);
        Assert.Equal(
            "internal-test-key-that-is-at-least-32-characters",
            handler.ApiKey);
        Assert.Equal("user-1", handler.UserId);
        Assert.Equal("indexed", result.Status);
        Assert.True(handler.IsMultipart);
        Assert.True(handler.HasGeneratedFilename);
    }

    private sealed class UploadHandler : HttpMessageHandler
    {
        public string? Url { get; private set; }
        public string? ApiKey { get; private set; }
        public string? UserId { get; private set; }
        public bool IsMultipart { get; private set; }
        public bool HasGeneratedFilename { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            Url = request.RequestUri?.ToString();
            ApiKey = request.Headers.GetValues("X-RAG-API-Key").Single();
            UserId = request.Headers
                .GetValues("X-Application-User-Id")
                .Single();
            IsMultipart = request.Content is MultipartFormDataContent;
            var body = await request.Content!.ReadAsStringAsync(
                cancellationToken);
            HasGeneratedFilename = body.Contains(
                "filename=upload.pdf",
                StringComparison.Ordinal);
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """
                    {"document_id":"doc-1","chunk_count":2,"status":"indexed"}
                    """,
                    Encoding.UTF8,
                    "application/json")
            };
        }
    }
}
