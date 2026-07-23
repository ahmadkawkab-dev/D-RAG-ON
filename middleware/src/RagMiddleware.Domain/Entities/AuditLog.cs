namespace RagMiddleware.Domain.Entities;

public sealed class AuditLog
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N");
    public string? UserId { get; init; }
    public required string Action { get; init; }
    public required string Endpoint { get; init; }
    public required string HttpMethod { get; init; }
    public string? RequestSummary { get; init; }
    public int StatusCode { get; init; }
    public string? IpAddress { get; init; }
    public string? UserAgent { get; init; }
    public string? TraceId { get; init; }
    public DateTimeOffset TimestampUtc { get; init; }
    public long DurationMs { get; init; }
    public bool Succeeded { get; init; }
    public string? FailureCode { get; init; }
}
