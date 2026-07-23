namespace RagMiddleware.Application.Contracts;

public sealed record RagChatRequest(
    string Message,
    string? SessionId,
    string? RegenerateMessageId);

public sealed record FeedbackRequest(
    string Direction,
    IReadOnlyList<string> Chips,
    string Comment);

public sealed record Citation(
    string DocumentId,
    string Title,
    string? SourceUrl,
    string? FilePath,
    int? PageNumber,
    string? Section,
    string? ChunkId,
    IReadOnlyList<string> Breadcrumb,
    string? Summary,
    IReadOnlyDictionary<string, object?> Metadata,
    string ChunkText,
    double? Score,
    double? Relevance);

public sealed record FeedbackResponse(
    string Id,
    string MessageId,
    string SessionId,
    string Mode,
    string Direction,
    IReadOnlyList<string> Chips,
    string Comment,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

public sealed record ChatSessionResponse(
    string Id,
    string Title,
    string Mode,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

public sealed record ChatMessageResponse(
    string Id,
    string SessionId,
    string Role,
    string Content,
    IReadOnlyList<Citation> Sources,
    DateTimeOffset Timestamp,
    string? ReplyToMessageId,
    int Version,
    FeedbackResponse? Feedback);

public sealed record ChatSessionDetail(
    ChatSessionResponse Session,
    IReadOnlyList<ChatMessageResponse> Messages);

public sealed record DeleteSessionResponse(bool Deleted, string SessionId);

public sealed record RagErrorResponse(string Code, string Message, string TraceId);
