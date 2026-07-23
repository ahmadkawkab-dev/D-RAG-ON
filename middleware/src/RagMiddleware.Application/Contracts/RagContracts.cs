using System.ComponentModel.DataAnnotations;

namespace RagMiddleware.Application.Contracts;

public static class RagValidation
{
    public const string IdentifierPattern = "^[A-Za-z0-9-]{1,128}$";
}

public sealed record RagChatRequest(
    [Required, StringLength(10000, MinimumLength = 1)]
    string Message,
    [RegularExpression(RagValidation.IdentifierPattern)]
    string? SessionId,
    [RegularExpression(RagValidation.IdentifierPattern)]
    string? RegenerateMessageId) : IValidatableObject
{
    public IEnumerable<ValidationResult> Validate(
        ValidationContext validationContext)
    {
        if (string.IsNullOrWhiteSpace(Message))
        {
            yield return new ValidationResult(
                "Message cannot be empty or whitespace.",
                [nameof(Message)]);
        }
    }
}

public sealed record FeedbackRequest(
    [Required, RegularExpression("^(up|down)$")]
    string Direction,
    [Required, MaxLength(20)]
    IReadOnlyList<string> Chips,
    [StringLength(2000)]
    string Comment) : IValidatableObject
{
    public IEnumerable<ValidationResult> Validate(
        ValidationContext validationContext)
    {
        if (Chips.Any(chip =>
                string.IsNullOrWhiteSpace(chip)
                || chip.Length > 64))
        {
            yield return new ValidationResult(
                "Feedback chips must contain 1 through 64 characters.",
                [nameof(Chips)]);
        }
    }
}

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

public sealed record DocumentUploadResponse(
    string DocumentId,
    int ChunkCount,
    string Status);

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

public sealed record DeleteSessionResponse(
    bool Deleted,
    string SessionId);

public sealed record RagErrorResponse(
    string Code,
    string Message,
    string TraceId);
