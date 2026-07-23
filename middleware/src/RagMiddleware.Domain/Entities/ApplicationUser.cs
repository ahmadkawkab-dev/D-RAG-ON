namespace RagMiddleware.Domain.Entities;

public sealed class ApplicationUser
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N");
    public required string GoogleSubject { get; set; }
    public required string Email { get; set; }
    public required string NormalizedEmail { get; set; }
    public string? DisplayName { get; set; }
    public string? AvatarUrl { get; set; }
    public DateTimeOffset CreatedAtUtc { get; init; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? LastLoginAtUtc { get; set; }
}
