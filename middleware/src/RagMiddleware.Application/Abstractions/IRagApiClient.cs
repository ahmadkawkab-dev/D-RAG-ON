using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Application.Abstractions;

public interface IRagApiClient
{
    Task<RagStreamResponse> StreamChatAsync(
        string mode,
        RagChatRequest request,
        string userId,
        CancellationToken cancellationToken);

    Task<ChatMessageResponse> SelectGeneralAnswerAsync(
        GeneralAnswerSelectionRequest request,
        string userId,
        CancellationToken cancellationToken);

    Task<IReadOnlyList<ChatSessionResponse>> ListSessionsAsync(
        string? mode,
        string userId,
        CancellationToken cancellationToken);

    Task<ChatSessionDetail> GetSessionAsync(
        string sessionId,
        string userId,
        CancellationToken cancellationToken);

    Task<DeleteSessionResponse> DeleteSessionAsync(
        string sessionId,
        string userId,
        CancellationToken cancellationToken);

    Task<DocumentUploadResponse> UploadDocumentAsync(
        Stream stream,
        long sizeBytes,
        string userId,
        CancellationToken cancellationToken);

    Task<FeedbackResponse> SaveFeedbackAsync(
        string messageId,
        FeedbackRequest request,
        string userId,
        CancellationToken cancellationToken);
}

public sealed class RagStreamResponse : IAsyncDisposable
{
    private readonly HttpResponseMessage _response;

    public RagStreamResponse(HttpResponseMessage response, Stream stream)
    {
        _response = response;
        Stream = stream;
    }

    public Stream Stream { get; }

    public ValueTask DisposeAsync()
    {
        Stream.Dispose();
        _response.Dispose();
        return ValueTask.CompletedTask;
    }
}

public sealed class RagServiceException(
    int statusCode,
    bool timedOut = false,
    Exception? innerException = null)
    : Exception("The internal RAG service request failed.", innerException)
{
    public int StatusCode { get; } = statusCode;
    public bool TimedOut { get; } = timedOut;
}
