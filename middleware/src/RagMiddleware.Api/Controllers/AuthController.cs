using System.ComponentModel.DataAnnotations;
using System.Diagnostics;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Google;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.RateLimiting;
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
    IAuditLogService auditLogs,
    IOptions<JwtOptions> jwtOptions,
    IOptions<FrontendOptions> frontendOptions) : ControllerBase
{
    private const string ExternalCookieScheme = "External";
    private const string RefreshCookieName = "__Secure-rag-refresh";
    private readonly FrontendOptions _frontend = frontendOptions.Value;
    private readonly JwtOptions _jwt = jwtOptions.Value;

    [AllowAnonymous]
    [HttpGet("login/google")]
    [EnableRateLimiting("Auth")]
    public async Task<IActionResult> LoginWithGoogle(
        [FromQuery, StringLength(256)] string? returnPath = null)
    {
        var stopwatch = Stopwatch.StartNew();
        if (returnPath is not null && !IsSafeRelativePath(returnPath))
        {
            await WriteAuditAsync(
                AuditActions.AuthLoginFailed,
                StatusCodes.Status400BadRequest,
                false,
                stopwatch,
                failureCode: "INVALID_RETURN_PATH");
            return BadRequest(new
            {
                code = "invalid_return_path",
                message = "The return path must be a local relative path."
            });
        }
        var safeReturnPath = IsSafeRelativePath(returnPath)
            ? returnPath!
            : _frontend.OAuthCallbackPath;
        var properties = new AuthenticationProperties
        {
            RedirectUri = Url.ActionLink(nameof(CompleteGoogleLogin))
        };
        properties.Items["returnPath"] = safeReturnPath;
        await WriteAuditAsync(
            AuditActions.AuthLoginStarted,
            StatusCodes.Status302Found,
            true,
            stopwatch,
            summary: "Google login challenge initiated");
        return Challenge(properties, GoogleDefaults.AuthenticationScheme);
    }

    [AllowAnonymous]
    [HttpGet("google/complete")]
    [EnableRateLimiting("OAuthCallback")]
    public async Task<IActionResult> CompleteGoogleLogin(
        CancellationToken cancellationToken)
    {
        var stopwatch = Stopwatch.StartNew();
        try
        {
            var result = await HttpContext.AuthenticateAsync(ExternalCookieScheme);
            if (!result.Succeeded || result.Principal is null)
            {
                await WriteAuditAsync(
                    AuditActions.AuthLoginFailed,
                    StatusCodes.Status401Unauthorized,
                    false,
                    stopwatch,
                    failureCode: "GOOGLE_CALLBACK_FAILED");
                return Unauthorized(new
                {
                    code = "external_login_failed",
                    message = "Google login could not be completed."
                });
            }

            var subject = result.Principal.FindFirstValue(ClaimTypes.NameIdentifier);
            var email = result.Principal.FindFirstValue(ClaimTypes.Email)?
                .Trim()
                .ToLowerInvariant();
            if (string.IsNullOrWhiteSpace(subject) || string.IsNullOrWhiteSpace(email))
            {
                await HttpContext.SignOutAsync(ExternalCookieScheme);
                await WriteAuditAsync(
                    AuditActions.AuthLoginFailed,
                    StatusCodes.Status401Unauthorized,
                    false,
                    stopwatch,
                    failureCode: "EXTERNAL_IDENTITY_MISSING");
                return Unauthorized(new
                {
                    code = "external_identity_invalid",
                    message = "Google did not provide the required identity claims."
                });
            }

            var user = await users.FindByGoogleSubjectAsync(subject, cancellationToken);
            if (user is null)
            {
                var normalizedEmail = email.ToUpperInvariant();
                if (await users.FindByNormalizedEmailAsync(
                        normalizedEmail,
                        cancellationToken) is not null)
                {
                    await HttpContext.SignOutAsync(ExternalCookieScheme);
                    await WriteAuditAsync(
                        AuditActions.AuthLoginFailed,
                        StatusCodes.Status409Conflict,
                        false,
                        stopwatch,
                        failureCode: "IDENTITY_LINK_CONFLICT");
                    return Conflict(new
                    {
                        code = "email_link_required",
                        message = "This email is already associated with another login."
                    });
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
                    await WriteAuditAsync(
                        AuditActions.AuthLoginFailed,
                        StatusCodes.Status409Conflict,
                        false,
                        stopwatch,
                        failureCode: "USER_CREATION_FAILED");
                    return Conflict(new
                    {
                        code = "external_identity_conflict",
                        message = "The Google account could not be linked safely."
                    });
                }
            }
            else
            {
                user.Email = email;
                user.NormalizedEmail = email.ToUpperInvariant();
                user.DisplayName = result.Principal.FindFirstValue(ClaimTypes.Name)
                    ?? user.DisplayName;
                user.AvatarUrl = result.Principal.FindFirstValue("picture")
                    ?? result.Principal.FindFirstValue("urn:google:picture")
                    ?? user.AvatarUrl;
                user.LastLoginAtUtc = DateTimeOffset.UtcNow;
                await users.UpdateAsync(user, cancellationToken);
            }

            var pair = await tokens.IssueTokensAsync(
                user,
                ClientIp(),
                cancellationToken);
            SetRefreshCookie(pair.RefreshToken);
            string? returnPath = null;
            result.Properties?.Items.TryGetValue("returnPath", out returnPath);
            await HttpContext.SignOutAsync(ExternalCookieScheme);
            await WriteAuditAsync(
                AuditActions.AuthLoginSuccess,
                StatusCodes.Status302Found,
                true,
                stopwatch,
                user.Id,
                "Google login completed");
            return Redirect(BuildFrontendRedirect(returnPath));
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            await WriteAuditAsync(
                AuditActions.AuthLoginFailed,
                StatusCodes.Status499ClientClosedRequest,
                false,
                stopwatch,
                failureCode: "CLIENT_DISCONNECTED");
            throw;
        }
        catch
        {
            await WriteAuditAsync(
                AuditActions.AuthLoginFailed,
                StatusCodes.Status500InternalServerError,
                false,
                stopwatch,
                failureCode: "GOOGLE_CALLBACK_FAILED");
            throw;
        }
    }

    [AllowAnonymous]
    [HttpPost("refresh")]
    [EnableRateLimiting("Auth")]
    public async Task<ActionResult<AccessTokenResponse>> Refresh(
        CancellationToken cancellationToken)
    {
        var stopwatch = Stopwatch.StartNew();
        if (!IsAllowedOrigin()
            || !Request.Cookies.TryGetValue(RefreshCookieName, out var refreshToken))
        {
            await WriteAuditAsync(
                AuditActions.AuthRefreshFailed,
                StatusCodes.Status401Unauthorized,
                false,
                stopwatch,
                failureCode: "INVALID_REFRESH_TOKEN");
            return Unauthorized();
        }

        var pair = await tokens.RotateRefreshTokenAsync(
            refreshToken,
            ClientIp(),
            cancellationToken);
        if (pair is null)
        {
            DeleteRefreshCookie();
            await WriteAuditAsync(
                AuditActions.AuthRefreshFailed,
                StatusCodes.Status401Unauthorized,
                false,
                stopwatch,
                failureCode: "INVALID_REFRESH_TOKEN");
            return Unauthorized();
        }

        SetRefreshCookie(pair.RefreshToken);
        await WriteAuditAsync(
            AuditActions.AuthRefreshSuccess,
            StatusCodes.Status200OK,
            true,
            stopwatch,
            SubjectFromAccessToken(pair.AccessToken),
            "Session refreshed");
        return Ok(new AccessTokenResponse(
            pair.AccessToken,
            "Bearer",
            pair.ExpiresInSeconds));
    }

    [Authorize]
    [HttpGet("me")]
    [EnableRateLimiting("Auth")]
    public async Task<ActionResult<UserResponse>> Me(
        CancellationToken cancellationToken)
    {
        var userId = User.FindFirstValue(JwtRegisteredClaimNames.Sub);
        if (string.IsNullOrWhiteSpace(userId))
            return Unauthorized();

        var user = await users.FindByIdAsync(userId, cancellationToken);
        return user is null ? Unauthorized() : Ok(UserResponse.FromUser(user));
    }

    [AllowAnonymous]
    [HttpPost("logout")]
    [EnableRateLimiting("Auth")]
    public async Task<IActionResult> Logout(CancellationToken cancellationToken)
    {
        var stopwatch = Stopwatch.StartNew();
        if (IsAllowedOrigin()
            && Request.Cookies.TryGetValue(RefreshCookieName, out var refreshToken))
        {
            await tokens.RevokeRefreshTokenAsync(
                refreshToken,
                ClientIp(),
                cancellationToken);
        }
        DeleteRefreshCookie();
        await HttpContext.SignOutAsync(ExternalCookieScheme);
        await WriteAuditAsync(
            AuditActions.AuthLogout,
            StatusCodes.Status204NoContent,
            true,
            stopwatch,
            User.FindFirstValue(JwtRegisteredClaimNames.Sub),
            "Session logout requested");
        return NoContent();
    }

    private async Task WriteAuditAsync(
        string action,
        int statusCode,
        bool succeeded,
        Stopwatch stopwatch,
        string? userId = null,
        string? summary = null,
        string? failureCode = null)
    {
        stopwatch.Stop();
        await auditLogs.WriteAsync(
            new AuditLogEntry(
                action,
                Request.Path.Value ?? "/api/auth",
                Request.Method,
                statusCode,
                succeeded,
                DateTimeOffset.UtcNow - stopwatch.Elapsed,
                stopwatch.ElapsedMilliseconds,
                userId,
                summary,
                ClientIp(),
                Request.Headers.UserAgent.ToString(),
                Activity.Current?.TraceId.ToString() ?? HttpContext.TraceIdentifier,
                failureCode),
            CancellationToken.None);
    }

    private bool IsAllowedOrigin()
    {
        var origin = Request.Headers.Origin.ToString();
        return string.IsNullOrWhiteSpace(origin)
            || _frontend.AllowedOrigins.Contains(
                origin,
                StringComparer.OrdinalIgnoreCase);
    }

    private static bool IsSafeRelativePath(string? path) =>
        !string.IsNullOrWhiteSpace(path)
        && path.StartsWith("/", StringComparison.Ordinal)
        && !path.StartsWith("//", StringComparison.Ordinal)
        && !path.Contains('\\');

    private string BuildFrontendRedirect(string? returnPath)
    {
        var path = IsSafeRelativePath(returnPath)
            ? returnPath!
            : _frontend.OAuthCallbackPath;
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
                IsEssential = true,
                Expires = DateTimeOffset.UtcNow.AddDays(_jwt.RefreshTokenLifetimeDays),
                MaxAge = TimeSpan.FromDays(_jwt.RefreshTokenLifetimeDays)
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

    private string? ClientIp() =>
        HttpContext.Connection.RemoteIpAddress?.ToString();

    private static string? SubjectFromAccessToken(string accessToken) =>
        new JwtSecurityTokenHandler().ReadJwtToken(accessToken).Subject;
}
