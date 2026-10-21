/*
 * Copyright (c) 2026 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/app/App";
import { TopBar } from "../src/app/TopBar";
import { Observation } from "../src/app/Observation";
import { SettingsHelp } from "../src/app/SettingsHelp";
import { MemoryWorkspace } from "../src/app/MemoryWorkspace";
import { desktopApi, getFoundationInfo } from "../src/shared/ipc";
import type { DesktopState, ProfileView } from "../src/generated/ipc";

vi.mock("../src/shared/ipc", () => ({
  getFoundationInfo: vi.fn(),
  desktopApi: {
    state: vi.fn(),
    save: vi.fn(),
    check: vi.fn(),
    disconnect: vi.fn(),
    scopes: vi.fn(),
    selectScope: vi.fn(),
    cancelScopes: vi.fn(),
    cancelMemory: vi.fn(),
    remember: vi.fn(),
    search: vi.fn(),
    atomicEntry: vi.fn(),
    diagnostics: vi.fn(),
  },
}));
const firstProfile: ProfileView = {
  id: "connection-a",
  revision: 1,
  name: "First",
  endpoint: "http://127.0.0.1:8000/",
  authentication: "unauthenticated_loopback",
  caPem: null,
  compatibility: null,
  credentialState: "not_required",
};
const secondProfile = {
  ...firstProfile,
  id: "connection-b",
  name: "Second",
  endpoint: "http://127.0.0.1:9000/",
};
const disconnected: DesktopState = {
  generation: 0,
  profiles: [firstProfile, secondProfile],
  reports: [],
  active: null,
  compatibilityProfiles: [],
  pendingCredentialCleanup: 0,
  lastWrite: null,
};
const fact = { value: null, error: null };
const report = {
  connectionId: firstProfile.id,
  revision: 1,
  checkedAt: 1,
  liveness: fact,
  readiness: fact,
  identity: fact,
  capabilities: fact,
  compatibilityVerified: true,
  anonymousAccess: true,
  supportedOperations: [],
};
const scope = {
  scope_id: "scope-a",
  title: "Same scope title",
  summary: "",
  context_references: [],
  external_references: [],
  version: 1,
};
const connected: DesktopState = {
  ...disconnected,
  generation: 1,
  active: { connectionId: firstProfile.id, generation: 1, report, scope },
};
const nav = (name: string) =>
  within(screen.getByRole("navigation")).getByRole("button", {
    name,
  });
const connectionTrigger = () =>
  screen.getByRole("button", { name: /^当前连接:/ });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getFoundationInfo).mockResolvedValue(null);
  vi.mocked(desktopApi.state).mockResolvedValue(disconnected);
  vi.mocked(desktopApi.cancelMemory).mockResolvedValue(undefined);
  vi.mocked(desktopApi.cancelScopes).mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("four entries expose both first-use paths and retain disabled disconnected Memory operations", async () => {
  const user = userEvent.setup();
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "尚未连接服务" }),
  ).toBeTruthy();
  expect(
    within(screen.getByRole("navigation"))
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(["记忆", "连接", "观察", "设置与帮助"]);
  expect(screen.getByRole("heading", { level: 1, name: "记忆" })).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "保存" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    (screen.getByRole("button", { name: "搜索" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  await user.click(screen.getByRole("button", { name: "本地设置" }));
  const local = screen.getByRole("heading", { name: "本地 Server" });
  await waitFor(() => expect(document.activeElement).toBe(local));
  expect(screen.getByText("本地安装与服务管理尚未可用")).toBeTruthy();
  expect(desktopApi.check).not.toHaveBeenCalled();
  expect(desktopApi.diagnostics).not.toHaveBeenCalled();
  await user.click(nav("记忆"));
  await user.click(screen.getByRole("button", { name: "连接已有服务" }));
  expect(screen.getByRole("heading", { name: "添加连接" })).toBeTruthy();
});

test("loading, failed initialization and a successful disconnected retry have distinct presentation", async () => {
  const user = userEvent.setup();
  let reject!: (reason: unknown) => void;
  vi.mocked(desktopApi.state).mockImplementationOnce(
    () =>
      new Promise((_, fail) => {
        reject = fail;
      }),
  );
  render(<App />);
  expect(screen.getByRole("status").textContent).toBe("正在加载 Desktop 状态…");
  expect(screen.queryByRole("button", { name: "本地设置" })).toBeNull();
  await act(async () => reject({ code: "storage" }));
  expect(screen.getByRole("alert").textContent).toContain(
    "无法加载 Desktop 状态",
  );
  expect(screen.queryByRole("button", { name: "本地设置" })).toBeNull();
  await user.click(nav("设置与帮助"));
  expect(screen.getByRole("heading", { name: "本地 Server" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "重试加载" }));
  await user.click(nav("记忆"));
  expect(await screen.findByRole("button", { name: "本地设置" })).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("settings, bilingual navigation and theme work without the native host and never invent a version", async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(nav("设置与帮助"));
  await user.selectOptions(screen.getByLabelText("语言"), "en");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "Settings & help",
  );
  expect(screen.getByRole("heading", { name: "Local Server" })).toBeTruthy();
  expect(screen.queryByText("0.1.0")).toBeNull();
  expect(screen.getByText("Unknown")).toBeTruthy();
  await user.selectOptions(screen.getByLabelText("Theme"), "dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(document.documentElement.lang).toBe("en");
  await user.selectOptions(screen.getByLabelText("Theme"), "light");
  expect(document.documentElement.dataset.theme).toBe("light");
  await user.selectOptions(screen.getByLabelText("Theme"), "system");
  expect(document.documentElement.dataset.theme).toBe("system");
  await user.click(nav("Memories"));
  expect(
    screen.getByText("Enter keywords to find existing memories."),
  ).toBeTruthy();
});

test("Observation has three keyboard-accessible unavailable panels without automatic checks", async () => {
  const user = userEvent.setup();
  vi.mocked(desktopApi.state).mockResolvedValue(connected);
  render(<App />);
  await user.click(nav("观察"));
  const runtime = screen.getByRole("tab", { name: "运行状态" });
  await user.click(runtime);
  await user.keyboard("{ArrowRight}");
  expect(document.activeElement).toBe(
    screen.getByRole("tab", { name: "当前 Scope 库存与用量" }),
  );
  expect(screen.getByRole("tabpanel").textContent).toContain(
    "未知值不表示为零",
  );
  await user.keyboard("{End}");
  expect(screen.getByRole("tabpanel").textContent).toContain(
    "安全诊断摘要复制",
  );
  await user.keyboard("{Home}{ArrowLeft}");
  expect(document.activeElement).toBe(
    screen.getByRole("tab", { name: "本次会话" }),
  );
  expect(screen.getAllByRole("tab")).toHaveLength(3);
  expect(desktopApi.check).not.toHaveBeenCalled();
  expect(desktopApi.diagnostics).not.toHaveBeenCalled();
  expect(desktopApi.search).not.toHaveBeenCalled();
});

test("each observation panel accepts its owning feature's content", () => {
  render(
    <Observation
      language="en"
      tab="inventory"
      onTabChange={vi.fn()}
      panels={{ inventory: <p>Exact Scope inventory supplied by its owner</p> }}
    />,
  );
  expect(screen.getByRole("tabpanel").textContent).toBe(
    "Exact Scope inventory supplied by its owner",
  );
  expect(
    screen.queryByText("This observation view is not available yet"),
  ).toBeNull();
});

test("a saved connection menu item opens that configuration without activating it", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: "本地设置" });
  await user.click(connectionTrigger());
  await user.click(screen.getByRole("menuitem", { name: /Second/ }));
  expect((screen.getByLabelText("连接名称") as HTMLInputElement).value).toBe(
    "Second",
  );
  expect(desktopApi.check).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { level: 1, name: "连接" }),
    ),
  );
});

test("canceling external connection selection keeps the editor and its draft intact", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: "本地设置" });
  await user.click(connectionTrigger());
  await user.click(screen.getByRole("menuitem", { name: /First/ }));
  await user.type(screen.getByLabelText("连接名称"), " draft");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(connectionTrigger());
  await user.click(screen.getByRole("menuitem", { name: /Second/ }));
  expect(confirm).toHaveBeenCalled();
  expect((screen.getByLabelText("连接名称") as HTMLInputElement).value).toBe(
    "First draft",
  );
  confirm.mockReturnValue(true);
  await user.click(connectionTrigger());
  await user.click(screen.getByRole("menuitem", { name: /Second/ }));
  expect((screen.getByLabelText("连接名称") as HTMLInputElement).value).toBe(
    "Second",
  );
  expect(desktopApi.check).not.toHaveBeenCalled();
});

test("connection menu supports arrows, Home, End, Escape and focus return", async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", { name: "本地设置" });
  connectionTrigger().focus();
  await user.keyboard("{ArrowDown}");
  expect(document.activeElement).toBe(
    screen.getByRole("menuitem", { name: /First/ }),
  );
  await user.keyboard("{ArrowDown}");
  expect(document.activeElement).toBe(
    screen.getByRole("menuitem", { name: /Second/ }),
  );
  await user.keyboard("{End}");
  expect(document.activeElement).toBe(
    screen.getByRole("menuitem", { name: "管理连接" }),
  );
  await user.keyboard("{Home}{ArrowUp}");
  expect(document.activeElement).toBe(
    screen.getByRole("menuitem", { name: "管理连接" }),
  );
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).toBeNull();
  expect(document.activeElement).toBe(connectionTrigger());
  await user.keyboard("{ArrowUp}");
  expect(document.activeElement).toBe(
    screen.getByRole("menuitem", { name: "管理连接" }),
  );
});

test("a late save cannot replace an externally selected connection's new draft", async () => {
  const user = userEvent.setup();
  let finish!: (state: DesktopState) => void;
  vi.mocked(desktopApi.save).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  await screen.findByRole("button", { name: "本地设置" });
  await user.click(connectionTrigger());
  await user.click(screen.getByRole("menuitem", { name: /First/ }));
  await user.type(screen.getByLabelText("连接名称"), " saved");
  await user.click(screen.getByRole("button", { name: "保存配置" }));
  await user.click(connectionTrigger());
  await user.click(screen.getByRole("menuitem", { name: /Second/ }));
  await act(async () =>
    finish({
      ...disconnected,
      profiles: [
        { ...firstProfile, revision: 2, name: "First saved" },
        secondProfile,
      ],
    }),
  );
  expect((screen.getByLabelText("连接名称") as HTMLInputElement).value).toBe(
    "Second",
  );
  await user.type(screen.getByLabelText("连接名称"), " draft");
  vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(nav("观察"));
  expect((screen.getByLabelText("连接名称") as HTMLInputElement).value).toBe(
    "Second draft",
  );
});

test("a failed disconnect preserves the draft's navigation protection", async () => {
  const user = userEvent.setup();
  vi.mocked(desktopApi.state).mockResolvedValue(connected);
  vi.mocked(desktopApi.disconnect).mockRejectedValue({ code: "storage" });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  await screen.findByRole("button", { name: scope.title });
  await user.type(screen.getByLabelText("记忆内容"), "unsaved");
  await user.click(connectionTrigger());
  await user.click(screen.getByRole("menuitem", { name: "断开桌面连接" }));
  await screen.findByRole("alert");
  confirm.mockClear().mockReturnValue(false);
  await user.click(nav("观察"));
  expect(confirm).toHaveBeenCalled();
  expect((screen.getByLabelText("记忆内容") as HTMLTextAreaElement).value).toBe(
    "unsaved",
  );
});

test("scope dialog traps focus and returns it to its trigger without losing a draft", async () => {
  const user = userEvent.setup();
  vi.mocked(desktopApi.state).mockResolvedValue(connected);
  render(<App />);
  await screen.findByRole("button", { name: "Same scope title" });
  const text = screen.getByLabelText("记忆内容");
  await user.type(text, "keep this draft");
  const trigger = screen.getByRole("button", { name: "Same scope title" });
  await user.click(trigger);
  const dialog = screen.getByRole("dialog");
  const close = within(dialog).getByRole("button", { name: "关闭" });
  expect(document.activeElement).toBe(close);
  expect((document.querySelector(".app-background") as HTMLElement).inert).toBe(
    true,
  );
  await user.keyboard("{Shift>}{Tab}{/Shift}");
  expect(document.activeElement).toBe(
    within(dialog).getByRole("button", { name: "查找范围" }),
  );
  await user.keyboard("{Tab}");
  expect(document.activeElement).toBe(close);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect((text as HTMLTextAreaElement).value).toBe("keep this draft");
});

test("global context distinguishes identical Scope titles by exact ID on every page", async () => {
  const user = userEvent.setup();
  const next = {
    ...connected,
    generation: 2,
    active: {
      ...connected.active!,
      generation: 2,
      scope: { ...scope, scope_id: "scope-b" },
    },
  };
  vi.mocked(desktopApi.state).mockResolvedValue(connected);
  vi.mocked(desktopApi.scopes).mockResolvedValue({
    items: [next.active.scope],
  });
  vi.mocked(desktopApi.selectScope).mockResolvedValue(next);
  render(<App />);
  await screen.findByRole("button", { name: scope.title });
  const context = document.querySelector(".global-context") as HTMLElement;
  expect(within(context).getByText("scope-a")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: scope.title }));
  await user.click(screen.getByRole("button", { name: "查找范围" }));
  await user.click(
    await within(screen.getByRole("dialog")).findByRole("button", {
      name: scope.title,
    }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  for (const page of ["连接", "观察", "设置与帮助", "记忆"]) {
    await user.click(nav(page));
    expect(within(context).getByText("scope-b")).toBeTruthy();
    expect(within(context).queryByText("scope-a")).toBeNull();
  }
});

test("connected Memory without an exact Scope offers the existing selector", async () => {
  const user = userEvent.setup();
  vi.mocked(desktopApi.state).mockResolvedValue({
    ...connected,
    active: { ...connected.active!, scope: null },
  });
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "选择范围" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
});

test("health does not turn unverified compatibility or identity into authorization", () => {
  const state = {
    ...connected,
    active: {
      ...connected.active!,
      report: {
        ...report,
        anonymousAccess: false,
        compatibilityVerified: false,
        readiness: {
          value: { status: "ready" as const, checks: {} },
          error: null,
        },
      },
    },
  };
  render(
    <TopBar
      state={state}
      language="en"
      onManageConnections={vi.fn()}
      onOpenScopes={vi.fn()}
      onDisconnect={vi.fn()}
    />,
  );
  expect(screen.getByText("Service ready")).toBeTruthy();
  expect(
    within(document.querySelector(".global-context") as HTMLElement).getByText(
      "Identity not verified yet",
    ),
  ).toBeTruthy();
  const compatibility = screen.getByText("Compatibility").closest("div")!;
  expect(within(compatibility).getByText("Not verified")).toBeTruthy();
  expect(
    screen.getByText(
      /Readiness and operation permissions are verified separately/,
    ),
  ).toBeTruthy();
});

test("help copies fixed locale-specific documentation and support links with failure feedback", async () => {
  const user = userEvent.setup();
  const clipboard = vi
    .spyOn(navigator.clipboard, "writeText")
    .mockResolvedValue(undefined);
  render(<App />);
  await user.click(nav("设置与帮助"));
  await user.click(screen.getByRole("button", { name: "复制使用指南链接" }));
  expect(clipboard).toHaveBeenLastCalledWith(
    "https://github.com/oceanbase/powercontext/blob/master/desktop/README.zh.md",
  );
  expect(screen.getByText("链接已复制。")).toBeTruthy();
  await user.selectOptions(screen.getByLabelText("语言"), "en");
  await user.click(
    screen.getByRole("button", { name: "Copy usage guide link" }),
  );
  expect(clipboard).toHaveBeenLastCalledWith(
    "https://github.com/oceanbase/powercontext/blob/master/desktop/README.md",
  );
  clipboard.mockRejectedValueOnce(new Error("clipboard denied"));
  await user.click(screen.getByRole("button", { name: "Copy support link" }));
  expect(clipboard).toHaveBeenLastCalledWith(
    "https://github.com/oceanbase/powercontext/issues",
  );
  expect(screen.getByRole("alert").textContent).toMatch(/Could not copy/);
});

test("appearance changes retain diagnostic results and use the actual native version", async () => {
  const user = userEvent.setup();
  vi.mocked(getFoundationInfo).mockResolvedValue({
    version: "9.8.7",
    phase: "preview",
    credentialBackend: "test",
    serverConnected: false,
  });
  vi.mocked(desktopApi.diagnostics).mockResolvedValue({
    checkedAt: 1,
    exitCode: 0,
    cliVersion: "synthetic-cli",
    items: [],
    hosts: [],
  });
  render(<App />);
  await user.click(nav("设置与帮助"));
  await user.click(screen.getByRole("button", { name: "检查本机服务" }));
  expect(await screen.findByText("CLI 版本: synthetic-cli")).toBeTruthy();
  await user.selectOptions(screen.getByLabelText("语言"), "en");
  await user.selectOptions(screen.getByLabelText("Theme"), "dark");
  expect(screen.getByText("CLI version: synthetic-cli")).toBeTruthy();
  expect(screen.getByText("9.8.7")).toBeTruthy();
});

test("language and theme presentation changes preserve Memory's draft", async () => {
  const user = userEvent.setup();
  const props = { state: connected, onState: vi.fn(), onDirty: vi.fn() };
  const { rerender } = render(<MemoryWorkspace {...props} language="zh" />);
  await user.type(screen.getByLabelText("记忆内容"), "unsaved draft");
  document.documentElement.dataset.theme = "dark";
  rerender(<MemoryWorkspace {...props} language="en" />);
  expect(
    (screen.getByLabelText("Memory text") as HTMLTextAreaElement).value,
  ).toBe("unsaved draft");
});

test("Local Server navigation can be requested repeatedly without changing its availability", async () => {
  const props = {
    language: "en" as const,
    theme: "system" as const,
    host: null,
    onLanguage: vi.fn(),
    onTheme: vi.fn(),
  };
  const { rerender } = render(
    <SettingsHelp {...props} localServerRequest={1} />,
  );
  expect(document.activeElement).toBe(
    screen.getByRole("heading", { name: "Local Server" }),
  );
  screen.getByRole("button", { name: "Copy usage guide link" }).focus();
  rerender(<SettingsHelp {...props} localServerRequest={2} />);
  expect(document.activeElement).toBe(
    screen.getByRole("heading", { name: "Local Server" }),
  );
  expect(
    screen.getByText(
      "Local installation and service management are not available yet",
    ),
  ).toBeTruthy();
});
