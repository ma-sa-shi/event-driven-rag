import type { InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";

const getUser = vi.fn();
vi.mock("../../src/auth/userManager", () => ({
  userManager: { getUser: () => getUser() },
}));

/** インターセプタは戻り値の関数ではない為、送信直前のconfigをアダプタで捕まえる。 */
function captureRequestConfig() {
  let captured: InternalAxiosRequestConfig | undefined;
  api.defaults.adapter = (config) => {
    captured = config;
    return Promise.resolve({
      data: {},
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    });
  };
  return () => captured;
}

beforeEach(() => {
  getUser.mockReset();
});

afterEach(() => {
  delete api.defaults.adapter;
});

describe("apiのリクエストインターセプタ", () => {
  it("アクセストークンをAuthorizationヘッダーへ載せる", async () => {
    getUser.mockResolvedValue({ access_token: "token-abc" });
    const config = captureRequestConfig();

    await api.get("/documents");

    expect(config()?.headers.Authorization).toBe("Bearer token-abc");
  });

  it("サインインしていなければヘッダーを付けない", async () => {
    getUser.mockResolvedValue(null);
    const config = captureRequestConfig();

    await api.get("/documents");

    expect(config()?.headers.Authorization).toBeUndefined();
  });

  it("baseURLに/apiを使う", async () => {
    getUser.mockResolvedValue(null);
    const config = captureRequestConfig();

    await api.get("/documents");

    expect(config()?.baseURL).toBe("/api");
  });
});
