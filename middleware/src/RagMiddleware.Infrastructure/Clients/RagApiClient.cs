using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.Options;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Clients;

public sealed class RagApiClient(
    HttpClient httpClient,
    IOptions<RagApiOptions> options) : IRagApiClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true
    };

    private readonly RagApiOptions _options = options.Value;

    public async Task<RagStreamResponse> StreamChatAsync(
        string mode,
        RagChatRequest request,
        string userId,
        CancellationToken cancellationToken)
    {
        var path = mode == "general"
            ? "api/v1/general/stream"
            : "api/v1/chat/stream";
        using var message = CreateRequest(HttpMethod.Post, path, userId);
        message.Headers.Accept.ParseAdd("text/event-stream");
        message.Content = JsonContent.Create(request, options: JsonOptions);
        try
        {
            var response = await httpClient.SendAsync(
                message,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                var statusCode = (int)response.StatusCode;
                response.Dispose();
                throw new RagServiceException(statusCode);
            }

            var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
            return new RagStreamResponse(response, stream);
        }
        catch (OperationCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new RagServiceException((int)HttpStatusCode.GatewayTimeout, true, exception);
        }
        catch (HttpRequestException exception)
        {
            throw new RagServiceException((int)HttpStatusCode.ServiceUnavailable, false, exception);
        }
    }

    public Task<IReadOnlyList<ChatSessionResponse>> ListSessionsAsync(
        string? mode,
        string userId,
        CancellationToken cancellationToken)
    {
        var path = "api/v1/history/sessions";
        if (!string.IsNullOrWhiteSpace(mode))
        {
            path += $"?mode={Uri.EscapeDataString(mode)}";
        }
        return SendAsync<IReadOnlyList<ChatSessionResponse>>(
            HttpMethod.Get,
            path,
            userId,
            null,
            cancellationToken);
    }

    public Task<ChatSessionDetail> GetSessionAsync(
        string sessionId,
        string userId,
        CancellationToken cancellationToken) =>
        SendAsync<ChatSessionDetail>(
            HttpMethod.Get,
            $"api/v1/history/sessions/{Uri.EscapeDataString(sessionId)}",
            userId,
            null,
            cancellationToken);

    public Task<DeleteSessionResponse> DeleteSessionAsync(
        string sessionId,
        string userId,
        CancellationToken cancellationToken) =>
        SendAsync<DeleteSessionResponse>(
            HttpMethod.Delete,
            $"api/v1/history/sessions/{Uri.EscapeDataString(sessionId)}",
            userId,
            null,
            cancellationToken);

    public Task<FeedbackResponse> SaveFeedbackAsync(
        string messageId,
        FeedbackRequest request,
        string userId,
        CancellationToken cancellationToken) =>
        SendAsync<FeedbackResponse>(
            HttpMethod.Put,
            $"api/v1/feedback/messages/{Uri.EscapeDataString(messageId)}",
            userId,
            request,
            cancellationToken);

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string path,
        string userId,
        object? body,
        CancellationToken cancellationToken)
    {
        using var message = CreateRequest(method, path, userId);
        if (body is not null)
        {
            message.Content = JsonContent.Create(body, options: JsonOptions);
        }

        try
        {
            using var response = await httpClient.SendAsync(message, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                throw new RagServiceException((int)response.StatusCode);
            }
            var result = await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken);
            return result ?? throw new RagServiceException((int)HttpStatusCode.BadGateway);
        }
        catch (OperationCanceledException exception) when (!cancellationToken.IsCancellationRequested)
        {
            throw new RagServiceException((int)HttpStatusCode.GatewayTimeout, true, exception);
        }
        catch (HttpRequestException exception)
        {
            throw new RagServiceException((int)HttpStatusCode.ServiceUnavailable, false, exception);
        }
        catch (JsonException exception)
        {
            throw new RagServiceException((int)HttpStatusCode.BadGateway, false, exception);
        }
    }

    private HttpRequestMessage CreateRequest(HttpMethod method, string path, string userId)
    {
        var request = new HttpRequestMessage(method, path);
        request.Headers.Add("X-RAG-API-Key", _options.ApiKey);
        request.Headers.Add("X-Application-User-Id", userId);
        return request;
    }
}
