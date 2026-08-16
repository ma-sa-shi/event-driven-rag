import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// globalsを注入しない設定では、RTLの自動cleanupが働かない為ここで登録する
afterEach(cleanup);
