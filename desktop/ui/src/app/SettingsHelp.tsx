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

import { useEffect, useRef, useState } from "react";
import type { FoundationInfo } from "../generated/ipc";
import { Diagnostics } from "./Diagnostics";
import { messages, type Language } from "./messages";
import type { Theme } from "./navigation";
import { PageFeedback } from "./PageFeedback";

export function SettingsHelp({
  language,
  theme,
  host,
  onLanguage,
  onTheme,
  localServerRequest,
}: {
  language: Language;
  theme: Theme;
  host: FoundationInfo | null;
  onLanguage: (language: Language) => void;
  onTheme: (theme: Theme) => void;
  localServerRequest: number;
}) {
  const t = messages[language];
  const localServer = useRef<HTMLHeadingElement>(null);
  const [copyResult, setCopyResult] = useState<"copied" | "copyFailed" | null>(
    null,
  );
  useEffect(() => {
    if (localServerRequest) {
      localServer.current?.scrollIntoView?.({ block: "start" });
      localServer.current?.focus();
    }
  }, [localServerRequest]);
  useEffect(() => setCopyResult(null), [language]);
  const guide = `https://github.com/oceanbase/powercontext/blob/master/desktop/README${language === "zh" ? ".zh" : ""}.md`;
  const support = "https://github.com/oceanbase/powercontext/issues";
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopyResult("copied");
    } catch {
      setCopyResult("copyFailed");
    }
  }
  return (
    <div className="stack settings">
      <section className="card stack">
        <h2>{t.appearance}</h2>
        <div className="setting-row">
          <label htmlFor="language">{t.language}</label>
          <select
            id="language"
            value={language}
            onChange={(event) => onLanguage(event.target.value as Language)}
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
            onChange={(event) => onTheme(event.target.value as Theme)}
          >
            <option value="system">{t.system}</option>
            <option value="light">{t.light}</option>
            <option value="dark">{t.dark}</option>
          </select>
        </div>
      </section>
      <section className="stack" aria-labelledby="local-server-heading">
        <h2 id="local-server-heading" tabIndex={-1} ref={localServer}>
          {t.localServer}
        </h2>
        <PageFeedback kind="unavailable" title={t.localSetupUnavailable}>
          <p>{t.localSetupDescription}</p>
          <p>{t.existingServerHelp}</p>
        </PageFeedback>
      </section>
      <Diagnostics language={language} />
      <section className="card stack">
        <h2>{t.version}</h2>
        <dl>
          <div>
            <dt>{t.version}</dt>
            <dd>{host?.version ?? t.unknown}</dd>
          </div>
          <div>
            <dt>{t.native}</dt>
            <dd>{host ? t.nativeReady : t.unavailable}</dd>
          </div>
        </dl>
        <p>{t.boundary}</p>
      </section>
      <section className="card stack">
        <h2>{t.help}</h2>
        <p>{t.guideDescription}</p>
        <code>{guide}</code>
        <div className="actions">
          <button onClick={() => void copy(guide)}>{t.copyGuide}</button>
        </div>
        <p>{t.supportDescription}</p>
        <code>{support}</code>
        <div className="actions">
          <button onClick={() => void copy(support)}>{t.copySupport}</button>
        </div>
        {copyResult && (
          <p role={copyResult === "copied" ? "status" : "alert"}>
            {t[copyResult]}
          </p>
        )}
      </section>
    </div>
  );
}
