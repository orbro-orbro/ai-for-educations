import { ApiError, isApiError } from "../api/client";

export function RequestState({ error, retry, retryLabel, deniedLabel = "无法访问该资源" }: { error: unknown; retry?: () => void; retryLabel?: string; deniedLabel?: string }) {
  const apiError = isApiError(error) ? error : new ApiError(0, { code: "CLIENT_ERROR", message: "请求未完成", request_id: "unknown" });
  const denied = apiError.status === 403 || apiError.status === 404;
  const title = denied ? deniedLabel : apiError.status === 401 ? "登录状态已失效" : apiError.status === 503 ? "服务暂不可用" : "请求未完成";
  return (
    <div className={`request-state ${denied ? "is-denied" : "is-error"}`} role="alert">
      <strong>{title}</strong>
      <p>{denied ? "请返回可访问的课程，或联系课程教师确认权限。" : "你的操作未丢失，可以稍后重试。"}</p>
      <p className="request-id">请求编号：{apiError.requestId}</p>
      {retry && <button type="button" className="button-secondary" onClick={retry}>{retryLabel ?? "重试"}</button>}
    </div>
  );
}
