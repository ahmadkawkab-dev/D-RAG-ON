namespace RagMiddleware.Application.Contracts;

public static class AuditActions
{
    public const string AuthLoginStarted = "AUTH_LOGIN_STARTED";
    public const string AuthLoginSuccess = "AUTH_LOGIN_SUCCESS";
    public const string AuthLoginFailed = "AUTH_LOGIN_FAILED";
    public const string AuthRefreshSuccess = "AUTH_REFRESH_SUCCESS";
    public const string AuthRefreshFailed = "AUTH_REFRESH_FAILED";
    public const string AuthLogout = "AUTH_LOGOUT";
    public const string AuthProfileView = "AUTH_PROFILE_VIEW";
    public const string AuthUnauthorized = "AUTH_UNAUTHORIZED";
    public const string AuthForbidden = "AUTH_FORBIDDEN";
    public const string AuthRateLimited = "AUTH_RATE_LIMITED";
    public const string RagQuery = "RAG_QUERY";
    public const string RagQueryFailed = "RAG_QUERY_FAILED";
    public const string RagDocumentUpload = "RAG_DOCUMENT_UPLOAD";
    public const string RagHistoryList = "RAG_HISTORY_LIST";
    public const string RagHistoryGet = "RAG_HISTORY_GET";
    public const string RagHistoryDelete = "RAG_HISTORY_DELETE";
    public const string RagFeedbackSave = "RAG_FEEDBACK_SAVE";
    public const string RagRequestFailed = "RAG_REQUEST_FAILED";
    public const string AdminAuditLogView = "ADMIN_AUDIT_LOG_VIEW";
}

public sealed record AuditLogEntry(
    string Action,
    string Endpoint,
    string HttpMethod,
    int StatusCode,
    bool Succeeded,
    DateTimeOffset TimestampUtc,
    long DurationMs,
    string? UserId = null,
    string? RequestSummary = null,
    string? IpAddress = null,
    string? UserAgent = null,
    string? TraceId = null,
    string? FailureCode = null);

public sealed record AuditLogQuery(
    int Page = 1,
    int PageSize = 50,
    string? UserId = null,
    string? Action = null,
    DateTimeOffset? FromUtc = null,
    DateTimeOffset? ToUtc = null,
    bool? Succeeded = null,
    int? StatusCode = null);

public sealed record AuditLogItem(
    string Id,
    string? UserId,
    string Action,
    string Endpoint,
    string HttpMethod,
    string? RequestSummary,
    int StatusCode,
    string? IpAddress,
    string? TraceId,
    DateTimeOffset TimestampUtc,
    long DurationMs,
    bool Succeeded,
    string? FailureCode);

public sealed record AuditLogPage(
    IReadOnlyList<AuditLogItem> Items,
    int Page,
    int PageSize,
    long TotalCount);
