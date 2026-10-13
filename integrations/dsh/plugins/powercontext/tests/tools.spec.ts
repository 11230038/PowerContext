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

import { describe, expect, it, vi } from 'vitest'
import { registerTools } from '../src/tools.ts'
import type { PluginRuntime } from '../src/invoke.ts'

describe('agent tool surface', () => {
  it('registers only explicit agent tools and does not expose generic or destructive operations', () => {
    const registered: Array<Record<string, unknown>> = []
    let preExecute: ((exec: { name: string }, next: () => Promise<unknown>) => Promise<unknown>) | undefined
    const runtime = {
      client: {} as never,
      config: { maxBytes: 8000 },
      resolveScope: vi.fn(async () => 'project:demo'),
      log: vi.fn(),
    } as unknown as PluginRuntime

    registerTools(
      {
        tools: { register: (tool) => registered.push(tool as Record<string, unknown>) },
        on: (event, handler) => {
          if (event === 'tools/pre-execute') preExecute = handler as never
        },
      },
      runtime,
      (definition) => definition,
    )

    const names = registered.map((tool) => tool.name)
    expect(names).toEqual([
      'pc_search',
      'pc_remember',
      'pc_memory_list',
      'pc_memory_get',
      'pc_memory_state',
      'pc_memory_revise',
      'pc_memory_retire',
      'pc_prepare_context',
      'pc_capture_source',
      'pc_capture_working_note',
      'pc_handoff_activate',
      'pc_handoff_prepare',
      'pc_handoff_finalize',
      'pc_handoff_commit',
      'pc_handoff_continue',
      'pc_experience_generate',
      'pc_experience_get',
      'pc_skill_generate',
      'pc_skill_get',
      'pc_review_list',
      'pc_review_get',
    ])
    expect(names).not.toContain('pc_call')
    expect(names).not.toContain('purge_handoff_report_activities')
    expect(names).not.toContain('detach_handoff_report_workspace')
    expect(names).not.toContain('approve_artifact_candidate')
    expect(preExecute).toBeTypeOf('function')
  })

  it('requires one-time approval for named mutations and delegates reads', async () => {
    let preExecute: ((exec: { name: string }, next: () => Promise<unknown>) => Promise<unknown>) | undefined
    const runtime = {
      client: {} as never,
      config: { maxBytes: 8000 },
      resolveScope: vi.fn(async () => 'project:demo'),
      log: vi.fn(),
    } as unknown as PluginRuntime
    registerTools(
      {
        tools: { register: vi.fn() },
        on: (event, handler) => {
          if (event === 'tools/pre-execute') preExecute = handler as never
        },
      },
      runtime,
      (definition) => definition,
    )
    const next = vi.fn(async () => ({ kind: 'allow' }))

    await expect(preExecute?.({ name: 'pc_remember' }, next)).resolves.toEqual({
      kind: 'ask',
      reason: 'PowerContext tool "pc_remember" changes durable project context.',
    })
    expect(next).not.toHaveBeenCalled()
    await expect(preExecute?.({ name: 'pc_capture_working_note' }, next)).resolves.toEqual({
      kind: 'ask',
      reason: 'PowerContext tool "pc_capture_working_note" changes durable project context.',
    })
    await expect(preExecute?.({ name: 'pc_search' }, next)).resolves.toEqual({ kind: 'allow' })
    expect(next).toHaveBeenCalledOnce()
  })

  it('returns unscoped when the session has no workspace and scopeId is not configured', async () => {
    const registered: Array<{
      name: string
      execute: (args: Record<string, unknown>, exec: unknown) => Promise<unknown>
    }> = []
    registerTools(
      {
        tools: { register: (tool) => registered.push(tool as never) },
        on: () => undefined,
      },
      {
        client: {} as never,
        config: { maxBytes: 8000 },
        resolveScope: async (cwd?: string) => cwd ? 'scp_from_server' : undefined,
        log: vi.fn(),
      } as unknown as PluginRuntime,
      (definition) => definition,
    )
    const search = registered.find((tool) => tool.name === 'pc_search')
    const result = await search?.execute({ query: 'public API' }, {
      signal: AbortSignal.timeout(1000),
      agent: { session: { header: { id: 's1' } } },
    })
    expect(result).toMatchObject({
      ok: false,
      code: 'unscoped',
    })
  })

  it('routes Working Note capture through the scoped operation', async () => {
    const registered: Array<{
      name: string
      execute: (args: Record<string, unknown>, exec: unknown) => Promise<unknown>
    }> = []
    const request = vi.fn(async () => ({
      kind: 'json' as const,
      value: { status: 'accepted', source: { name: 'content', source_id: 'note-1' }, position: 1 },
      status: 202,
      requestId: undefined,
    }))
    registerTools(
      {
        tools: { register: (tool) => registered.push(tool as never) },
        on: () => undefined,
      },
      {
        client: { request } as never,
        config: { maxBytes: 8000 },
        resolveScope: vi.fn(async () => 'project:demo'),
        log: vi.fn(),
      } as unknown as PluginRuntime,
      (definition) => definition,
    )

    const capture = registered.find((tool) => tool.name === 'pc_capture_working_note')
    const result = await capture?.execute({
      source_id: 'note-1',
      content: 'Parser validation is still in progress.',
      session_id: 'session-1',
      note_kind: 'validation',
      expires_at: '2030-01-02T00:00:00Z',
    }, {
      signal: AbortSignal.timeout(1000),
      agent: { session: { header: { cwd: '/workspace/repo' } } },
    })

    expect(result).toMatchObject({ ok: true, status: 202 })
    expect(request).toHaveBeenCalledWith('capture_working_note', {
      source_id: 'note-1',
      content: 'Parser validation is still in progress.',
      session_id: 'session-1',
      note_kind: 'validation',
      expires_at: '2030-01-02T00:00:00Z',
      scope_id: 'project:demo',
    }, expect.any(AbortSignal))
  })
})
