using Microsoft.Extensions.Diagnostics.HealthChecks;
using MongoDB.Bson;
using RagMiddleware.Infrastructure.Persistence;

namespace RagMiddleware.Infrastructure.Health;

public sealed class MongoHealthCheck(
    MongoContext context) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext healthContext,
        CancellationToken cancellationToken = default)
    {
        try
        {
            await context.Database.RunCommandAsync<BsonDocument>(
                new BsonDocument("ping", 1),
                cancellationToken: cancellationToken);
            return HealthCheckResult.Healthy();
        }
        catch
        {
            return HealthCheckResult.Unhealthy("MongoDB is unavailable.");
        }
    }
}
