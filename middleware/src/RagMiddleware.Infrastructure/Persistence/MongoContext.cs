using Microsoft.Extensions.Options;
using MongoDB.Driver;
using RagMiddleware.Domain.Entities;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Persistence;

public sealed class MongoContext
{
    public MongoContext(IOptions<MongoDbOptions> options)
    {
        var client = new MongoClient(options.Value.ConnectionString);
        Database = client.GetDatabase(options.Value.DatabaseName);
    }

    public IMongoDatabase Database { get; }
    public IMongoCollection<ApplicationUser> Users =>
        Database.GetCollection<ApplicationUser>("application_users");
    public IMongoCollection<RefreshToken> RefreshTokens =>
        Database.GetCollection<RefreshToken>("refresh_tokens");
}
