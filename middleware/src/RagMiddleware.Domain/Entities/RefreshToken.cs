namespace RagMiddleware.Domain.Entities;

public sealed class RefreshToken
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N");
    public required string UserId { get; init; }
    public required string TokenHash { get; init; }
    public required string FamilyId { get; init; }
    public DateTimeOffset CreatedAtUtc { get; init; }
    public DateTimeOffset ExpiresAtUtc { get; init; }
    public DateTimeOffset? RevokedAtUtc { get; set; }
    public string? ReplacedByTokenHash { get; set; }
    public string? CreatedByIp { get; init; }
    public string? RevokedByIp { get; set; }
}
