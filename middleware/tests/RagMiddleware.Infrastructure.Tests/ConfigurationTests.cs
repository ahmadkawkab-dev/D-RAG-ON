using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Infrastructure.Tests;

public sealed class ConfigurationTests
{
    [Fact]
    public void Rag_configuration_binds_and_validates()
    {
        using var provider = Provider<RagApiOptions>(
            RagApiOptions.SectionName,
            new Dictionary<string, string?>
            {
                ["RagApi:BaseUrl"] = "http://localhost:8000",
                ["RagApi:ApiKey"] = "a-test-key-that-is-at-least-32-characters"
            });

        var options = provider.GetRequiredService<IOptions<RagApiOptions>>().Value;

        Assert.Equal("http://localhost:8000", options.BaseUrl);
    }

    [Fact]
    public void Missing_rag_service_key_fails_validation()
    {
        using var provider = Provider<RagApiOptions>(
            RagApiOptions.SectionName,
            new Dictionary<string, string?> { ["RagApi:BaseUrl"] = "http://localhost:8000" });

        Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<RagApiOptions>>().Value);
    }

    [Theory]
    [InlineData("Authentication:Google:ClientId")]
    [InlineData("Authentication:Google:ClientSecret")]
    public void Missing_google_secret_fails_validation(string missingKey)
    {
        var values = new Dictionary<string, string?>
        {
            ["Authentication:Google:ClientId"] = "client-id",
            ["Authentication:Google:ClientSecret"] = "client-secret",
            ["Authentication:Google:CallbackPath"] = "/signin-google"
        };
        values.Remove(missingKey);
        using var provider = Provider<GoogleAuthOptions>(GoogleAuthOptions.SectionName, values);

        Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<GoogleAuthOptions>>().Value);
    }

    [Fact]
    public void Missing_jwt_signing_key_fails_validation()
    {
        using var provider = Provider<JwtOptions>(
            JwtOptions.SectionName,
            new Dictionary<string, string?>
            {
                ["Authentication:Jwt:Issuer"] = "rag-middleware",
                ["Authentication:Jwt:Audience"] = "rag-ui"
            });

        Assert.Throws<OptionsValidationException>(
            () => provider.GetRequiredService<IOptions<JwtOptions>>().Value);
    }

    private static ServiceProvider Provider<T>(
        string section,
        IDictionary<string, string?> values) where T : class
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(values)
            .Build();
        var services = new ServiceCollection();
        services.AddOptions<T>()
            .Bind(configuration.GetSection(section))
            .ValidateDataAnnotations()
            .ValidateOnStart();
        return services.BuildServiceProvider();
    }
}
