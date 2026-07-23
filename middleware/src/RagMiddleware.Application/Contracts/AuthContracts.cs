using RagMiddleware.Domain.Entities;

namespace RagMiddleware.Application.Contracts;

public sealed record TokenPair(
    string AccessToken,
    string RefreshToken,
    int ExpiresInSeconds);

public sealed record AccessTokenResponse(
    string AccessToken,
    string TokenType,
    int ExpiresIn);

public sealed record UserResponse(
    string Id,
    string Email,
    string? DisplayName,
    string? AvatarUrl,
    IReadOnlyList<string> Roles)
{
    public static UserResponse FromUser(ApplicationUser user) =>
        new(user.Id, user.Email, user.DisplayName, user.AvatarUrl, user.Roles);
}
