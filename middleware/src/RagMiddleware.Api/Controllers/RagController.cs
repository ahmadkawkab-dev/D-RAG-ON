using System.ComponentModel.DataAnnotations;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.AspNetCore.Mvc;
using RagMiddleware.Api.Middleware;
using RagMiddleware.Application.Abstractions;
using RagMiddleware.Application.Contracts;

namespace RagMiddleware.Api.Controllers;

[ApiController]
[Authorize]
[Route("api/rag")]
[EnableRateLimiting("Rag")]
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
        [FromQuery, RegularExpression("^(general|document)$")] string? mode,
        CancellationToken cancellationToken)
    {
        HttpContext.Items[AuditLoggingMiddleware.SummaryItem] =
            $"Session history listed; mode={SafeMode(mode)}";
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
        [FromRoute, RegularExpression(RagValidation.IdentifierPattern)] string sessionId,
        CancellationToken cancellationToken)
    {
        HttpContext.Items[AuditLoggingMiddleware.SummaryItem] =
            "Session history item requested";
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
        [FromRoute, RegularExpression(RagValidation.IdentifierPattern)] string sessionId,
        CancellationToken cancellationToken)
    {
        HttpContext.Items[AuditLoggingMiddleware.SummaryItem] =
            "Session history deletion requested";
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
        [FromRoute, RegularExpression(RagValidation.IdentifierPattern)] string messageId,
        FeedbackRequest request,
        CancellationToken cancellationToken)
    {
        HttpContext.Items[AuditLoggingMiddleware.SummaryItem] =
            $"Feedback submitted; direction={SafeDirection(request.Direction)}; "
            + $"chipCount={request.Chips.Count}; commentLength={request.Comment.Length}";
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

    [HttpPost("documents/upload")]
    [Consumes("multipart/form-data")]
    [RequestSizeLimit(11 * 1024 * 1024)]
    public async Task<IActionResult> UploadDocument(
        IFormFile file,
        CancellationToken cancellationToken)
    {
        const long maximumPdfBytes = 10 * 1024 * 1024;
        if (!Request.HasFormContentType || Request.Form.Files.Count != 1)
        {
            return BadRequest(new
            {
                code = "single_pdf_required",
                message = "Submit exactly one PDF file."
            });
        }
        if (file.Length == 0)
        {
            return BadRequest(new
            {
                code = "empty_pdf",
                message = "The PDF cannot be empty."
            });
        }
        if (file.Length > maximumPdfBytes)
        {
            return StatusCode(
                StatusCodes.Status413PayloadTooLarge,
                new
                {
                    code = "pdf_too_large",
                    message = "The PDF exceeds the 10 MiB limit."
                });
        }
        if (!string.Equals(
                Path.GetExtension(file.FileName),
                ".pdf",
                StringComparison.OrdinalIgnoreCase)
            || !string.Equals(
                file.ContentType,
                "application/pdf",
                StringComparison.OrdinalIgnoreCase))
        {
            return BadRequest(new
            {
                code = "unsupported_file",
                message = "Only application/pdf files are supported."
            });
        }

        await using var stream = file.OpenReadStream();
        var signature = new byte[5];
        var signatureLength = await stream.ReadAsync(
            signature,
            cancellationToken);
        if (signatureLength != signature.Length
            || !signature.AsSpan().SequenceEqual("%PDF-"u8))
        {
            return BadRequest(new
            {
                code = "invalid_pdf",
                message = "The uploaded file is not a valid PDF."
            });
        }
        stream.Position = 0;

        try
        {
            var result = await ragApiClient.UploadDocumentAsync(
                stream,
                file.Length,
                UserId(),
                cancellationToken);
            HttpContext.Items[AuditLoggingMiddleware.SummaryItem] =
                $"PDF indexed; extension=.pdf; sizeBytes={file.Length}; "
                + $"documentId={result.DocumentId}; chunkCount={result.ChunkCount}";
            return Ok(result);
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
        HttpContext.Items[AuditLoggingMiddleware.SummaryItem] =
            $"Query submitted; mode={mode}; length={request.Message.Length}; "
            + $"hasSession={request.SessionId is not null}; "
            + $"isRegeneration={request.RegenerateMessageId is not null}";
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
        ?? throw new InvalidOperationException(
            "The validated access token has no subject.");

    private ObjectResult RagFailure(RagServiceException exception)
    {
        var (status, code, message, auditCode) = exception switch
        {
            { TimedOut: true } => (
                504,
                "rag_timeout",
                "The RAG service timed out.",
                "RAG_STREAM_TIMEOUT"),
            { StatusCode: 404 } => (
                404,
                "rag_not_found",
                "The requested RAG resource was not found.",
                "RAG_RESOURCE_NOT_FOUND"),
            { StatusCode: >= 400 and < 500 } => (
                400,
                "rag_request_invalid",
                "The RAG request was invalid.",
                "RAG_REQUEST_REJECTED"),
            { StatusCode: 503 } => (
                503,
                "rag_service_unavailable",
                "The RAG service is temporarily unavailable.",
                "RAG_SERVICE_UNAVAILABLE"),
            _ => (
                502,
                "rag_service_error",
                "The RAG service could not complete the request.",
                "RAG_SERVICE_FAILURE")
        };
        HttpContext.Items[AuditLoggingMiddleware.FailureCodeItem] = auditCode;
        return StatusCode(
            status,
            new RagErrorResponse(code, message, HttpContext.TraceIdentifier));
    }

    private static string SafeMode(string? mode) =>
        mode is "general" or "document" ? mode : "unspecified";

    private static string SafeDirection(string direction) =>
        direction is "up" or "down" ? direction : "invalid";
}
