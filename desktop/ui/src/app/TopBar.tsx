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

import { useEffect, useId, useRef, useState } from "react";
import type { DesktopState } from "../generated/ipc";
import { messages, type Language } from "./messages";
import { connectionMessages } from "./connection-messages";

type Props = {
  state: DesktopState | null;
  language: Language;
  onManageConnections: (connectionId?: string) => void;
  onOpenScopes: () => void;
  onDisconnect: () => void;
};
export function TopBar({
  state,
  language,
  onManageConnections,
  onOpenScopes,
  onDisconnect,
}: Props) {
  const t = messages[language];
  const ct = connectionMessages[language];
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const connectionWrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const firstItem = useRef(0);
  const menuId = useId();
  useEffect(() => {
    const bar = wrap.current;
    if (!bar) return;
    const update = () =>
      document.documentElement.style.setProperty(
        "--topbar-height",
        `${bar.getBoundingClientRect().height}px`,
      );
    update();
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(bar);
    return () => {
      observer?.disconnect();
      document.documentElement.style.removeProperty("--topbar-height");
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    const items =
      menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
    items?.[firstItem.current === -1 ? items.length - 1 : 0]?.focus();
    function onPointerDown(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !connectionWrap.current?.contains(event.target)
      )
        setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);
  const active = state?.active;
  const activeProfile = state?.profiles.find(
    (profile) => profile.id === active?.connectionId,
  );
  const latest = state?.reports.find(
    (report) =>
      report.connectionId === active?.connectionId &&
      report.revision === active?.report.revision,
  );
  const report =
    latest && active && latest.checkedAt >= active.report.checkedAt
      ? latest
      : active?.report;
  const principal = report?.anonymousAccess
    ? null
    : report?.identity.value?.principal;
  const identityText = !active
    ? t.unverified
    : report?.anonymousAccess
      ? t.anonymousIdentity
      : principal
        ? (principal.description ?? `${principal.type}: ${principal.id}`)
        : t.identityUnverified;
  function closeMenu() {
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <div className="topbar" ref={wrap}>
      <div className="menu-wrap" ref={connectionWrap}>
        <button
          className="menu-trigger"
          aria-expanded={open}
          aria-haspopup="menu"
          aria-controls={menuId}
          ref={trigger}
          aria-label={`${t.current}: ${activeProfile?.name ?? (state ? t.notConnected : t.unverified)}`}
          onClick={() => {
            firstItem.current = 0;
            setOpen(!open);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              firstItem.current = event.key === "ArrowUp" ? -1 : 0;
              setOpen(true);
            }
          }}
        >
          <span className="label">
            {activeProfile?.name ?? (state ? t.notConnected : t.unverified)}
          </span>
          <span aria-hidden="true">▾</span>
        </button>
        {open && (
          <div
            className="menu"
            id={menuId}
            role="menu"
            aria-label={t.manageConnections}
            ref={menu}
            onBlur={(event) => {
              if (
                event.relatedTarget instanceof Node &&
                !connectionWrap.current?.contains(event.relatedTarget)
              )
                setOpen(false);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                closeMenu();
                return;
              }
              if (event.key === "Tab") {
                setOpen(false);
                return;
              }
              const items = Array.from(
                menu.current?.querySelectorAll<HTMLButtonElement>(
                  '[role="menuitem"]',
                ) ?? [],
              );
              const index = items.indexOf(
                document.activeElement as HTMLButtonElement,
              );
              let next: number;
              if (event.key === "ArrowDown") next = (index + 1) % items.length;
              else if (event.key === "ArrowUp")
                next = (index + items.length - 1) % items.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = items.length - 1;
              else return;
              event.preventDefault();
              items[next]?.focus();
            }}
          >
            {state?.profiles.map((profile) => (
              <button
                key={profile.id}
                className="menu-item"
                role="menuitem"
                tabIndex={-1}
                onClick={() => {
                  closeMenu();
                  onManageConnections(profile.id);
                }}
              >
                <span>
                  {profile.name}
                  {active?.connectionId === profile.id
                    ? ` · ${ct.activeBadge}`
                    : ""}
                </span>
                <span className="meta">{profile.endpoint}</span>
              </button>
            ))}
            <button
              className="menu-item"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                closeMenu();
                onManageConnections();
              }}
            >
              {t.manageConnections}
            </button>
            {active && (
              <button
                className="menu-item"
                role="menuitem"
                tabIndex={-1}
                onClick={() => {
                  closeMenu();
                  onDisconnect();
                }}
              >
                {ct.disconnect}
              </button>
            )}
            <p className="menu-note">{t.switchHint}</p>
          </div>
        )}
      </div>
      <span className="status-pill">
        {active ? t.connected : state ? t.notConnected : t.unverified}
      </span>
      <div className="topbar-group">
        <span className="topbar-label">{t.scopeLabel}</span>
        <button
          className="menu-trigger"
          disabled={!active}
          onClick={onOpenScopes}
          aria-haspopup="dialog"
        >
          <span>{active?.scope?.title ?? t.noScopeSelected}</span>
          <span aria-hidden="true">▾</span>
        </button>
      </div>
      <div className="global-context">
        {activeProfile && (
          <p className="context-endpoint">{activeProfile.endpoint}</p>
        )}
        {active?.scope && (
          <p>
            <span>{t.exactScope}: </span>
            <code>{active.scope.scope_id}</code>
          </p>
        )}
        {active && (
          <dl className="context-facts">
            <div>
              <dt>{t.identityLabel}</dt>
              <dd>{identityText}</dd>
            </div>
            <div>
              <dt>{t.compatibility}</dt>
              <dd>
                {report?.compatibilityVerified
                  ? t.compatibilityVerified
                  : t.unverified}
              </dd>
            </div>
            <div>
              <dt>{t.liveness}</dt>
              <dd>{report?.liveness.value?.status ?? t.unverified}</dd>
            </div>
            <div>
              <dt>{t.readiness}</dt>
              <dd>
                {report?.readiness.value?.status === "ready"
                  ? t.serviceReady
                  : report?.readiness.value
                    ? t.serviceNotReady
                    : t.unverified}
              </dd>
            </div>
          </dl>
        )}
        {report && (
          <p className="small">
            {t.lastChecked}:{" "}
            {new Date(report.checkedAt * 1000).toLocaleString(
              language === "zh" ? "zh-CN" : "en-US",
            )}
            . {t.readinessNote}
          </p>
        )}
      </div>
      {active && (
        <details className="identity-details" key={active.generation}>
          <summary>{t.identityDetails}</summary>
          {principal ? (
            <p>
              {principal.type}: {principal.id} · {t.accessMode}:{" "}
              {report?.identity.value?.mode ?? t.unverified}
            </p>
          ) : (
            <p>
              {report?.anonymousAccess ? ct.noIdentity : t.identityUnverified}
            </p>
          )}
        </details>
      )}
    </div>
  );
}
