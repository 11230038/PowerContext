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

//! Bounded diagnostic execution in a private process group.
use crate::{diagnostics::OUTPUT_LIMIT, error::SafeError};
use std::{
    fs::File,
    io::Read,
    os::{
        fd::{AsRawFd, FromRawFd, IntoRawFd},
        unix::process::CommandExt,
    },
    path::Path,
    process::{Command, Stdio},
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc,
    },
    time::{Duration, Instant},
};

/// The collection threads poll in short slices so a cancellation signal is
/// observed while a foreign writer keeps the pipe alive without producing data.
const POLL_SLICE: Duration = Duration::from_millis(50);

pub(crate) struct Output {
    pub stdout: Vec<u8>,
    pub exit_code: i32,
}
struct Group(i32);
impl Drop for Group {
    fn drop(&mut self) {
        // The child creates its own group before exec. Never signal the app's group.
        unsafe {
            libc::kill(-self.0, libc::SIGKILL);
        }
    }
}
fn collect(
    reader: impl Read + IntoRawFd + Send + 'static,
    deadline: Instant,
    cancelled: Arc<AtomicBool>,
    total: Arc<AtomicUsize>,
    exceeded: Arc<AtomicBool>,
) -> mpsc::Receiver<Result<Vec<u8>, SafeError>> {
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        // Owning the descriptor lets the closure close the read end exactly once,
        // even when the caller stops listening before the writer outside the
        // killed process group releases the pipe.
        let mut file = unsafe { File::from_raw_fd(reader.into_raw_fd()) };
        let mut output = Vec::new();
        let mut buffer = [0; 8192];
        loop {
            if cancelled.load(Ordering::Relaxed) || Instant::now() >= deadline {
                break;
            }
            let slice = deadline
                .saturating_duration_since(Instant::now())
                .min(POLL_SLICE)
                .as_millis()
                .try_into()
                .unwrap_or(i32::MAX);
            let mut descriptor = libc::pollfd {
                fd: file.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            };
            let ready = unsafe { libc::poll(&mut descriptor, 1, slice) };
            if ready <= 0 {
                // Interrupted or no data yet; the schedule check above ends the loop.
                continue;
            }
            match file.read(&mut buffer) {
                Ok(0) => break,
                Ok(n) => {
                    if total.fetch_add(n, Ordering::Relaxed).saturating_add(n) > OUTPUT_LIMIT {
                        exceeded.store(true, Ordering::Relaxed);
                        break;
                    }
                    output.extend_from_slice(&buffer[..n]);
                }
                Err(_) => {
                    let _ = sender.send(Err(SafeError::Storage));
                    return;
                }
            }
        }
        let _ = sender.send(Ok(output));
    });
    receiver
}

/// Receives one bounded result; the reader always delivers before the deadline
/// or closes the pipe read end, so this never blocks a surviving writer.
fn receive(
    receiver: mpsc::Receiver<Result<Vec<u8>, SafeError>>,
    deadline: Instant,
) -> Option<Result<Vec<u8>, SafeError>> {
    let remaining = deadline.checked_duration_since(Instant::now())?;
    receiver.recv_timeout(remaining).ok()
}
pub(crate) fn run(
    executable: &Path,
    arguments: &[&str],
    timeout: Duration,
    cancelled: Arc<AtomicBool>,
) -> Result<Output, SafeError> {
    let mut child = Command::new(executable)
        .args(arguments)
        .current_dir(std::env::temp_dir())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .map_err(|_| SafeError::NotFound)?;
    let group = Group(child.id() as i32);
    let deadline = Instant::now() + timeout;
    let total = Arc::new(AtomicUsize::new(0));
    let exceeded = Arc::new(AtomicBool::new(false));
    let stdout = collect(
        child.stdout.take().unwrap(),
        deadline,
        cancelled.clone(),
        total.clone(),
        exceeded.clone(),
    );
    let stderr = collect(
        child.stderr.take().unwrap(),
        deadline,
        cancelled.clone(),
        total,
        exceeded.clone(),
    );
    let result = loop {
        if cancelled.load(Ordering::Relaxed) {
            break Err(SafeError::StaleContext);
        }
        if exceeded.load(Ordering::Relaxed) {
            break Err(SafeError::ResponseTooLarge);
        }
        if Instant::now() >= deadline {
            break Err(SafeError::Timeout);
        }
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status.code().unwrap_or(-1)),
            Ok(None) => std::thread::sleep(Duration::from_millis(10)),
            Err(_) => break Err(SafeError::Storage),
        }
    };
    drop(group);
    let _ = child.wait();
    let exit_code = match result {
        Ok(code) => code,
        Err(error) => {
            // A writer may survive outside the killed group and keep the pipes
            // open, so never block here; collection threads end by the deadline.
            return Err(error);
        }
    };
    let output = receive(stdout, deadline).unwrap_or(Ok(Vec::new()));
    let errors = receive(stderr, deadline).unwrap_or(Ok(Vec::new()));
    if exceeded.load(Ordering::Relaxed) {
        return Err(SafeError::ResponseTooLarge);
    }
    errors?;
    Ok(Output {
        stdout: output?,
        exit_code,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn shell(
        script: &str,
        timeout: Duration,
        cancelled: Arc<AtomicBool>,
    ) -> Result<Output, SafeError> {
        run(Path::new("/bin/sh"), &["-c", script], timeout, cancelled)
    }
    #[test]
    fn captures_output_and_nonzero_exit() {
        let result = shell(
            "printf synthetic; exit 1",
            Duration::from_secs(2),
            Arc::new(AtomicBool::new(false)),
        )
        .unwrap();
        assert_eq!(result.stdout, b"synthetic");
        assert_eq!(result.exit_code, 1);
    }
    #[test]
    fn surviving_pipe_writer_does_not_extend_shutdown() {
        let directory = tempfile::tempdir().unwrap();
        let pid_file = directory.path().join("escape.pid");
        let script = format!(
            "perl -e 'use POSIX; POSIX::setsid(); open(my $fh, q(>), $ARGV[0]) or die; print $fh $$; close($fh); sleep 300' '{}'",
            pid_file.display()
        );
        let started = Instant::now();
        let result = shell(
            &script,
            Duration::from_millis(200),
            Arc::new(AtomicBool::new(false)),
        );
        let elapsed = started.elapsed();
        assert_eq!(result.err(), Some(SafeError::Timeout));
        assert!(
            elapsed < Duration::from_secs(30),
            "bounded shutdown blocked {elapsed:?} behind a writer that escaped the killed group"
        );
        let pid: i32 = std::fs::read_to_string(&pid_file)
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        unsafe {
            libc::kill(-pid, libc::SIGKILL);
        }
    }
    #[test]
    fn timeout_and_live_cancellation_terminate_spawned_descendants() {
        for cancel in [false, true] {
            let directory = tempfile::tempdir().unwrap();
            let pid_file = directory.path().join("child.pid");
            let script = format!("sleep 30 & echo $! > '{}'; wait", pid_file.display());
            let flag = Arc::new(AtomicBool::new(false));
            let cancellation = if cancel {
                let flag = flag.clone();
                let pid_file = pid_file.clone();
                Some(std::thread::spawn(move || {
                    let deadline = Instant::now() + Duration::from_secs(2);
                    while !pid_file.exists() && Instant::now() < deadline {
                        std::thread::sleep(Duration::from_millis(10));
                    }
                    flag.store(true, Ordering::Relaxed);
                }))
            } else {
                None
            };
            let result = shell(
                &script,
                Duration::from_millis(if cancel { 3000 } else { 200 }),
                flag,
            );
            if let Some(thread) = cancellation {
                thread.join().unwrap();
            }
            assert_eq!(
                result.err(),
                Some(if cancel {
                    SafeError::StaleContext
                } else {
                    SafeError::Timeout
                })
            );
            let pid: i32 = std::fs::read_to_string(pid_file)
                .unwrap()
                .trim()
                .parse()
                .unwrap();
            let deadline = Instant::now() + Duration::from_secs(2);
            loop {
                let status = Command::new("/bin/ps")
                    .args(["-o", "stat=", "-p", &pid.to_string()])
                    .output()
                    .unwrap();
                let state = String::from_utf8_lossy(&status.stdout);
                if state.trim().is_empty() || state.trim().starts_with('Z') {
                    break;
                }
                assert!(
                    Instant::now() < deadline,
                    "diagnostic descendant remains running"
                );
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }

    #[test]
    fn bounds_output_deadline_and_cancellation() {
        assert!(matches!(
            shell(
                "yes synthetic",
                Duration::from_secs(2),
                Arc::new(AtomicBool::new(false))
            ),
            Err(SafeError::ResponseTooLarge)
        ));
        assert!(matches!(
            shell(
                "sleep 30 & wait",
                Duration::from_millis(100),
                Arc::new(AtomicBool::new(false))
            ),
            Err(SafeError::Timeout)
        ));
        assert!(matches!(
            shell(
                "sleep 30",
                Duration::from_secs(2),
                Arc::new(AtomicBool::new(true))
            ),
            Err(SafeError::StaleContext)
        ));
    }
}
