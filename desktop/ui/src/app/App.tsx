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

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { messages, type Language } from "./messages";
import { getFoundationInfo, desktopApi } from "../shared/ipc";
import type { FoundationInfo, DesktopState } from "../generated/ipc";
import logo from "../../../src-tauri/icons/brand.png";
import homeIcon from "../assets/overview.svg";
import connectionsIcon from "../assets/connections.svg";
import memoryIcon from "../assets/memory.svg";
import settingsIcon from "../assets/settings.svg";
import observationIcon from "../assets/retrieval.svg";

import { TopBar } from "./TopBar";
import { Overview } from "./Overview";
import { MemoryWorkspace } from "./MemoryWorkspace";
import { LocalServerSettings } from "./LocalServerSettings";
import { Help } from "./Help";
import { Diagnostics } from "./Diagnostics";
import { Connections } from "./Connections";
import { Scopes } from "./Scopes";
import { Observation, type ObservationTab } from "./Observation";
import { connectionMessages } from "./connection-messages";
import { PageFeedback, ErrorFeedback } from "./PageFeedback";
import { activeCheckReport } from "./context";

type Page = "home" | "connections" | "memories" | "observation" | "settings";
type Theme = "light" | "dark" | "system";
export function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [theme, setTheme] = useState<Theme>("system");
  const [page, setPage] = useState<Page>("home");
  const [observationTab, setObservationTab] =
    useState<ObservationTab>("runtime");
  const [menu, setMenu] = useState(false);
  const [host, setHost] = useState<FoundationInfo | null>(null);
  const [desktop, setDesktop] = useState<DesktopState | null>(null);
  const [nativeError, setNativeError] = useState<unknown>(null);
  const [stateError, setStateError] = useState<unknown>(null);
  const [stateLoading, setStateLoading] = useState(true);
  const stateRequest = useRef(0);
  const [dirty, setDirty] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [pendingConnections, setPendingConnections] = useState(0);
  const contextPending = pendingConnections > 0;
  function connectionPending(pending: boolean) {
    // Pending operations may finish after their editor has unmounted.
    setPendingConnections((current) => current + (pending ? 1 : -1));
  }
  function receiveState(next: DesktopState) {
    setDesktop((current) =>
      !current || next.generation >= current.generation ? next : current,
    );
  }
  function confirmSwitch() {
    return !dirty || window.confirm(connectionMessages[language].discard);
  }
  const activeProfile = desktop?.profiles.find(
    (p) => p.id === desktop.active?.connectionId,
  );
  const activeReport = activeCheckReport(desktop);
  const heading = useRef<HTMLHeadingElement>(null);
  const localServerHeading = useRef<HTMLHeadingElement>(null);
  const settingsSection = useRef<"local-server" | undefined>(undefined);
  const scopeDialog = useRef<HTMLDivElement>(null);
  const scopeReturnFocus = useRef<HTMLElement | null>(null);
  const t = messages[language];
  const ct = connectionMessages[language];
  async function loadState() {
    const request = ++stateRequest.current;
    setStateLoading(true);
    setStateError(null);
    try {
      receiveState(await desktopApi.state());
    } catch (error) {
      if (request === stateRequest.current) setStateError(error);
    } finally {
      if (request === stateRequest.current) setStateLoading(false);
    }
  }
  useEffect(() => {
    void loadState();
    getFoundationInfo()
      .then(setHost)
      .catch(() => setHost(null));
  }, []);
  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  useLayoutEffect(() => {
    const localServer =
      page === "settings" && settingsSection.current === "local-server";
    const target = localServer ? localServerHeading.current : heading.current;
    target?.focus();
    if (localServer) target?.scrollIntoView?.({ block: "start" });
  }, [page]);
  function openScopes() {
    scopeReturnFocus.current = document.activeElement as HTMLElement;
    setScopeOpen(true);
  }
  useEffect(() => {
    if (!scopeOpen) return;
    const previous = scopeReturnFocus.current;
    const dialog = scopeDialog.current;
    const background = Array.from(
      document.querySelector(".app")?.children ?? [],
    ).filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement &&
        !element.classList.contains("modal-backdrop"),
    );
    const inertValues = background.map((element) => element.inert);
    background.forEach((element) => {
      element.inert = true;
    });
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setScopeOpen(false);
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button, input, select, [tabindex="0"]',
        ) ?? [],
      ).filter((element) => !element.matches(":disabled"));
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      background.forEach((element, index) => {
        element.inert = inertValues[index];
      });
      if (scopeReturnFocus.current === null) return;
      if (previous?.isConnected) previous.focus();
      else
        document
          .querySelector<HTMLButtonElement>(".topbar-group button")
          ?.focus();
    };
  }, [scopeOpen]);
  function navigate(next: Page, section?: "local-server") {
    if (next === page || !confirmSwitch()) return;
    settingsSection.current = section;
    setDirty(false);
    setPage(next);
    setMenu(false);
  }
  function disconnect() {
    if (!confirmSwitch()) return;
    connectionPending(true);
    void desktopApi
      .disconnect()
      .then(receiveState)
      .catch(setNativeError)
      .finally(() => connectionPending(false));
  }
  async function refresh() {
    setRefreshing(true);
    setNativeError(null);
    connectionPending(true);
    try {
      receiveState(
        desktop?.active
          ? await desktopApi.check(desktop.active.connectionId, false)
          : await desktopApi.state(),
      );
    } catch (e) {
      setNativeError(e);
    } finally {
      connectionPending(false);
      setRefreshing(false);
    }
  }
  const ready = activeReport?.readiness.value?.status === "ready";
  return (
    <div className="app">
      <a className="skip" href="#main">
        {t.skip}
      </a>
      <header className="mobile-bar">
        <span>PowerContext</span>
        <button
          aria-expanded={menu}
          aria-controls="navigation"
          onClick={() => setMenu(!menu)}
        >
          {t.menu}
        </button>
      </header>
      <aside id="navigation" className={menu ? "sidebar open" : "sidebar"}>
        <div className="brand">
          <img src={logo} alt="" />
          <strong>PowerContext</strong>
          <span className="brand-sub">{t.brandSub}</span>
        </div>
        <span className="brand-badge">{t.foundation}</span>
        <nav aria-label={t.menu}>
          {(["home", "connections", "memories", "observation"] as const).map(
            (item, index) => (
              <button
                key={item}
                aria-current={page === item ? "page" : undefined}
                onClick={() => navigate(item)}
              >
                <img
                  className="nav-symbol"
                  alt=""
                  src={
                    [homeIcon, connectionsIcon, memoryIcon, observationIcon][
                      index
                    ]
                  }
                />
                {t[item]}
              </button>
            ),
          )}
        </nav>
        <div className="sidebar-bottom">
          <button
            aria-current={page === "settings" ? "page" : undefined}
            onClick={() => navigate("settings")}
          >
            <img className="nav-symbol" alt="" src={settingsIcon} />
            {t.settings}
          </button>
          <div className="sidebar-status">
            <p className="status">
              <span aria-hidden="true" className="dot" />
              {activeProfile?.name ??
                (stateLoading
                  ? t.loadingState
                  : desktop
                    ? t.disconnected
                    : t.stateUnavailable)}
            </p>
            <p className="caption">{t.sidebarRunning}</p>
          </div>
        </div>
      </aside>
      <div className="content">
        <TopBar
          state={desktop}
          language={language}
          loading={stateLoading}
          contextPending={contextPending}
          onManageConnections={() => navigate("connections")}
          onOpenScopes={openScopes}
          onDisconnect={disconnect}
        />
        <main id="main">
          <h1 className="sr-only" tabIndex={-1} ref={heading}>
            {t[page]}
          </h1>
          {contextPending && (
            <PageFeedback kind="loading" title={t.connectionUpdating}>
              <p>{t.connectionUpdatingHint}</p>
            </PageFeedback>
          )}
          {stateLoading && (
            <PageFeedback kind="loading" title={t.loadingState} />
          )}
          {!stateLoading && stateError != null && (
            <ErrorFeedback
              error={stateError}
              language={language}
              title={t.stateFailed}
              action={
                <button onClick={() => void loadState()}>{t.retryState}</button>
              }
            />
          )}
          {nativeError != null && (
            <ErrorFeedback
              error={nativeError}
              language={language}
              action={
                <button onClick={() => navigate("connections")}>
                  {t.manageConnections}
                </button>
              }
            />
          )}
          {page === "memories" && desktop?.active && (
            <div className="context-line">
              <span>{activeProfile?.name}</span>
              <span aria-hidden="true">·</span>
              <span>{activeProfile?.endpoint}</span>
              <span aria-hidden="true">·</span>
              <span>{desktop.active.scope?.title ?? t.noScopeSelected}</span>
              {desktop.active.scope && (
                <code>{desktop.active.scope.scope_id}</code>
              )}
              <span className={ready ? "badge success" : "badge subtle"}>
                {ready ? t.serviceReady : t.unverified}
              </span>
            </div>
          )}
          {page === "home" && (
            <Overview
              state={desktop}
              language={language}
              onNavigate={navigate}
              refreshing={refreshing}
              onRefresh={() => void refresh()}
            />
          )}
          {page === "memories" && (
            <MemoryWorkspace
              key={`memory-${desktop?.active?.generation ?? "none"}`}
              state={desktop}
              language={language}
              onState={receiveState}
              onDirty={setDirty}
              onManageConnections={() => navigate("connections")}
              onOpenScopes={openScopes}
              onOpenLocalServer={() => navigate("settings", "local-server")}
              contextPending={contextPending}
            />
          )}
          {page === "connections" && (
            <Connections
              state={desktop}
              language={language}
              onState={receiveState}
              onDirty={setDirty}
              onPendingChange={connectionPending}
            />
          )}
          {page === "observation" && (
            <Observation
              language={language}
              tab={observationTab}
              onTabChange={setObservationTab}
            />
          )}
          {page === "settings" && (
            <div className="stack settings">
              <section className="card">
                <div className="setting-row">
                  <label htmlFor="language">{t.language}</label>
                  <select
                    id="language"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value as Language)}
                  >
                    <option value="zh">简体中文</option>
                    <option value="en">English</option>
                  </select>
                </div>
                <div className="setting-row">
                  <label htmlFor="theme">{t.theme}</label>
                  <select
                    id="theme"
                    value={theme}
                    onChange={(e) => setTheme(e.target.value as Theme)}
                  >
                    <option value="system">{t.system}</option>
                    <option value="light">{t.light}</option>
                    <option value="dark">{t.dark}</option>
                  </select>
                </div>
              </section>
              <LocalServerSettings
                language={language}
                headingRef={localServerHeading}
                onManageConnections={() => navigate("connections")}
              />
              <Help language={language} />
              <Diagnostics language={language} />
              <section className="card">
                <h2>{t.version}</h2>
                <dl>
                  <div>
                    <dt>{t.version}</dt>
                    <dd>{host?.version ?? t.unknown}</dd>
                  </div>
                  <div>
                    <dt>{t.native}</dt>
                    <dd role="status">
                      {host ? t.nativeReady : t.unavailable}
                    </dd>
                  </div>
                </dl>
                <p>{t.boundary}</p>
              </section>
            </div>
          )}
        </main>
      </div>
      {scopeOpen && (
        <div
          className="modal-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) setScopeOpen(false);
          }}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={ct.scope}
            ref={scopeDialog}
          >
            <div className="modal-heading">
              <h2>{ct.scope}</h2>
              <button onClick={() => setScopeOpen(false)}>
                {t.closeDialog}
              </button>
            </div>
            <Scopes
              key={`scopes-${desktop?.active?.generation ?? "none"}`}
              state={desktop}
              language={language}
              onState={receiveState}
              confirmSwitch={confirmSwitch}
              onSelected={() => {
                setDirty(false);
                setScopeOpen(false);
              }}
              hideHeading
              onManageConnections={() => {
                scopeReturnFocus.current = null;
                setScopeOpen(false);
                navigate("connections");
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
