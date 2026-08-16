import { AxiosError, AxiosHeaders } from "axios";
import type { AxiosResponse } from "axios";
import { describe, expect, it } from "vitest";
import {
  isNotFound,
  toAuthErrorMessage,
  toErrorMessage,
} from "../../src/lib/errors";

const AUTH_MESSAGE =
  "認証の有効期限が切れた可能性があります。ページを再読み込みしてください。";

function axiosErrorWith(status: number, data?: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() };
  const response = { status, data, config } as AxiosResponse;
  return new AxiosError(
    "request failed",
    "ERR_BAD_RESPONSE",
    config,
    {},
    response,
  );
}

/** レスポンスの届かない通信エラー。axiosはresponseなしのAxiosErrorを投げる */
function networkError(): AxiosError {
  return new AxiosError("Network Error", AxiosError.ERR_NETWORK);
}

describe("toAuthErrorMessage", () => {
  it("401と403で認証切れの案内を返す", () => {
    expect(toAuthErrorMessage(401)).toBe(AUTH_MESSAGE);
    expect(toAuthErrorMessage(403)).toBe(AUTH_MESSAGE);
  });

  it("それ以外のステータスとundefinedはnullを返す", () => {
    expect(toAuthErrorMessage(404)).toBeNull();
    expect(toAuthErrorMessage(500)).toBeNull();
    expect(toAuthErrorMessage(undefined)).toBeNull();
  });
});

describe("isNotFound", () => {
  it("404のAxiosErrorだけを真とする", () => {
    expect(isNotFound(axiosErrorWith(404))).toBe(true);
    expect(isNotFound(axiosErrorWith(409))).toBe(false);
    expect(isNotFound(networkError())).toBe(false);
    expect(isNotFound(new Error("boom"))).toBe(false);
  });
});

describe("toErrorMessage", () => {
  it("401と403は認証切れの案内へ差し替える", () => {
    expect(toErrorMessage(axiosErrorWith(401), "取得に失敗しました")).toBe(
      AUTH_MESSAGE,
    );
    expect(toErrorMessage(axiosErrorWith(403), "取得に失敗しました")).toBe(
      AUTH_MESSAGE,
    );
  });

  it("404と409はそれぞれの案内を返す", () => {
    expect(toErrorMessage(axiosErrorWith(404), "取得に失敗しました")).toBe(
      "対象のドキュメントが見つかりません。一覧を再取得してください。",
    );
    expect(toErrorMessage(axiosErrorWith(409), "取得に失敗しました")).toBe(
      "ドキュメントの状態が変わっています。一覧を再取得しました。",
    );
  });

  it("レスポンスがない場合は接続失敗の補足を添える", () => {
    expect(toErrorMessage(networkError(), "取得に失敗しました")).toBe(
      "取得に失敗しました（サーバーに接続できませんでした）",
    );
  });

  it("detailがあればフォールバック文言へ添える", () => {
    const error = axiosErrorWith(400, { detail: "ファイル形式が不正です" });
    expect(toErrorMessage(error, "取得に失敗しました")).toBe(
      "取得に失敗しました（ファイル形式が不正です）",
    );
  });

  it("detailが文字列でない場合はフォールバック文言のみ返す", () => {
    expect(toErrorMessage(axiosErrorWith(500, {}), "取得に失敗しました")).toBe(
      "取得に失敗しました",
    );
    expect(
      toErrorMessage(
        axiosErrorWith(500, { detail: { code: 1 } }),
        "取得に失敗しました",
      ),
    ).toBe("取得に失敗しました");
  });

  it("axios以外のエラーはフォールバック文言をそのまま返す", () => {
    expect(toErrorMessage(new Error("boom"), "取得に失敗しました")).toBe(
      "取得に失敗しました",
    );
    expect(toErrorMessage("boom", "取得に失敗しました")).toBe(
      "取得に失敗しました",
    );
  });
});
