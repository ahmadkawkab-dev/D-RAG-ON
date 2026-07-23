using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using MongoDB.Driver;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;
using RagMiddleware.Domain.Entities;
using RagMiddleware.Infrastructure.Configuration;

namespace RagMiddleware.Api.Controllers;

[ApiController]
[Route("api/auth")]
public sealed class AuthController(
    IUserRepository users,
    ITokenService tokens,
    IOptions<FrontendOptions> frontendOptions) : ControllerBase
{
    private const string ExternalCookieScheme = "External";
    private const string RefreshCookieName = "__Secure-rag-refresh";
    private readonly FrontendOptions _frontend = frontendOptions.Value;

    [AllowAnonymous]
    [HttpGet("login/google")]
    public IActionResult LoginWithGoogle([FromQuery] string? returnPath = null)
    {
        var safeReturnPath = IsSafeRelativePath(returnPath)
            ? returnPath!
            : _frontend.OAuthCallbackPath;
        var properties = new AuthenticationProperties
        {
            RedirectUri = Url.ActionLink(nameof(CompleteGoogleLogin))
        };
        properties.Items["returnPath"] = safeReturnPath;
        return Challenge(properties, GoogleDefaults.AuthenticationScheme);
    }

    [AllowAnonymous]
    [HttpGet("google/complete")]
    public async Task<IActionResult> CompleteGoogleLogin(CancellationToken cancellationToken)
    {
        var result = await HttpContext.AuthenticateAsync(ExternalCookieScheme);
        if (!result.Succeeded || result.Principal is null)
        {
            return Unauthorized(new { code = "external_login_failed", message = "Google login could not be completed." });
        }

        var subject = result.Principal.FindFirstValue(ClaimTypes.NameIdentifier);
        var email = result.Principal.FindFirstValue(ClaimTypes.Email)?.Trim().ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(subject) || string.IsNullOrWhiteSpace(email))
        {
            await HttpContext.SignOutAsync(ExternalCookieScheme);
            return Unauthorized(new { code = "external_identity_invalid", message = "Google did not provide the required identity claims." });
        }

        var user = await users.FindByGoogleSubjectAsync(subject, cancellationToken);
        if (user is null)
        {
            var normalizedEmail = email.ToUpperInvariant();
            if (await users.FindByNormalizedEmailAsync(normalizedEmail, cancellationToken) is not null)
            {
                await HttpContext.SignOutAsync(ExternalCookieScheme);
                return Conflict(new { code = "email_link_required", message = "This email is already associated with another login." });
            }

            user = new ApplicationUser
            {
                GoogleSubject = subject,
                Email = email,
                NormalizedEmail = normalizedEmail,
                DisplayName = result.Principal.FindFirstValue(ClaimTypes.Name),
                AvatarUrl = result.Principal.FindFirstValue("picture")
                    ?? result.Principal.FindFirstValue("urn:google:picture"),
                LastLoginAtUtc = DateTimeOffset.UtcNow
            };
            try
            {
                await users.CreateAsync(user, cancellationToken);
            }
            catch (MongoWriteException)
            {
                await HttpContext.SignOutAsync(ExternalCookieScheme);
                return Conflict(new { code = "external_identity_conflict", message = "The Google account could not be linked safely." });
            }
        }
        else
        {
            user.Email = email;
            user.NormalizedEmail = email.ToUpperInvariant();
            user.DisplayName = result.Principal.FindFirstValue(ClaimTypes.Name) ?? user.DisplayName;
            user.AvatarUrl = result.Principal.FindFirstValue("picture")
                ?? result.Principal.FindFirstValue("urn:google:picture")
                ?? user.AvatarUrl;
            user.LastLoginAtUtc = DateTimeOffset.UtcNow;
            await users.UpdateAsync(user, cancellationToken);
        }

        var pair = await tokens.IssueTokensAsync(user, ClientIp(), cancellationToken);
        SetRefreshCookie(pair.RefreshToken);
        string? returnPath = null;
        result.Properties?.Items.TryGetValue("returnPath", out returnPath);
        await HttpContext.SignOutAsync(ExternalCookieScheme);
        return Redirect(BuildFrontendRedirect(returnPath));
    }

    [AllowAnonymous]
    [HttpPost("refresh")]
    public async Task<ActionResult<AccessTokenResponse>> Refresh(CancellationToken cancellationToken)
    {
        if (!IsAllowedOrigin() || !Request.Cookies.TryGetValue(RefreshCookieName, out var refreshToken))
        {
            return Unauthorized();
        }

        var pair = await tokens.RotateRefreshTokenAsync(refreshToken, ClientIp(), cancellationToken);
        if (pair is null)
        {
            DeleteRefreshCookie();
            return Unauthorized();
        }

        SetRefreshCookie(pair.RefreshToken);
        return Ok(new AccessTokenResponse(pair.AccessToken, "Bearer", pair.ExpiresInSeconds));
    }

    [Authorize]
    [HttpGet("me")]
    public async Task<ActionResult<UserResponse>> Me(CancellationToken cancellationToken)
    {
        var userId = User.FindFirstValue(JwtRegisteredClaimNames.Sub);
        if (string.IsNullOrWhiteSpace(userId))
        {
            return Unauthorized();
        }

        var user = await users.FindByIdAsync(userId, cancellationToken);
        return user is null ? Unauthorized() : Ok(UserResponse.FromUser(user));
    }

    [AllowAnonymous]
    [HttpPost("logout")]
    public async Task<IActionResult> Logout(CancellationToken cancellationToken)
    {
        if (IsAllowedOrigin() && Request.Cookies.TryGetValue(RefreshCookieName, out var refreshToken))
        {
            await tokens.RevokeRefreshTokenAsync(refreshToken, ClientIp(), cancellationToken);
        }
        DeleteRefreshCookie();
        await HttpContext.SignOutAsync(ExternalCookieScheme);
        return NoContent();
    }

    private bool IsAllowedOrigin()
    {
        var origin = Request.Headers.Origin.ToString();
        return string.IsNullOrWhiteSpace(origin)
            || _frontend.AllowedOrigins.Contains(origin, StringComparer.OrdinalIgnoreCase);
    }

    private static bool IsSafeRelativePath(string? path) =>
        !string.IsNullOrWhiteSpace(path)
        && path.StartsWith("/", StringComparison.Ordinal)
        && !path.StartsWith("//", StringComparison.Ordinal)
        && !path.Contains('\\');

    private string BuildFrontendRedirect(string? returnPath)
    {
        var path = IsSafeRelativePath(returnPath) ? returnPath! : _frontend.OAuthCallbackPath;
        return $"{_frontend.BaseUrl.TrimEnd('/')}{path}";
    }

    private void SetRefreshCookie(string value) =>
        Response.Cookies.Append(
            RefreshCookieName,
            value,
            new CookieOptions
            {
                HttpOnly = true,
                Secure = true,
                SameSite = SameSiteMode.None,
                Path = "/api/auth",
                IsEssential = true
            });

    private void DeleteRefreshCookie() =>
        Response.Cookies.Delete(
            RefreshCookieName,
            new CookieOptions
            {
                Secure = true,
                SameSite = SameSiteMode.None,
                Path = "/api/auth"
            });

    private string? ClientIp() => HttpContext.Connection.RemoteIpAddress?.ToString();
}
