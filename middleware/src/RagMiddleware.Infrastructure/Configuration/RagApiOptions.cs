using System.ComponentModel.DataAnnotations;

namespace RagMiddleware.Infrastructure.Configuration;

public sealed class RagApiOptions
{
    public const string SectionName = "RagApi";

    [Required, Url]
    public required string BaseUrl { get; init; }

    [Required, MinLength(32)]
    public required string ApiKey { get; init; }

    [Range(30, 3600)]
    public int TimeoutSeconds { get; init; } = 900;
}
