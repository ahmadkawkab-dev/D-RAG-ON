using System.ComponentModel.DataAnnotations;

namespace RagMiddleware.Infrastructure.Configuration;

public sealed class RateLimitOptions
{
    public const string SectionName = "RateLimiting";

    [Range(1, 1000)]
    public int AuthPermitLimit { get; init; } = 10;

    [Range(1, 3600)]
    public int AuthWindowSeconds { get; init; } = 60;

    [Range(1, 1000)]
    public int OAuthCallbackPermitLimit { get; init; } = 30;

    [Range(1, 1000)]
    public int RagTokenLimit { get; init; } = 20;

    [Range(1, 1000)]
    public int RagTokensPerPeriod { get; init; } = 20;

    [Range(1, 3600)]
    public int RagReplenishmentSeconds { get; init; } = 60;

    [Range(1, 100)]
    public int RagConcurrencyLimit { get; init; } = 4;

    [Range(1, 1000)]
    public int AdminPermitLimit { get; init; } = 60;

    [Range(1, 3600)]
    public int AdminWindowSeconds { get; init; } = 60;
}

public sealed class RequestLimitOptions
{
    public const string SectionName = "RequestLimits";

    [Range(1024, 20 * 1024 * 1024)]
    public long MaxRequestBodyBytes { get; init; } = 11 * 1024 * 1024;

    [Range(8192, 128 * 1024)]
    public int MaxRequestHeadersBytes { get; init; } = 32 * 1024;

    [Range(5, 120)]
    public int RequestHeadersTimeoutSeconds { get; init; } = 15;

    [Range(8, 128)]
    public int JsonMaxDepth { get; init; } = 32;
}

public sealed class ProxyOptions
{
    public const string SectionName = "Proxy";

    public string[] KnownProxies { get; init; } = [];
}
