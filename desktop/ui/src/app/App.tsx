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
import observationIcon from "../assets/overview.svg";
import connectionsIcon from "../assets/connections.svg";
import memoryIcon from "../assets/memory.svg";
import settingsIcon from "../assets/settings.svg";
import { TopBar } from "./TopBar";
import { MemoryWorkspace } from "./MemoryWorkspace";
import { Connections } from "./Connections";
import { Scopes } from "./Scopes";
import { Observation } from "./Observation";
import { SettingsHelp } from "./SettingsHelp";
import { PageFeedback } from "./PageFeedback";
import type {
  NavigationTarget,
  ObservationTab,
  Page,
  Theme,
} from "./navigation";
import { connectionMessages, connectionError } from "./connection-messages";

export function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [theme, setTheme] = useState<Theme>("system");
  const [page, setPage] = useState<Page>("memories");
  const [tab, setTab] = useState<ObservationTab>("runtime");
  const [connectionSelection, setConnectionSelection] = useState({
    id: null as string | null,
    request: 0,
  });
  const [localServerRequest, setLocalServerRequest] = useState(0);
  const [menu, setMenu] = useState(false);
  const [host, setHost] = useState<FoundationInfo | null>(null);
  const [desktop, setDesktop] = useState<DesktopState | null>(null);
  const [nativeError, setNativeError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const scopeDialog = useRef<HTMLDivElement>(null);
  const scopeReturnFocus = useRef<HTMLElement | null>(null);
  const t = messages[language];
  const ct = connectionMessages[language];
  function receiveState(next: DesktopState) {
    setDesktop((current) =>
      !current || next.generation >= current.generation ? next : current,
    );
  }
  function confirmSwitch() {
    return !dirty || window.confirm(ct.discard);
  }
  async function loadState() {
    setLoading(true);
    setNativeError(null);
    try {
      receiveState(await desktopApi.state());
    } catch (error) {
      setNativeError(error);
    } finally {
      setLoading(false);
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
    heading.current?.focus();
  }, [page]);
  useEffect(() => {
    if (!scopeOpen) return;
    const previous = scopeReturnFocus.current;
    const dialog = scopeDialog.current;
    const background = document.querySelector<HTMLElement>(".app-background");
    if (background) background.inert = true;
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setScopeOpen(false);
      }
      if (event.key !== "Tab") return;
      const elements = Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]',
        ) ?? [],
      ).filter((element) => !element.matches(":disabled"));
      const first = elements[0];
      const last = elements[elements.length - 1];
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
      if (background) background.inert = false;
      if (previous?.isConnected) previous.focus();
      else
        document
          .querySelector<HTMLButtonElement>(".topbar-group button")
          ?.focus();
    };
  }, [scopeOpen]);
  function navigate(target: NavigationTarget) {
    const samePage = target.page === page;
    if (samePage && !(target.page === "connections" && target.connectionId)) {
      if (target.page === "observation" && target.tab) setTab(target.tab);
      if (target.page === "settings" && target.section)
        setLocalServerRequest((value) => value + 1);
      setMenu(false);
      if (!(target.page === "settings" && target.section))
        heading.current?.focus();
      return;
    }
    if (!confirmSwitch()) return;
    setDirty(false);
    if (target.page === "connections")
      setConnectionSelection((current) => ({
        id: target.connectionId ?? null,
        request: current.request + 1,
      }));
    if (target.page === "observation" && target.tab) setTab(target.tab);
    if (target.page === "settings")
      setLocalServerRequest((value) => (target.section ? value + 1 : 0));
    setPage(target.page);
    setMenu(false);
    if (samePage) heading.current?.focus();
  }
  function disconnect() {
    if (!confirmSwitch()) return;
    void desktopApi.disconnect().then(receiveState).catch(setNativeError);
  }
  const activeProfile = desktop?.profiles.find(
    (profile) => profile.id === desktop.active?.connectionId,
  );
  return (
    <div className="app-root">
      <div className="app app-background">
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
            {(
              ["memories", "connections", "observation", "settings"] as const
            ).map((item, index) => (
              <button
                key={item}
                aria-current={page === item ? "page" : undefined}
                onClick={() => navigate({ page: item })}
              >
                <img
                  className="nav-symbol"
                  alt=""
                  src={
                    [
                      memoryIcon,
                      connectionsIcon,
                      observationIcon,
                      settingsIcon,
                    ][index]
                  }
                />
                {t[item]}
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <p className="status">
              {activeProfile?.name ??
                (loading
                  ? t.loading
                  : desktop
                    ? t.disconnected
                    : t.unavailable)}
            </p>
            <p className="caption">{t.sidebarRunning}</p>
          </div>
        </aside>
        <div className="content">
          <TopBar
            state={desktop}
            language={language}
            onManageConnections={(connectionId) =>
              navigate({ page: "connections", connectionId })
            }
            onOpenScopes={() => {
              scopeReturnFocus.current = document.activeElement as HTMLElement;
              setScopeOpen(true);
            }}
            onDisconnect={disconnect}
          />
          <main id="main">
            <h1 tabIndex={-1} ref={heading}>
              {t[page]}
            </h1>
            {loading && <PageFeedback kind="loading" title={t.loading} />}
            {!loading && nativeError != null && (
              <PageFeedback
                kind="error"
                title={desktop ? t.desktopError : t.stateFailed}
                action={
                  <button onClick={() => void loadState()}>
                    {t.retryState}
                  </button>
                }
              >
                <p>{connectionError(nativeError, language)}</p>
              </PageFeedback>
            )}
            {page === "memories" && (
              <div className="stack">
                {!loading && desktop && !desktop.active && (
                  <PageFeedback
                    kind="empty"
                    title={t.noActiveTitle}
                    action={
                      <>
                        <button
                          onClick={() =>
                            navigate({
                              page: "settings",
                              section: "local-server",
                            })
                          }
                        >
                          {t.setUpLocally}
                        </button>
                        <button
                          className="primary"
                          onClick={() => navigate({ page: "connections" })}
                        >
                          {t.connect}
                        </button>
                      </>
                    }
                  >
                    <p>{t.firstUseDescription}</p>
                  </PageFeedback>
                )}
                {desktop?.active && !desktop.active.scope && (
                  <PageFeedback
                    kind="empty"
                    title={t.noScopeSelected}
                    action={
                      <button
                        onClick={() => {
                          scopeReturnFocus.current =
                            document.activeElement as HTMLElement;
                          setScopeOpen(true);
                        }}
                      >
                        {t.chooseScope}
                      </button>
                    }
                  >
                    <p>{t.selectScopeDescription}</p>
                  </PageFeedback>
                )}
                <MemoryWorkspace
                  key={`memory-${desktop?.active?.generation ?? "none"}`}
                  state={desktop}
                  language={language}
                  onState={receiveState}
                  onDirty={setDirty}
                />
              </div>
            )}
            {page === "connections" && (
              <Connections
                state={desktop}
                language={language}
                onState={receiveState}
                onDirty={setDirty}
                selection={connectionSelection}
              />
            )}
            {page === "observation" && (
              <Observation language={language} tab={tab} onTabChange={setTab} />
            )}
            {page === "settings" && (
              <SettingsHelp
                language={language}
                theme={theme}
                host={host}
                onLanguage={setLanguage}
                onTheme={setTheme}
                localServerRequest={localServerRequest}
              />
            )}
          </main>
        </div>
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
            />
          </div>
        </div>
      )}
    </div>
  );
}
