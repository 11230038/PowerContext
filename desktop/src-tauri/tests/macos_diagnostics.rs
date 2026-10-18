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

#![cfg(target_os = "macos")]

use powercontext_desktop::{
    diagnostics::{DiagnosticKind, LocalDiagnostics},
    error::SafeError,
};
use sha2::{Digest, Sha256};

#[tokio::test]
async fn registered_launcher_is_verified_and_projected_without_private_output() {
    let directory = tempfile::tempdir().unwrap();
    let executable = directory.path().join("powercontext");
    // A real subprocess with the public CLI protocol. It needs no Server or user data.
    std::fs::write(&executable, r##"#!/bin/sh
if [ "$1" = "--version" ]; then
    printf '1.3.0\n'
else
    printf '%s\n' '{"support":"supported","registration":"not_installed","definition":"unknown","manager_ownership":"unknown","manager":"unknown","server_liveness":"unknown","private":"must-not-reach-IPC"}'
    exit 1
fi
"##).unwrap();
    let registration = directory.path().join("diagnostic-cli.json");
    let mut config = serde_json::json!({
        "executable": executable,
        "sha256": format!("{:x}", Sha256::digest(std::fs::read(&executable).unwrap())),
        "source": "explicit_local_installation"
    });
    std::fs::write(&registration, serde_json::to_vec(&config).unwrap()).unwrap();
    let report = LocalDiagnostics::new(registration.clone())
        .run(DiagnosticKind::Service)
        .await
        .unwrap();
    assert_eq!(report.exit_code, 1);
    assert_eq!(report.cli_version.as_deref(), Some("1.3.0"));
    assert!(
        report
            .items
            .iter()
            .any(|item| item.field == "registration" && item.status == "not_installed")
    );
    assert!(
        !serde_json::to_string(&report)
            .unwrap()
            .contains("must-not-reach-IPC")
    );
    config["sha256"] = "0".repeat(64).into();
    std::fs::write(&registration, serde_json::to_vec(&config).unwrap()).unwrap();
    assert_eq!(
        LocalDiagnostics::new(registration)
            .run(DiagnosticKind::Service)
            .await
            .unwrap_err(),
        SafeError::CompatibilityUnverified
    );
}
