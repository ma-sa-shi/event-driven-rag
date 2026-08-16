import { describe, expect, it } from "vitest";
import { contentTypeFor } from "../../src/lib/fileTypes";

describe("contentTypeFor", () => {
  it("署名に使うContent-Typeを拡張子から決める", () => {
    expect(contentTypeFor("manual.pdf")).toBe("application/pdf");
    expect(contentTypeFor("readme.md")).toBe("text/plain; charset=utf-8");
  });

  it("拡張子の大文字小文字を区別しない", () => {
    expect(contentTypeFor("MANUAL.PDF")).toBe("application/pdf");
    expect(contentTypeFor("Readme.Md")).toBe("text/plain; charset=utf-8");
  });

  it("非対応の拡張子と拡張子なしはnullを返す", () => {
    expect(contentTypeFor("archive.zip")).toBeNull();
    expect(contentTypeFor("archive.tar.gz")).toBeNull();
    expect(contentTypeFor("README")).toBeNull();
    expect(contentTypeFor("trailing.")).toBeNull();
  });
});
