using System.ComponentModel.DataAnnotations;

namespace RagMiddleware.Infrastructure.Configuration;

public sealed class GoogleAuthOptions
{
    public const string SectionName = "Authentication:Google";

    [Required]
    public required string ClientId { get; init; }

    [Required]
    public required string ClientSecret { get; init; }

    [Required]
    public string CallbackPath { get; init; } = "/signin-google";
}

public sealed class JwtOptions
{
    public const string SectionName = "Authentication:Jwt";

    [Required]
    public required string Issuer { get; init; }

    [Required]
    public required string Audience { get; init; }

    [Required, MinLength(32)]
    public required string SigningKey { get; init; }

    [Range(5, 60)]
    public int AccessTokenLifetimeMinutes { get; init; } = 15;

    [Range(1, 90)]
    public int RefreshTokenLifetimeDays { get; init; } = 30;
}

public sealed class MongoDbOptions
{
    public const string SectionName = "MongoDb";

    [Required]
    public required string ConnectionString { get; init; }

    [Required]
    public string DatabaseName { get; init; } = "rag_app";
}

public sealed class FrontendOptions
{
    public const string SectionName = "Frontend";

    [Required, Url]
    public required string BaseUrl { get; init; }

    [Required]
    public string OAuthCallbackPath { get; init; } = "/auth/callback";

    [MinLength(1)]
    public required string[] AllowedOrigins { get; init; }
}
