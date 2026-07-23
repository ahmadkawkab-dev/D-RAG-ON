using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Api.Controllers;

[ApiController]
[Authorize]
[Route("api/rag")]
public sealed class RagController(IRagApiClient ragApiClient) : ControllerBase
{
    [HttpPost("document/stream")]
    public Task StreamDocument(
        RagChatRequest request,
        CancellationToken cancellationToken) =>
        Stream("document", request, cancellationToken);

    [HttpPost("general/stream")]
    public Task StreamGeneral(
        RagChatRequest request,
        CancellationToken cancellationToken) =>
        Stream("general", request, cancellationToken);

    [HttpGet("history/sessions")]
    public async Task<IActionResult> ListSessions(
        [FromQuery] string? mode,
        CancellationToken cancellationToken)
    {
        try
        {
            return Ok(await ragApiClient.ListSessionsAsync(
                mode,
                UserId(),
                cancellationToken));
        }
        catch (RagServiceException exception)
        {
            return RagFailure(exception);
        }
    }

    [HttpGet("history/sessions/{sessionId}")]
    public async Task<IActionResult> GetSession(
        string sessionId,
        CancellationToken cancellationToken)
    {
        try
        {
            return Ok(await ragApiClient.GetSessionAsync(
                sessionId,
                UserId(),
                cancellationToken));
        }
        catch (RagServiceException exception)
        {
            return RagFailure(exception);
        }
    }

    [HttpDelete("history/sessions/{sessionId}")]
    public async Task<IActionResult> DeleteSession(
        string sessionId,
        CancellationToken cancellationToken)
    {
        try
        {
            return Ok(await ragApiClient.DeleteSessionAsync(
                sessionId,
                UserId(),
                cancellationToken));
        }
        catch (RagServiceException exception)
        {
            return RagFailure(exception);
        }
    }

    [HttpPut("feedback/messages/{messageId}")]
    public async Task<IActionResult> SaveFeedback(
        string messageId,
        FeedbackRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            return Ok(await ragApiClient.SaveFeedbackAsync(
                messageId,
                request,
                UserId(),
                cancellationToken));
        }
        catch (RagServiceException exception)
        {
            return RagFailure(exception);
        }
    }

    private async Task Stream(
        string mode,
        RagChatRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            await using var response = await ragApiClient.StreamChatAsync(
                mode,
                request,
                UserId(),
                cancellationToken);
            Response.StatusCode = StatusCodes.Status200OK;
            Response.ContentType = "text/event-stream";
            Response.Headers.CacheControl = "no-cache, no-transform";
            Response.Headers.Append("X-Accel-Buffering", "no");
            await response.Stream.CopyToAsync(Response.Body, cancellationToken);
        }
        catch (RagServiceException exception) when (!Response.HasStarted)
        {
            var result = RagFailure(exception);
            await result.ExecuteResultAsync(ControllerContext);
        }
    }

    private string UserId() =>
        User.FindFirstValue(JwtRegisteredClaimNames.Sub)
        ?? throw new InvalidOperationException("The validated access token has no subject.");

    private ObjectResult RagFailure(RagServiceException exception)
    {
        var (status, code, message) = exception switch
        {
            { TimedOut: true } => (504, "rag_timeout", "The RAG service timed out."),
            { StatusCode: 404 } => (404, "rag_not_found", "The requested RAG resource was not found."),
            { StatusCode: >= 400 and < 500 } => (400, "rag_request_invalid", "The RAG request was invalid."),
            { StatusCode: 503 } => (503, "rag_service_unavailable", "The RAG service is temporarily unavailable."),
            _ => (502, "rag_service_error", "The RAG service could not complete the request.")
        };
        return StatusCode(
            status,
            new RagErrorResponse(code, message, HttpContext.TraceIdentifier));
    }
}
